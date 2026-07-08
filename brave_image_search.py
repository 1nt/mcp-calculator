# brave_image_search.py
from fastmcp import FastMCP
import sys
import os
import httpx

if sys.platform == "win32":
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

mcp = FastMCP("BraveImageSearch")
_SUPPORTED_EXT = (".jpg", ".jpeg", ".png")


@mcp.tool()
async def search_images(
    query: str,
    count: int = 10,
    safesearch: str = "strict",
) -> str:
    """Search for images using the Brave Image Search API. Returns only JPEG/PNG images with direct source URLs suitable for display."""
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
                ext = os.path.splitext(orig_url.split("?")[0])[1].lower()
                if ext not in _SUPPORTED_EXT:
                    continue

                title = img.get("title", "")
                w = img.get("properties", {}).get("width", "")
                h = img.get("properties", {}).get("height", "")
                dims = f" {w}x{h}" if w and h else ""
                lines.append(
                    f"Title: {title}\nURL: {orig_url}\nSource: {img.get('page_url', '')}{dims}\n---"
                )
                seen += 1

            if not lines:
                return (
                    "No JPEG/PNG images found. Try a different query or "
                    "use convert_image_for_screen tool with any image URL."
                )
            return "\n".join(lines)

    except httpx.ConnectTimeout:
        return "Error: Connection timeout to Brave Image Search API."
    except httpx.HTTPStatusError as e:
        return f"Error API (status {e.response.status_code}): {e.response.text}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
