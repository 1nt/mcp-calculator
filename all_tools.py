import asyncio
import json
import os
import subprocess
import sys
from urllib.parse import urlencode, urlparse

from fastmcp import FastMCP

if sys.platform == "win32":
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

mcp = FastMCP("AllTools")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")


def _hostname_to_ip(host: str, timeout: int = 3) -> str:
    import socket
    for dns in ["8.8.8.8", "1.1.1.1", "208.67.222.222"]:
        try:
            proc = subprocess.run(
                ["host", host, dns],
                capture_output=True, text=True, timeout=timeout
            )
            for line in proc.stdout.splitlines():
                if "has address" in line:
                    return line.split()[-1]
        except Exception:
            continue
    return ""


async def _curl(url: str, headers: dict = None, timeout: int = 20) -> bytes:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    ip = _hostname_to_ip(host)

    cmd = ["curl", "-s", "--max-time", str(timeout)]
    if ip:
        cmd += ["--resolve", f"{host}:{port}:{ip}"]
    if headers:
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"curl exit {proc.returncode}: {stderr.decode()[:200]}")
    return stdout


@mcp.tool()
async def search_brave(query: str) -> str:
    """Search the web using the Brave Search API when you need real-time information."""
    if not BRAVE_API_KEY:
        return "Error: BRAVE_API_KEY is not set."

    params = urlencode({"q": query})
    url = f"https://api.search.brave.com/res/v1/web/search?{params}"
    headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY}

    try:
        data = await _curl(url, headers)
        results = json.loads(data).get("web", {}).get("results", [])
    except Exception as e:
        return f"Error: {str(e)}"

    snippets = []
    for r in results[:5]:
        snippets.append(f"Title: {r.get('title')}\nURL: {r.get('url')}\nDescription: {r.get('description')}\n---")
    return "\n".join(snippets) if snippets else "No results found."


@mcp.tool()
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression. Supports +, -, *, /, **, sqrt, sin, cos, etc."""
    import math
    allowed = set("0123456789.+-*/()% ,sqrtcossin tanlogabsfloorceilpi e")
    if not all(c in allowed for c in expression.lower()):
        return "Error: Invalid characters in expression."
    try:
        result = eval(expression, {"__builtins__": {}}, vars(math))
        return f"{result:.4f}" if isinstance(result, float) else str(result)
    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
