# brave_search.py
from fastmcp import FastMCP
import sys
import os
import httpx

# Исправление кодировки для стабильного stdio пайпа
if sys.platform == 'win32':
    sys.stderr.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')

# 1. Создаем сервер MCP через FastMCP
mcp = FastMCP("BraveSearch")

# 2. Вешаем декоратор, чтобы FastMCP сам сделал схему для MCP
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
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        results = response.json()
        
        # Собираем только компактные сниппеты, чтобы не раздувать размер схемы
        snippets = []
        for web in results.get("web", {}).get("results", [])[:5]:
            snippets.append(f"Title: {web.get('title')}\nURL: {web.get('url')}\nDescription: {web.get('description')}\n---")
        
        return "\n".join(snippets) if snippets else "No results found."

# 3. Запускаем бесконечный stdio-сервер
if __name__ == "__main__":
    mcp.run(transport="stdio")

