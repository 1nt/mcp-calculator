# image_tool.py
import asyncio
import hashlib
import os
import socket
import sys
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from io import BytesIO
from pathlib import Path

import httpx
from fastmcp import FastMCP
from PIL import Image

if sys.platform == "win32":
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

mcp = FastMCP("ImageTool")

IMAGE_DIR = Path("/tmp/mcp_images")
IMAGE_DIR.mkdir(exist_ok=True)

_server_port = None
_server_started = False
_server_lock = threading.Lock()


def _get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _start_http_server():
    global _server_port, _server_started
    with _server_lock:
        if _server_started:
            return
        os.chdir(str(IMAGE_DIR))

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def guess_type(self, path):
                return "image/jpeg"

        for port in range(9090, 9100):
            try:
                server = HTTPServer(("0.0.0.0", port), Handler)
                _server_port = port
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                _server_started = True
                return
            except OSError:
                continue
        raise RuntimeError("Could not find free port")


@mcp.tool()
async def convert_image_for_screen(
    url: str,
    max_width: int = 320,
    max_height: int = 240,
) -> str:
    """Download an image from a URL, resize it to fit the screen, convert to JPEG, and return a URL to access it."""
    local_ip = _get_local_ip()
    _start_http_server()

    timeout = httpx.Timeout(30.0, connect=15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            img_data = r.content
    except Exception as e:
        return f"Error downloading image: {str(e)}"

    try:
        img = Image.open(BytesIO(img_data))
    except Exception as e:
        return f"Error decoding image: {str(e)}"

    img.thumbnail((max_width, max_height), Image.LANCZOS)

    if img.mode != "RGB":
        img = img.convert("RGB")

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    jpeg_data = buf.getvalue()

    name = hashlib.md5(url.encode()).hexdigest() + ".jpg"
    dest = IMAGE_DIR / name
    with open(dest, "wb") as f:
        f.write(jpeg_data)

    return f"http://{local_ip}:{_server_port}/{name}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
