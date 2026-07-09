# all_tools.py - Combined MCP server with all tools
import asyncio
import json
import os
import subprocess
import sys
import socket
from io import BytesIO
from urllib.parse import urlencode, urlparse

from fastmcp import FastMCP

if sys.platform == "win32":
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

mcp = FastMCP("AllTools")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")


async def _curl(url: str, headers: dict = None, timeout: int = 20) -> bytes:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    ip = None
    for dns in ["8.8.8.8", "1.1.1.1", "208.67.222.222"]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "host", host, dns,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
            for line in stdout.decode().splitlines():
                if "has address" in line:
                    ip = line.split()[-1]
                    break
            if ip:
                break
        except Exception:
            continue

    if ip:
        cmd = ["curl", "-s", "--max-time", str(timeout), "--resolve", f"{host}:{port}:{ip}"]
    else:
        cmd = ["curl", "-s", "--max-time", str(timeout)]

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
        snippets.append(f"Title: {r.get(title)}\nURL: {r.get(url)}\nDescription: {r.get(description)}\n---")
    return "\n".join(snippets) if snippets else "No results found."


@mcp.tool()
async def search_images(query: str, count: int = 10, safesearch: str = "strict") -> str:
    """Search for images using Brave API. Returns image URLs with Thumb and Source."""
    if not BRAVE_API_KEY:
        return "Error: BRAVE_API_KEY is not set."

    params = urlencode({"q": query, "count": min(count, 200), "safesearch": safesearch})
    url = f"https://api.search.brave.com/res/v1/images/search?{params}"
    headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY}

    try:
        data = await _curl(url, headers)
        results = json.loads(data).get("results", [])
    except Exception as e:
        return f"Error searching images: {str(e)}"

    if not results:
        return "No images found."

    lines = []
    for img in results:
        if len(lines) >= count:
            break
        orig_url = img.get("properties", {}).get("url", "")
        if not orig_url:
            continue
        title = img.get("title", "")
        w = img.get("properties", {}).get("width", 0) or 0
        h = img.get("properties", {}).get("height", 0) or 0
        dims = f" {w}x{h}" if w and h else ""
        thumb = img.get("thumbnail", {}).get("src", "")
        lines.append(f"Title: {title}\nURL: {orig_url}\nThumb: {thumb}\nSource: {img.get(url, )}{dims}\n---")

    return "\n".join(lines) if lines else "No images found."


@mcp.tool()
async def prepare_image_for_screen(url: str, thumb_url: str = "") -> str:
    """Download image, convert to small PNG (max 320x240), upload to catbox.moe, After getting this URL, you MUST call screen.preview_image(url) on the device to display it."""
    from PIL import Image

    download_url = thumb_url if thumb_url else url

    try:
        data = await _curl(download_url, {"User-Agent": "Mozilla/5.0"}, timeout=15)
    except Exception:
        if not thumb_url:
            return "Error downloading image."
        try:
            data = await _curl(url, {"User-Agent": "Mozilla/5.0"}, timeout=20)
        except Exception as e:
            return f"Error downloading: {str(e)}"

    try:
        img = Image.open(BytesIO(data))
    except Exception as e:
        return f"Error decoding: {str(e)}"

    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((320, 240), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="PNG")
    png_data = buf.getvalue()

    tmp = "/tmp/mcp_preview.png"
    with open(tmp, "wb") as f:
        f.write(png_data)

    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--max-time", "20",
            "-F", "reqtype=fileupload",
            "-F", f"fileToUpload=@{tmp};filename=image.png;type=image/png",
            "https://catbox.moe/user/api.php",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
        result = stdout.decode().strip()
        if result.startswith("http"):
            return result
    except Exception:
        pass
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass

    return "Error: Could not upload image."


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
