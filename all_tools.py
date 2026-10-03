import asyncio
import json
import os
import subprocess
import sys
import time
from urllib.parse import urlencode, urlparse

from fastmcp import FastMCP
import yt_dlp

if sys.platform == "win32":
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

mcp = FastMCP("AllTools")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")

# ==========================================
# Network Helpers for Brave Search
# ==========================================

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


# ==========================================
# 1. Search Tool (Brave Search)
# ==========================================

@mcp.tool()
async def search_brave(query: str) -> str:
    """Search the web using the Brave Search API when you need real-time information.
    Используй для поиска актуальной информации в интернете."""
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


# ==========================================
# 2. Calculator Tool
# ==========================================

@mcp.tool()
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression. Supports +, -, *, /, **, sqrt, sin, cos, etc.
    Используй для математических вычислений."""
    import math
    allowed = set("0123456789.+-*/()% ,sqrtcossin tanlogabsfloorceilpi e")
    if not all(c in allowed for c in expression.lower()):
        return "Error: Invalid characters in expression."
    try:
        result = eval(expression, {"__builtins__": {}}, vars(math))
        return f"{result:.4f}" if isinstance(result, float) else str(result)
    except Exception as e:
        return f"Error: {str(e)}"


# ==========================================
# 3. Music Tools (Direct Audio Playback)
# ==========================================

_music_cache: dict[str, tuple[float, dict]] = {}
_current_track: dict = {}
_is_playing: bool = False


def _extract_audio_stream(query: str) -> dict:
    global _music_cache, _current_track, _is_playing
    cache_key = query.lower().strip()
    now = time.time()

    if cache_key in _music_cache:
        cached_time, cached_data = _music_cache[cache_key]
        if now - cached_time < 3600:
            _current_track = cached_data
            _is_playing = True
            return cached_data

    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 15,
    }

    target = query if (query.startswith("http://") or query.startswith("https://")) else f"ytsearch1:{query}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(target, download=False)
        entry = info["entries"][0] if "entries" in info else info
        title = entry.get("title") or query
        artist = entry.get("uploader") or entry.get("artist") or ""
        duration = entry.get("duration") or 0
        audio_url = entry.get("url") or ""

        track_data = {
            "success": True,
            "title": title,
            "artist": artist,
            "duration_seconds": duration,
            "url": audio_url,
            "audio_url": audio_url,
            "stream_url": audio_url,
            "action": "play",
            "should_play": True,
            "reply_for_tts": f"Включаю {title}",
            "message": f"Воспроизводится: {title}. Прямой аудиопоток получен.",
        }

        # Keep cache bounded
        if len(_music_cache) > 100:
            oldest_key = min(_music_cache.keys(), key=lambda k: _music_cache[k][0])
            del _music_cache[oldest_key]

        _music_cache[cache_key] = (now, track_data)
        _current_track = track_data
        _is_playing = True
        return track_data


def _search_tracks(query: str, limit: int = 5) -> dict:
    limit = max(1, min(limit, 10))
    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "socket_timeout": 10,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        entries = info.get("entries", []) if info else []
        tracks = []
        for e in entries:
            tracks.append({
                "title": e.get("title"),
                "artist": e.get("uploader") or e.get("channel") or "",
                "duration_seconds": e.get("duration"),
                "url": e.get("url"),
            })
        return {
            "success": True,
            "query": query,
            "count": len(tracks),
            "tracks": tracks,
            "reply_for_tts": f"Найдено треков: {len(tracks)}"
        }


@mcp.tool()
async def play_music(song_name: str, artist: str = "") -> dict:
    """Play a music track or song by name and optional artist.
    Searches for the audio track and returns the direct audio stream URL for playback.
    Используй этот инструмент, когда пользователь просит включить песню, трек или музыку.

    Args:
        song_name: The name or title of the song, keywords, or a direct audio URL.
        artist: The artist, singer, or band name (optional).
    """
    parts = []
    if artist and artist.lower() not in song_name.lower():
        parts.append(artist.strip())
    parts.append(song_name.strip())
    query = " ".join(parts)

    try:
        return await asyncio.to_thread(_extract_audio_stream, query)
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Не удалось найти песню по запросу '{query}': {str(e)}",
            "reply_for_tts": f"К сожалению, не удалось найти песню {song_name}."
        }


@mcp.tool()
def pause_music() -> dict:
    """Pause currently playing music.
    Используй для паузы воспроизведения музыки."""
    global _is_playing
    _is_playing = False
    return {
        "success": True,
        "action": "pause",
        "should_play": False,
        "reply_for_tts": "Воспроизведение приостановлено",
        "message": "Музыка поставлена на паузу."
    }


@mcp.tool()
def resume_music() -> dict:
    """Resume paused music playback.
    Используй для возобновления воспроизведения музыки."""
    global _is_playing
    if not _current_track:
        return {
            "success": False,
            "message": "Нет трека для возобновления воспроизведения.",
            "reply_for_tts": "Нет трека на паузе."
        }
    _is_playing = True
    title = _current_track.get("title", "")
    url = _current_track.get("url", "")
    return {
        "success": True,
        "action": "resume",
        "should_play": True,
        "title": title,
        "artist": _current_track.get("artist", ""),
        "url": url,
        "audio_url": url,
        "stream_url": url,
        "reply_for_tts": f"Продолжаю воспроизведение: {title}",
        "message": f"Возобновлено воспроизведение: {title}"
    }


@mcp.tool()
def stop_music() -> dict:
    """Stop music playback.
    Используй для полной остановки музыки."""
    global _is_playing
    _is_playing = False
    return {
        "success": True,
        "action": "stop",
        "should_play": False,
        "reply_for_tts": "Музыка остановлена",
        "message": "Воспроизведение музыки остановлено."
    }


@mcp.tool()
def get_current_music() -> dict:
    """Get information about the currently playing music track.
    Используй, когда пользователь спрашивает 'что сейчас играет'."""
    if not _current_track:
        return {
            "success": False,
            "is_playing": False,
            "message": "Сейчас ничего не играет.",
            "reply_for_tts": "Сейчас ничего не воспроизводится."
        }
    title = _current_track.get("title", "")
    artist = _current_track.get("artist", "")
    return {
        "success": True,
        "is_playing": _is_playing,
        "title": title,
        "artist": artist,
        "track": _current_track,
        "reply_for_tts": f"Сейчас играет {title}" if _is_playing else f"На паузе: {title}"
    }


@mcp.tool()
async def search_music(query: str, limit: int = 5) -> dict:
    """Search for music tracks matching the query without playing them.
    Используй для поиска списка треков или песен исполнителя.

    Args:
        query: Search keywords (e.g. artist, album, song title).
        limit: Number of results to return (default 5, max 10).
    """
    try:
        return await asyncio.to_thread(_search_tracks, query, limit)
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Ошибка поиска: {str(e)}",
            "reply_for_tts": "Не удалось выполнить поиск песен."
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
