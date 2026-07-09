# brave_image_search.py
from fastmcp import FastMCP
import sys
import os
import httpx
from io import BytesIO

if sys.platform == "win32":
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

mcp = FastMCP("BraveImageSearch")


@mcp.tool()
async def search_images(
    query: str,
    count: int = 10,
    safesearch: str = "strict",
) -> str:
    """Search for images using Brave API. Returns image URLs and metadata."""
    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        return "Error: BRAVE_API_KEY is not set."

    url = "https://api.search.brave.com/res/v1/images/search"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": min(count, 200), "safesearch": safesearch}

    timeout = httpx.Timeout(15.0, connect=10.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return "No images found."

            lines = []
            seen = 0
            for img in results:
                if seen >= count:
                    break
                orig_url = img.get("properties", {}).get("url", "")
                if not orig_url:
                    continue
                title = img.get("title", "")
                w = img.get("properties", {}).get("width", 0) or 0
                h = img.get("properties", {}).get("height", 0) or 0
                dims = f" {w}x{h}" if w and h else ""
                lines.append(
                    f"Title: {title}\nURL: {orig_url}\nSource: {img.get('url', '')}{dims}\n---"
                )
                seen += 1

            return "\n".join(lines) if lines else "No images found."

    except httpx.ConnectTimeout:
        return "Error: Connection timeout to Brave Image Search API."
    except httpx.HTTPStatusError as e:
        return f"Error API (status {e.response.status_code}): {e.response.text}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


@mcp.tool()
async def prepare_image_for_screen(url: str) -> str:
    """Download image from URL, convert to small PNG (max 320x240), upload to temp host, return public URL for device display."""
    from PIL import Image

    timeout = httpx.Timeout(30.0, connect=15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            r = await client.get(url)
            r.raise_for_status()
    except Exception as e:
        return f"Error downloading: {str(e)}"

    try:
        img = Image.open(BytesIO(r.content))
    except Exception as e:
        return f"Error decoding: {str(e)}"

    if img.mode != "RGBA":
        img = img.convert("RGBA")

    img.thumbnail((320, 240), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="PNG")
    png_data = buf.getvalue()

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            up = await client.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": ("image.png", png_data, "image/png")}
            )
            if up.status_code == 200:
                url = up.text.strip()
                if url.startswith("http"):
                    return url
    except Exception:
        pass

    return "Error: Could not upload image."


if __name__ == "__main__":
    mcp.run(transport="stdio")
