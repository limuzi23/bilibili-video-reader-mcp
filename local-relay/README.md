# Bilibili Video Reader v3 — Windows Local Relay

This relay is used when Bilibili returns HTTP 412 to cloud/datacenter IPs.

It runs extraction on your own Windows computer and uses your normal residential/campus network. For subtitles it asks yt-dlp to read the existing login cookies from Chrome (or Edge/Firefox). A temporary Cloudflare Quick Tunnel exposes only the relay endpoints behind a random secret path.

## Start

1. Make sure Python 3 is installed.
2. Keep your normal Bilibili account logged in in Chrome.
3. Double-click `START_WINDOWS.bat`.
4. On first run it creates a venv, installs dependencies, and downloads `cloudflared.exe`.
5. Wait until the window prints a value beginning with `https://...trycloudflare.com/r/...`.
6. Keep the window open.
7. In Cloudflare Workers → `bilibili-video-reader-mcp` → Settings → Variables and Secrets, add/update `LOCAL_RELAY_URL` with that complete value, then deploy/save.
8. Open `/health` on the Worker. It should report `version: 3.0.0` and `local_relay_configured: true`.
9. In ChatGPT refresh the Bilibili Video Reader plugin and test P1.

## If Chrome cookies fail

Close every Chrome window and retry. Or run in PowerShell:

```powershell
.\start-local-relay.ps1 -Browser edge
```

Do not paste your Bilibili password or raw cookies into ChatGPT or commit them to Git.

## Important

The Quick Tunnel URL changes every time the relay is restarted. For this first end-to-end test, update `LOCAL_RELAY_URL` each time. A later version can automate relay registration.
