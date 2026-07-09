# brave_image_search.py
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from io import BytesIO

from fastmcp import FastMCP

if sys.platform == "win32":
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

mcp = FastMCP("BraveImageSearch")


async def _curl(url: str, headers: dict = None, timeout: int = 20) -> bytes:
    import socket
    from urllib.parse import urlparse

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
                if f"has address" in line:
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

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"curl exit {proc.returncode}: {stderr.decode()[:200]}")
    return stdout


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

    from urllib.parse import urlencode
    params = urlencode({"q": query, "count": min(count, 200), "safesearch": safesearch})
    url = f"https://api.search.brave.com/res/v1/images/search?{params}"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }

    try:
        data = await _curl(url, headers)
        results = json.loads(data).get("results", [])
    except Exception as e:
        return f"Error searching images: {str(e)}"

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
        thumb = img.get("thumbnail", {}).get("src", "")
        lines.append(
            f"Title: {title}\nURL: {orig_url}\nThumb: {thumb}\nSource: {img.get('url', '')}{dims}\n---"
        )
        seen += 1

    return "\n".join(lines) if lines else "No images found."


@mcp.tool()
async def prepare_image_for_screen(url: str, thumb_url: str = "") -> str:
    """Download image, convert to small PNG (max 320x240), upload to catbox.moe, return public URL for device display."""
    from PIL import Image

    download_url = thumb_url if thumb_url else url
    tmp_img = "/tmp/mcp_download_img"

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

    with open(tmp_img, "wb") as f:
        f.write(png_data)

    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "--max-time", "20",
            "-F", "reqtype=fileupload",
            "-F", f"fileToUpload=@{tmp_img};filename=image.png;type=image/png",
            "https://catbox.moe/user/api.php",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
        result_url = stdout.decode().strip()
        if result_url.startswith("http"):
            return result_url
    except Exception:
        pass
    finally:
        try:
            os.unlink(tmp_img)
        except Exception:
            pass

    return "Error: Could not upload image."


if __name__ == "__main__":
    mcp.run(transport="stdio")
