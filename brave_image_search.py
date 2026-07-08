# brave_image_search.py
from fastmcp import FastMCP
import sys
import os
import httpx

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
    """Search for images using the Brave Image Search API. Returns image results with thumbnails, titles, and source URLs."""
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

            results = data.get("results", [])[:count]
            if not results:
                return "No images found."

            lines = []
            for img in results:
                title = img.get("title", "")
                thumb = img.get("thumbnail", {}).get("src", "")
                orig_url = img.get("url", "")
                page_url = img.get("page_url", "https://www.mysql.com/")
                w = img.get("properties", {}).get("width", "")
                h = img.get("properties", {}).get("height", "")
                dims = f" {w}x{h}" if w and h else ""
                lines.append(
                    f"Title: {title}\nThumbnail: {thumb}\nURL: {orig_url}\nSource: {page_url}{dims}\n---"
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
