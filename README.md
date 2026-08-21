# Bilibili Video Reader v2

A read-only ChatGPT/Codex plugin built as **Skill + MCP server**.

## What v2 fixes

The v1 Skill tried to run `yt-dlp` inside ChatGPT's sandbox. v2 moves live Bilibili access into a deployable MCP backend. The Skill only controls the workflow and formatting.

## MCP tools

- `get_bilibili_video_parts(url)` — title, author, description, all P numbers and CIDs.
- `get_bilibili_part_transcript(url, part, language, max_chars)` — official/AI subtitle tracks and timestamped transcript for one P.

The backend calls:

- `https://api.bilibili.com/x/web-interface/view`
- `https://api.bilibili.com/x/player/v2`

No video download is needed for subtitle mode.

## Deploy

### Render (simple path)

1. Put this folder in a GitHub repository.
2. In Render, create a Blueprint from the repo. `render.yaml` builds `server/Dockerfile`.
3. Wait until `https://<your-service>/health` returns JSON with `status: ok`.
4. Your MCP URL is `https://<your-service>/mcp`.

For public subtitles, no secret is required.

### Optional login-state subtitles

On a private deployment only, mount a Netscape-format Bilibili cookie file and set:

```text
BILI_COOKIES_FILE=/run/secrets/bilibili-cookies.txt
```

Do **not** paste raw cookies into ChatGPT or commit cookie files to Git.

## Connect to ChatGPT

1. ChatGPT → Settings → Security and login → enable **Developer mode**.
2. Open Plugins, press `+`, and register the deployed MCP URL ending in `/mcp`.
3. Copy the technical ID from the created connection URL. It begins with `plugin_asdk_app_`.
4. In this project run:

```bash
python scripts/configure_plugin.py plugin_asdk_app_YOUR_ID
```

5. Package/install the plugin from this folder (or use `@plugin-creator`).

The OpenAI plugin manifest lives at `.codex-plugin/plugin.json`; after step 4 it references `.app.json`.

## Local checks

```bash
python -m py_compile server/bili_client.py server/server.py scripts/configure_plugin.py
python -m pytest server/tests
```

For a full MCP test after installing dependencies:

```bash
cd server
python server.py
# MCP endpoint: http://localhost:8000/mcp
# health:       http://localhost:8000/health
```

## Current scope

v2.0 intentionally focuses on **metadata + official/AI subtitles**. It does not yet download audio/video, run Whisper ASR, or OCR code from frames. Those can be added after the public-subtitle path is connected and verified end-to-end.
