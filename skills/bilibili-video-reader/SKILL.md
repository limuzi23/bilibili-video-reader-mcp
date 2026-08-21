---
name: bilibili-video-reader
description: Read Bilibili videos and multi-P collections through the Bilibili Video Reader MCP tools, extract official/AI subtitles, and turn them into faithful study notes, problem/method summaries, and Python solutions. Use when the user provides a bilibili.com/B23/BV link and asks for subtitles, transcript, all parts, methods, questions, code, or a collection summary.
---

# Bilibili Video Reader v2.1

Use the bundled MCP tools for live Bilibili data. Do not run local yt-dlp scripts in ChatGPT.

## Required workflow

1. For any Bilibili/B23/BV input, call `get_bilibili_video_parts` first.
2. If the user asks for the whole collection/all P, verify `total_parts` and iterate over every requested part.
3. Call `get_bilibili_part_transcript` once per part.
4. Respect tool statuses exactly:
   - `ok`: summarize the returned transcript.
   - `login_required`: tell the user this subtitle track requires login state; never invent text.
   - `no_subtitles`: state that no official/AI subtitle is exposed; do not pretend otherwise.
   - `error`: report the error and do not fabricate missing content.
5. Keep speaker content separate from your own reconstruction.
6. If code is visible on screen but not spoken in the subtitle, label it as unavailable from subtitle-only extraction. Never claim reconstructed code is verbatim.

## Output modes

For algorithm / machine-test videos, use `references/OUTPUT_FORMAT.md` and organize each P as:

- P number and title
- Problem / task
- Method used in the video
- Key steps
- Complexity when justified
- Edge cases / pitfalls
- Python code, only when supported by the transcript or clearly labeled `根据讲解重写`

For tutorials, organize by method → purpose → steps → parameters → pitfalls.

For a transcript-only request, return cleaned timestamped transcript and do not over-summarize.

## Multi-P completeness rule

When the user asks for all P, the final answer must state how many parts were discovered, how many were successfully transcribed, and list any missing/login-required parts. Never silently omit a part.

## Security

- Never ask the user to paste passwords, `SESSDATA`, access tokens, or raw cookie text into chat.
- Public subtitle access requires no secret.
- If login-only subtitle support is needed, it may be configured privately as an encrypted Cloudflare Worker secret named `BILI_COOKIE`; the user should set it directly in Cloudflare, never in chat or GitHub.
- Do not bypass paywalls, VIP restrictions, DRM, geographic restrictions, or account permissions.
