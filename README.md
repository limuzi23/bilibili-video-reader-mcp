# Bilibili Video Reader v2.1

A read-only ChatGPT/Codex plugin built as **Skill + stateless MCP server**, now targeting **Cloudflare Workers** so it can run without Render or a credit card.

## MCP tools

- `get_bilibili_video_parts(url)` — title, author, description, all P numbers and CIDs.
- `get_bilibili_part_transcript(url, part, language, max_chars)` — official/AI subtitle tracks and timestamped transcript for one P.

The Worker calls Bilibili's metadata/player/subtitle endpoints directly. No video download is needed for subtitle mode.

## Deploy to Cloudflare Workers

### Dashboard path

1. Create/sign in to a Cloudflare account.
2. Open **Workers & Pages** → **Create** → **Import a repository** (wording may vary slightly).
3. Connect GitHub and select `limuzi23/bilibili-video-reader-mcp`.
4. Keep the repository root as the root directory.
5. Cloudflare should detect `wrangler.jsonc` automatically.
6. Use the default deploy command: `npx wrangler deploy`.
7. Deploy.

The Worker name must remain `bilibili-video-reader-mcp` because it matches `wrangler.jsonc`.

After deployment, Cloudflare will give you a URL similar to:

```text
https://bilibili-video-reader-mcp.<your-subdomain>.workers.dev
```

Health check:

```text
https://bilibili-video-reader-mcp.<your-subdomain>.workers.dev/health
```

MCP endpoint:

```text
https://bilibili-video-reader-mcp.<your-subdomain>.workers.dev/mcp
```

For public subtitles, no runtime secret is required.

### Optional private login state

If a subtitle is only visible while logged in, the Worker can read an optional Cloudflare secret named `BILI_COOKIE`. Configure it only inside Cloudflare's encrypted **Variables and Secrets** UI. Never paste raw cookies into ChatGPT and never commit them to GitHub.

## Connect to ChatGPT

1. ChatGPT → Settings → Security and login → enable **Developer mode**.
2. Open Plugins, press `+`, and register the deployed URL ending in `/mcp`.
3. Copy the technical ID from the created connection. It begins with `plugin_asdk_app_`.
4. Run `python scripts/configure_plugin.py plugin_asdk_app_YOUR_ID` if the plugin packaging flow requires an app reference.

The OpenAI plugin manifest lives at `.codex-plugin/plugin.json` and the workflow Skill is in `skills/bilibili-video-reader/`.

## Local development

```bash
npm install
npm run dev
```

Deploy from a local terminal if desired:

```bash
npm run deploy
```

Endpoints:

```text
GET  /health
MCP  /mcp
```

## Architecture

The current production path is:

```text
ChatGPT Skill
    ↓
Cloudflare Workers /mcp
    ↓
Bilibili metadata/player/subtitle APIs
    ↓
structured multi-P metadata + timestamped subtitles
```

The old `server/` Python implementation remains in the repository only as a reference/legacy implementation; Cloudflare does not use it.

## Current scope

v2.1 focuses on **multi-P metadata + official/AI subtitles**. It does not yet download audio/video, run Whisper ASR, or OCR source code from video frames. Those are planned only after this subtitle path is verified end-to-end.
