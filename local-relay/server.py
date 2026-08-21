from __future__ import annotations

import argparse
import re
from typing import Any

import httpx
import yt_dlp
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

BVID_RE = re.compile(r"BV[0-9A-Za-z]{10,}")
BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}

TOKEN = ""
BROWSER = "chrome"
app = FastAPI(title="Bilibili Video Reader Local Relay", docs_url=None, redoc_url=None)


class VideoRequest(BaseModel):
    url: str


class TranscriptRequest(BaseModel):
    url: str
    part: int = Field(default=1, ge=1)
    language: str = "auto"
    max_chars: int = Field(default=120000, ge=2000, le=250000)


class CaptureLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        self.warnings.append(str(msg))

    def error(self, msg: str) -> None:
        self.warnings.append(str(msg))


def require_token(token: str) -> None:
    if not TOKEN or token != TOKEN:
        raise HTTPException(status_code=404, detail="Not found")


def resolve_bvid(value: str) -> str:
    match = BVID_RE.search(value or "")
    if match:
        return match.group(0)
    raise ValueError("A BV ID was not found in the supplied URL.")


def bili_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    with httpx.Client(headers=BASE_HEADERS, follow_redirects=True, timeout=20.0) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Bilibili returned invalid JSON.")
    return data


def direct_parts(url: str) -> dict[str, Any]:
    bvid = resolve_bvid(url)
    payload = bili_json("https://api.bilibili.com/x/web-interface/view", {"bvid": bvid})
    if payload.get("code") != 0:
        raise RuntimeError(
            f"Bilibili metadata API error: {payload.get('message') or 'unknown'} "
            f"(code {payload.get('code')})."
        )
    data = payload.get("data") or {}
    pages = data.get("pages") if isinstance(data.get("pages"), list) else []
    if not pages and data.get("cid"):
        pages = [{
            "page": 1,
            "cid": data.get("cid"),
            "part": data.get("title") or "P1",
            "duration": data.get("duration"),
        }]
    parts = []
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or not page.get("cid"):
            continue
        part = int(page.get("page") or index)
        parts.append({
            "part": part,
            "cid": int(page["cid"]),
            "title": str(page.get("part") or f"P{part}"),
            "duration_seconds": int(page["duration"]) if page.get("duration") is not None else None,
            "url": f"https://www.bilibili.com/video/{bvid}?p={part}",
        })
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
    return {
        "status": "ok",
        "bvid": bvid,
        "title": str(data.get("title") or "") or None,
        "author": str(owner.get("name") or "") or None,
        "description": str(data.get("desc") or "") or None,
        "total_parts": len(parts),
        "fetch_strategy": "local_residential_api",
        "parts": parts,
    }


def ydl_options(*, playlist: bool, logger: CaptureLogger) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "logger": logger,
        "socket_timeout": 25,
        "retries": 1,
        "fragment_retries": 1,
        "cookiesfrombrowser": (BROWSER,),
    }
    if playlist:
        options.update({
            "extract_flat": "in_playlist",
            "noplaylist": False,
        })
    else:
        options.update({
            "noplaylist": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "listsubtitles": False,
        })
    return options


def ydl_parts(url: str) -> dict[str, Any]:
    bvid = resolve_bvid(url)
    logger = CaptureLogger()
    with yt_dlp.YoutubeDL(ydl_options(playlist=True, logger=logger)) as ydl:
        info = ydl.extract_info(f"https://www.bilibili.com/video/{bvid}", download=False)
    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp returned no video information.")
    entries = info.get("entries") if isinstance(info.get("entries"), list) else []
    if entries:
        parts = []
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                continue
            entry_url = str(entry.get("url") or f"https://www.bilibili.com/video/{bvid}?p={index}")
            parts.append({
                "part": index,
                "cid": entry.get("cid"),
                "title": str(entry.get("title") or entry.get("id") or f"P{index}"),
                "duration_seconds": int(entry["duration"]) if entry.get("duration") is not None else None,
                "url": entry_url,
            })
        return {
            "status": "ok",
            "bvid": bvid,
            "title": str(info.get("title") or "") or None,
            "author": str(info.get("uploader") or "") or None,
            "description": str(info.get("description") or "") or None,
            "total_parts": len(parts),
            "fetch_strategy": "local_yt_dlp",
            "parts": parts,
        }
    return {
        "status": "ok",
        "bvid": bvid,
        "title": str(info.get("title") or "") or None,
        "author": str(info.get("uploader") or "") or None,
        "description": str(info.get("description") or "") or None,
        "total_parts": 1,
        "fetch_strategy": "local_yt_dlp",
        "parts": [{
            "part": 1,
            "cid": info.get("cid"),
            "title": str(info.get("title") or "P1"),
            "duration_seconds": int(info["duration"]) if info.get("duration") is not None else None,
            "url": f"https://www.bilibili.com/video/{bvid}?p=1",
        }],
    }


def get_parts(url: str) -> dict[str, Any]:
    try:
        return direct_parts(url)
    except Exception as direct_error:
        try:
            result = ydl_parts(url)
            result["direct_api_warning"] = str(direct_error)
            return result
        except Exception as ydl_error:
            raise RuntimeError(f"Local Bilibili access failed: API={direct_error}; yt-dlp={ydl_error}") from ydl_error


def parse_srt_time(value: str) -> float:
    match = re.fullmatch(r"(\d+):(\d+):(\d+)[,.](\d+)", value.strip())
    if not match:
        return 0.0
    h, m, s, ms = (int(x) for x in match.groups())
    return h * 3600 + m * 60 + s + ms / (1000 if len(match.group(4)) == 3 else 100)


def timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def srt_segments(srt: str, max_chars: int) -> tuple[list[dict[str, Any]], str]:
    normalized = srt.replace("\r\n", "\n").strip()
    blocks = re.split(r"\n\s*\n", normalized)
    segments: list[dict[str, Any]] = []
    lines_out: list[str] = []
    chars = 0
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue
        timing_index = 1 if re.fullmatch(r"\d+", lines[0].strip()) else 0
        if timing_index >= len(lines) or "-->" not in lines[timing_index]:
            continue
        left, right = (x.strip() for x in lines[timing_index].split("-->", 1))
        text = " ".join(line.strip() for line in lines[timing_index + 1:]).strip()
        if not text:
            continue
        start = parse_srt_time(left)
        end = parse_srt_time(right)
        stamp = timestamp(start)
        out_line = f"[{stamp}] {text}"
        if chars + len(out_line) + 1 > max_chars:
            break
        chars += len(out_line) + 1
        lines_out.append(out_line)
        segments.append({"start": start, "end": end, "timestamp": stamp, "text": text})
    return segments, "\n".join(lines_out)


def choose_language(keys: list[str], preferred: str) -> str | None:
    real = [key for key in keys if key.lower() not in {"danmaku", "live_chat"}]
    if not real:
        return None
    pref = (preferred or "auto").lower()
    if pref != "auto":
        for key in real:
            if key.lower() == pref:
                return key
    for wanted in ["zh-cn", "zh-hans", "zh", "ai-zh", "zh-hant"]:
        for key in real:
            if key.lower().startswith(wanted):
                return key
    return real[0]


def get_transcript(url: str, part: int, language: str, max_chars: int) -> dict[str, Any]:
    bvid = resolve_bvid(url)
    part_url = f"https://www.bilibili.com/video/{bvid}?p={part}"
    logger = CaptureLogger()
    try:
        with yt_dlp.YoutubeDL(ydl_options(playlist=False, logger=logger)) as ydl:
            info = ydl.extract_info(part_url, download=False)
    except Exception as exc:
        message = str(exc)
        if "cookie" in message.lower() or "decrypt" in message.lower():
            raise RuntimeError(
                f"Could not read {BROWSER} login cookies. Close the browser completely and retry, "
                f"or run the relay with -Browser edge. Original error: {message}"
            ) from exc
        raise
    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp returned no part information.")
    subtitles = info.get("subtitles") if isinstance(info.get("subtitles"), dict) else {}
    available = []
    for key, tracks in subtitles.items():
        if key.lower() in {"danmaku", "live_chat"}:
            continue
        available.append({
            "language": key,
            "language_name": key,
            "is_ai": key.lower().startswith("ai-"),
        })
    selected_lang = choose_language(list(subtitles.keys()), language)
    if not selected_lang:
        login_warning = any("subtitles are only available when logged in" in w.lower() for w in logger.warnings)
        return {
            "status": "login_required" if login_warning else "no_subtitles",
            "bvid": bvid,
            "part": part,
            "part_title": str(info.get("title") or f"P{part}"),
            "fetch_strategy": "local_yt_dlp_browser_cookies",
            "available_tracks": available,
            "error": (
                "Bilibili reports that subtitles require a logged-in browser session."
                if login_warning else "This part exposes no official/AI subtitle track."
            ),
        }
    tracks = subtitles.get(selected_lang)
    track = tracks[0] if isinstance(tracks, list) and tracks else None
    if not isinstance(track, dict):
        return {
            "status": "no_subtitles",
            "bvid": bvid,
            "part": part,
            "part_title": str(info.get("title") or f"P{part}"),
            "fetch_strategy": "local_yt_dlp_browser_cookies",
            "available_tracks": available,
            "error": "Subtitle metadata was present but no usable subtitle body was returned.",
        }
    data = track.get("data")
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    if not isinstance(data, str) or not data.strip():
        return {
            "status": "no_subtitles",
            "bvid": bvid,
            "part": part,
            "part_title": str(info.get("title") or f"P{part}"),
            "fetch_strategy": "local_yt_dlp_browser_cookies",
            "available_tracks": available,
            "error": "yt-dlp returned an empty subtitle body.",
        }
    segments, transcript = srt_segments(data, max_chars)
    return {
        "status": "ok",
        "bvid": bvid,
        "part": part,
        "part_title": str(info.get("title") or f"P{part}"),
        "language": selected_lang,
        "language_name": selected_lang,
        "source": "ai" if selected_lang.lower().startswith("ai-") else "official",
        "fetch_strategy": "local_yt_dlp_browser_cookies",
        "available_tracks": available,
        "segments": segments,
        "transcript": transcript,
    }


@app.get("/r/{token}/health")
def health(token: str) -> dict[str, Any]:
    require_token(token)
    return {"status": "ok", "runtime": "local", "browser": BROWSER}


@app.post("/r/{token}/parts")
def parts(token: str, request: VideoRequest) -> dict[str, Any]:
    require_token(token)
    try:
        return get_parts(request.url)
    except Exception as exc:
        return {"status": "error", "total_parts": 0, "parts": [], "error": str(exc)}


@app.post("/r/{token}/transcript")
def transcript(token: str, request: TranscriptRequest) -> dict[str, Any]:
    require_token(token)
    try:
        return get_transcript(request.url, request.part, request.language, request.max_chars)
    except Exception as exc:
        return {"status": "error", "part": request.part, "error": str(exc)}


def main() -> None:
    global TOKEN, BROWSER
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--browser", default="chrome", choices=["chrome", "edge", "firefox"])
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    TOKEN = args.token
    BROWSER = args.browser
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
