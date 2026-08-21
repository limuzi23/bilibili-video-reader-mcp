from __future__ import annotations

import http.cookiejar
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

BVID_RE = re.compile(r"BV[0-9A-Za-z]{10,}")
ALLOWED_HOSTS = {
    "bilibili.com",
    "www.bilibili.com",
    "m.bilibili.com",
    "api.bilibili.com",
    "b23.tv",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


class BiliError(RuntimeError):
    pass


@dataclass
class SubtitleSegment:
    start: float
    end: float
    text: str


def _host_allowed(host: str) -> bool:
    host = host.lower().split(":")[0]
    return host in ALLOWED_HOSTS or host.endswith(".bilibili.com") or host.endswith(".hdslb.com")


def _load_cookie_dict() -> dict[str, str]:
    """Load a Netscape/Mozilla cookie jar from BILI_COOKIES_FILE, if configured.

    The file should be mounted as a deployment secret. Raw cookie text is never
    accepted as a tool argument.
    """
    cookie_path = os.getenv("BILI_COOKIES_FILE", "").strip()
    if not cookie_path:
        return {}

    path = Path(cookie_path).expanduser()
    if not path.is_file():
        return {}

    jar = http.cookiejar.MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return {}

    out: dict[str, str] = {}
    for cookie in jar:
        if "bilibili.com" in cookie.domain or "b23.tv" in cookie.domain:
            out[cookie.name] = cookie.value
    return out


class BiliClient:
    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self.cookies = _load_cookie_dict()

    def _client(self) -> httpx.Client:
        return httpx.Client(
            headers=DEFAULT_HEADERS,
            cookies=self.cookies,
            timeout=self.timeout,
            follow_redirects=True,
        )

    def resolve_bvid(self, url_or_bvid: str) -> str:
        raw = url_or_bvid.strip()
        direct = BVID_RE.search(raw)
        if direct:
            return direct.group(0)

        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not _host_allowed(parsed.netloc):
            raise BiliError("Only Bilibili/B23 video links or BV IDs are supported.")

        with self._client() as client:
            response = client.get(raw)
            response.raise_for_status()
            match = BVID_RE.search(str(response.url)) or BVID_RE.search(response.text[:200_000])
            if not match:
                raise BiliError("Could not resolve a BV ID from this Bilibili link.")
            return match.group(0)

    def _get_json(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not _host_allowed(parsed.netloc):
            raise BiliError("Refusing to fetch a non-Bilibili HTTPS endpoint.")

        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                with self._client() as client:
                    response = client.get(url, params=params)
                    if response.status_code in {412, 429}:
                        raise BiliError(
                            f"Bilibili rate-limited the request (HTTP {response.status_code}). Retry later."
                        )
                    response.raise_for_status()
                    data = response.json()
                if not isinstance(data, dict):
                    raise BiliError("Bilibili returned an unexpected non-object JSON response.")
                return data
            except (httpx.HTTPError, json.JSONDecodeError, BiliError) as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(0.6)
                    continue
                break
        raise BiliError(str(last_exc) if last_exc else "Bilibili request failed.")

    def get_video_info(self, url_or_bvid: str) -> dict[str, Any]:
        bvid = self.resolve_bvid(url_or_bvid)
        payload = self._get_json(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
        )
        code = payload.get("code")
        if code != 0:
            message = payload.get("message") or "unknown Bilibili API error"
            if code in {-352, -412}:
                raise BiliError(f"Bilibili anti-abuse/rate-limit response: {message} (code {code}).")
            raise BiliError(f"Bilibili metadata API error: {message} (code {code}).")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise BiliError("Bilibili metadata response has no data object.")
        return data

    def get_player_info(self, bvid: str, cid: int) -> dict[str, Any]:
        payload = self._get_json(
            "https://api.bilibili.com/x/player/v2",
            params={"bvid": bvid, "cid": cid},
        )
        code = payload.get("code")
        if code != 0:
            message = payload.get("message") or "unknown Bilibili API error"
            raise BiliError(f"Bilibili player API error: {message} (code {code}).")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise BiliError("Bilibili player response has no data object.")
        return data

    @staticmethod
    def _normalize_subtitle_url(url: str) -> str:
        if url.startswith("//"):
            return "https:" + url
        return url

    def get_subtitle_body(self, subtitle_url: str) -> list[SubtitleSegment]:
        url = self._normalize_subtitle_url(subtitle_url)
        parsed = urlparse(url)
        if parsed.scheme != "https" or not _host_allowed(parsed.netloc):
            raise BiliError("Subtitle URL is outside Bilibili's allowed domains.")

        payload = self._get_json(url)
        body = payload.get("body", [])
        if not isinstance(body, list):
            raise BiliError("Subtitle JSON has an unexpected body format.")

        out: list[SubtitleSegment] = []
        for item in body:
            if not isinstance(item, dict):
                continue
            text = str(item.get("content", "")).strip()
            if not text:
                continue
            try:
                start = float(item.get("from", 0.0))
                end = float(item.get("to", start))
            except (TypeError, ValueError):
                continue
            out.append(SubtitleSegment(start=start, end=end, text=text))
        return out
