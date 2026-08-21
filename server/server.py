from __future__ import annotations

import os
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from bili_client import BiliClient, BiliError


class PartInfo(BaseModel):
    part: int
    cid: int
    title: str
    duration_seconds: int | None = None
    url: str


class VideoPartsResult(BaseModel):
    status: Literal["ok", "error"]
    bvid: str | None = None
    title: str | None = None
    author: str | None = None
    description: str | None = None
    total_parts: int = 0
    parts: list[PartInfo] = []
    error: str | None = None


class SubtitleTrack(BaseModel):
    language: str
    language_name: str | None = None
    is_ai: bool = False


class TranscriptSegment(BaseModel):
    start: float
    end: float
    timestamp: str
    text: str


class TranscriptResult(BaseModel):
    status: Literal["ok", "login_required", "no_subtitles", "error"]
    bvid: str | None = None
    part: int | None = None
    part_title: str | None = None
    language: str | None = None
    language_name: str | None = None
    source: Literal["official", "ai", "unknown"] | None = None
    available_tracks: list[SubtitleTrack] = []
    segments: list[TranscriptSegment] = []
    transcript: str | None = None
    error: str | None = None


def _ts(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _pick_track(tracks: list[dict], language: str) -> dict | None:
    if not tracks:
        return None

    lang = language.strip().lower()
    if lang and lang != "auto":
        exact = [t for t in tracks if str(t.get("lan", "")).lower() == lang]
        if exact:
            return exact[0]

    preferred = ("zh-cn", "zh-hans", "zh", "ai-zh", "zh-hant")
    for pref in preferred:
        for track in tracks:
            lan = str(track.get("lan", "")).lower()
            if lan == pref or lan.startswith(pref):
                return track
    return tracks[0]


def _track_is_ai(track: dict) -> bool:
    ai_type = track.get("ai_type")
    if ai_type not in (None, 0, "0", ""):
        return True
    lan = str(track.get("lan", "")).lower()
    return lan.startswith("ai-")


mcp = MCPServer(
    "bilibili-video-reader",
    instructions=(
        "Use get_bilibili_video_parts first for multi-part videos. Then call "
        "get_bilibili_part_transcript once per requested part. Never invent missing subtitles, "
        "on-screen code, or inaccessible content; report login_required/no_subtitles exactly."
    ),
)


@mcp.tool(
    title="Get Bilibili video parts",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
def get_bilibili_video_parts(
    url: Annotated[str, Field(description="A bilibili.com/b23.tv video URL or a BV ID.")],
) -> VideoPartsResult:
    """Get title, author, description, and every P/cid in a Bilibili multi-part video."""
    try:
        client = BiliClient()
        data = client.get_video_info(url)
        bvid = str(data.get("bvid") or "")
        pages = data.get("pages") if isinstance(data.get("pages"), list) else []
        if not pages and data.get("cid"):
            pages = [{
                "page": 1,
                "cid": data.get("cid"),
                "part": data.get("title") or "P1",
                "duration": data.get("duration"),
            }]

        parts: list[PartInfo] = []
        for idx, page in enumerate(pages, start=1):
            if not isinstance(page, dict) or not page.get("cid"):
                continue
            part_no = int(page.get("page") or idx)
            parts.append(
                PartInfo(
                    part=part_no,
                    cid=int(page["cid"]),
                    title=str(page.get("part") or f"P{part_no}"),
                    duration_seconds=(int(page["duration"]) if page.get("duration") is not None else None),
                    url=f"https://www.bilibili.com/video/{bvid}?p={part_no}",
                )
            )

        owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
        return VideoPartsResult(
            status="ok",
            bvid=bvid or None,
            title=str(data.get("title") or "") or None,
            author=str(owner.get("name") or "") or None,
            description=str(data.get("desc") or "") or None,
            total_parts=len(parts),
            parts=parts,
        )
    except Exception as exc:
        return VideoPartsResult(status="error", error=str(exc))


@mcp.tool(
    title="Get Bilibili part transcript",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
def get_bilibili_part_transcript(
    url: Annotated[str, Field(description="A bilibili.com/b23.tv video URL or a BV ID.")],
    part: Annotated[int, Field(ge=1, description="1-based P number to transcribe.")] = 1,
    language: Annotated[str, Field(description="Preferred subtitle language, e.g. zh-CN; auto prefers Chinese.")] = "auto",
    max_chars: Annotated[int, Field(ge=2000, le=250000, description="Maximum transcript characters returned.")] = 120000,
) -> TranscriptResult:
    """Fetch official/AI Bilibili subtitles for one P and return timestamped transcript text."""
    try:
        client = BiliClient()
        data = client.get_video_info(url)
        bvid = str(data.get("bvid") or "")
        pages = data.get("pages") if isinstance(data.get("pages"), list) else []
        if not pages and data.get("cid"):
            pages = [{"page": 1, "cid": data.get("cid"), "part": data.get("title") or "P1"}]

        selected: dict | None = None
        for idx, page_data in enumerate(pages, start=1):
            if not isinstance(page_data, dict):
                continue
            pno = int(page_data.get("page") or idx)
            if pno == part:
                selected = page_data
                break
        if selected is None:
            return TranscriptResult(status="error", bvid=bvid or None, part=part, error=f"Part P{part} does not exist.")

        cid = int(selected["cid"])
        player = client.get_player_info(bvid, cid)
        subtitle_obj = player.get("subtitle") if isinstance(player.get("subtitle"), dict) else {}
        tracks = subtitle_obj.get("subtitles") if isinstance(subtitle_obj.get("subtitles"), list) else []

        available = [
            SubtitleTrack(
                language=str(t.get("lan") or "unknown"),
                language_name=str(t.get("lan_doc") or "") or None,
                is_ai=_track_is_ai(t),
            )
            for t in tracks
            if isinstance(t, dict)
        ]

        if not tracks:
            need_login = bool(player.get("need_login_subtitle") or subtitle_obj.get("need_login_subtitle"))
            return TranscriptResult(
                status="login_required" if need_login else "no_subtitles",
                bvid=bvid or None,
                part=part,
                part_title=str(selected.get("part") or f"P{part}"),
                available_tracks=available,
                error=(
                    "Bilibili reports that subtitle access requires a logged-in session. "
                    "Configure BILI_COOKIES_FILE on your private deployment; do not paste raw cookies into chat."
                    if need_login
                    else "This part currently exposes no official/AI subtitle track."
                ),
            )

        track = _pick_track([t for t in tracks if isinstance(t, dict)], language)
        if not track or not track.get("subtitle_url"):
            return TranscriptResult(
                status="no_subtitles",
                bvid=bvid or None,
                part=part,
                part_title=str(selected.get("part") or f"P{part}"),
                available_tracks=available,
                error="Subtitle metadata exists but no usable subtitle URL was returned.",
            )

        body = client.get_subtitle_body(str(track["subtitle_url"]))
        segments: list[TranscriptSegment] = []
        lines: list[str] = []
        current_chars = 0
        for seg in body:
            line = f"[{_ts(seg.start)}] {seg.text}"
            if current_chars + len(line) + 1 > max_chars:
                break
            current_chars += len(line) + 1
            lines.append(line)
            segments.append(
                TranscriptSegment(
                    start=seg.start,
                    end=seg.end,
                    timestamp=_ts(seg.start),
                    text=seg.text,
                )
            )

        is_ai = _track_is_ai(track)
        return TranscriptResult(
            status="ok",
            bvid=bvid or None,
            part=part,
            part_title=str(selected.get("part") or f"P{part}"),
            language=str(track.get("lan") or "unknown"),
            language_name=str(track.get("lan_doc") or "") or None,
            source="ai" if is_ai else "official",
            available_tracks=available,
            segments=segments,
            transcript="\n".join(lines),
        )
    except BiliError as exc:
        return TranscriptResult(status="error", part=part, error=str(exc))
    except Exception as exc:
        return TranscriptResult(status="error", part=part, error=f"Unexpected error: {exc}")


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "bilibili-video-reader"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    try:
        from mcp.server.transport_security import TransportSecuritySettings

        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=port,
            stateless_http=True,
            json_response=True,
            transport_security=security,
        )
    except ImportError:
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=port,
            stateless_http=True,
            json_response=True,
        )
