# brave_search.py
from fastmcp import FastMCP
import sys
import os
import httpx

# Исправление кодировки для стабильного stdio пайпа
if sys.platform == 'win32':
    sys.stderr.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')

mcp = FastMCP("BraveSearch")

@mcp.tool()
async def search_brave(query: str) -> str:
    """Search the web using the Brave Search API when you need real-time information."""
    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        return "Error: BRAVE_API_KEY is not set."

    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key
    }
    params = {"q": query}
    
    # Увеличиваем таймаут подключения до 15 секунд и включаем доверие системным прокси
    timeout = httpx.Timeout(15.0, connect=10.0)
    
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            results = response.json()
            
            snippets = []
            for web in results.get("web", {}).get("results", [])[:5]:
                snippets.append(f"Title: {web.get('title')}\nURL: {web.get('url')}\nDescription: {web.get('description')}\n---")
            
            return "\n".join(snippets) if snippets else "No results found."
            
    except httpx.ConnectTimeout:
        return "Ошибка: Не удалось подключиться к серверам Brave Search API (Таймаут соединения). Проверьте сетевое подключение или прокси."
    except httpx.HTTPStatusError as e:
        return f"Ошибка API Brave (Статус {e.response.status_code}): {e.response.text}"
    except Exception as e:
        return f"Непредвиденная ошибка сети: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="stdio")

