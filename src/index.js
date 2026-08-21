import { createMcpHandler } from "agents/mcp/server";
import { McpServer } from "@modelcontextprotocol/server";
import puppeteer from "@cloudflare/puppeteer";
import { z } from "zod";

const BVID_RE = /BV[0-9A-Za-z]{10,}/;
const BASE_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
  "Referer": "https://www.bilibili.com/",
  "Accept": "application/json,text/plain,*/*",
  "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"
};

const memoryCache = new Map();

class AntiAbuseError extends Error {}

function cacheGet(key) {
  const item = memoryCache.get(key);
  if (!item) return null;
  if (Date.now() > item.expiresAt) {
    memoryCache.delete(key);
    return null;
  }
  return item.value;
}

function cacheSet(key, value, ttlMs) {
  memoryCache.set(key, { value, expiresAt: Date.now() + ttlMs });
}

function allowedHost(hostname) {
  const host = hostname.toLowerCase();
  return host === "bilibili.com" || host === "www.bilibili.com" || host === "m.bilibili.com" || host === "api.bilibili.com" || host === "b23.tv" || host.endsWith(".bilibili.com") || host.endsWith(".hdslb.com");
}

function headers(env) {
  const out = new Headers(BASE_HEADERS);
  if (env?.BILI_COOKIE) out.set("Cookie", env.BILI_COOKIE);
  return out;
}

function isAntiAbuseCode(code) {
  return [-352, -412].includes(Number(code));
}

function cookieObjects(cookieHeader) {
  if (!cookieHeader) return [];
  return String(cookieHeader)
    .split(";")
    .map((piece) => piece.trim())
    .filter(Boolean)
    .map((piece) => {
      const index = piece.indexOf("=");
      if (index <= 0) return null;
      return {
        name: piece.slice(0, index).trim(),
        value: piece.slice(index + 1).trim(),
        domain: ".bilibili.com",
        path: "/",
        secure: true
      };
    })
    .filter(Boolean);
}

async function resolveBvid(input, env) {
  const raw = String(input || "").trim();
  const direct = raw.match(BVID_RE);
  if (direct) return direct[0];

  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("Only Bilibili/B23 video links or BV IDs are supported.");
  }
  if (!["http:", "https:"].includes(url.protocol) || !allowedHost(url.hostname)) {
    throw new Error("Only Bilibili/B23 video links or BV IDs are supported.");
  }

  const response = await fetch(url.toString(), {
    headers: headers(env),
    redirect: "follow"
  });
  if (!response.ok) throw new Error(`Could not resolve Bilibili link (HTTP ${response.status}).`);

  const fromUrl = response.url.match(BVID_RE);
  if (fromUrl) return fromUrl[0];
  const text = (await response.text()).slice(0, 200000);
  const fromBody = text.match(BVID_RE);
  if (fromBody) return fromBody[0];
  throw new Error("Could not resolve a BV ID from this Bilibili link.");
}

function buildUrl(urlString, params) {
  const url = new URL(urlString);
  if (url.protocol !== "https:" || !allowedHost(url.hostname)) {
    throw new Error("Refusing to fetch a non-Bilibili HTTPS endpoint.");
  }
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }
  }
  return url;
}

async function fetchJsonDirect(urlString, params, env) {
  const url = buildUrl(urlString, params);
  let lastError;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await fetch(url.toString(), { headers: headers(env) });
      if (response.status === 412 || response.status === 429) {
        throw new AntiAbuseError(`Bilibili blocked the direct request (HTTP ${response.status}).`);
      }
      if (!response.ok) throw new Error(`Bilibili request failed (HTTP ${response.status}).`);
      const data = await response.json();
      if (!data || typeof data !== "object" || Array.isArray(data)) {
        throw new Error("Bilibili returned an unexpected JSON response.");
      }
      return data;
    } catch (error) {
      lastError = error;
      if (error instanceof AntiAbuseError) break;
      if (attempt === 0) await new Promise((resolve) => setTimeout(resolve, 350));
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Bilibili request failed.");
}

async function browserFetchJson(urlString, params, env, bootstrapBvid = null) {
  if (!env?.BROWSER) throw new Error("Browser Run binding is unavailable.");
  const target = buildUrl(urlString, params);
  const browser = await puppeteer.launch(env.BROWSER);
  try {
    const page = await browser.newPage();
    await page.setUserAgent(BASE_HEADERS["User-Agent"]);
    await page.setExtraHTTPHeaders({
      "Accept-Language": BASE_HEADERS["Accept-Language"],
      "Referer": BASE_HEADERS.Referer
    });

    const cookies = cookieObjects(env?.BILI_COOKIE);
    if (cookies.length) await page.setCookie(...cookies);

    if (bootstrapBvid) {
      try {
        await page.goto(`https://www.bilibili.com/video/${bootstrapBvid}`, {
          waitUntil: "domcontentloaded",
          timeout: 25000
        });
      } catch {
        // The API navigation below may still work even if the video page times out.
      }
    } else {
      try {
        await page.goto("https://www.bilibili.com/", {
          waitUntil: "domcontentloaded",
          timeout: 15000
        });
      } catch {
        // Continue to the target API/CDN URL.
      }
    }

    const response = await page.goto(target.toString(), {
      waitUntil: "domcontentloaded",
      timeout: 30000
    });
    if (!response) throw new Error("Browser Run received no response from Bilibili.");
    const status = response.status();
    if (status === 412 || status === 429) {
      throw new AntiAbuseError(`Bilibili also blocked the browser fallback (HTTP ${status}).`);
    }
    if (status < 200 || status >= 300) {
      throw new Error(`Bilibili browser fallback failed (HTTP ${status}).`);
    }
    const text = await response.text();
    const data = JSON.parse(text);
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw new Error("Bilibili browser fallback returned an unexpected JSON response.");
    }
    return data;
  } finally {
    await browser.close();
  }
}

async function fetchWithBrowserFallback(urlString, params, env, bootstrapBvid = null) {
  try {
    return { payload: await fetchJsonDirect(urlString, params, env), strategy: "direct" };
  } catch (error) {
    if (!(error instanceof AntiAbuseError) || !env?.BROWSER) throw error;
    return {
      payload: await browserFetchJson(urlString, params, env, bootstrapBvid),
      strategy: "browser_run"
    };
  }
}

async function getVideoInfo(input, env) {
  const bvid = await resolveBvid(input, env);
  const cached = cacheGet(`meta:${bvid}`);
  if (cached) return cached;

  let result = await fetchWithBrowserFallback(
    "https://api.bilibili.com/x/web-interface/view",
    { bvid },
    env,
    bvid
  );

  if (isAntiAbuseCode(result.payload?.code) && result.strategy === "direct" && env?.BROWSER) {
    result = {
      payload: await browserFetchJson("https://api.bilibili.com/x/web-interface/view", { bvid }, env, bvid),
      strategy: "browser_run"
    };
  }

  const payload = result.payload;
  if (payload.code !== 0) {
    const message = payload.message || "unknown error";
    if (isAntiAbuseCode(payload.code)) throw new AntiAbuseError(`Bilibili anti-abuse response: ${message} (code ${payload.code}).`);
    throw new Error(`Bilibili metadata API error: ${message} (code ${payload.code}).`);
  }
  if (!payload.data || typeof payload.data !== "object") throw new Error("Bilibili metadata response has no data object.");

  const value = { data: payload.data, strategy: result.strategy };
  cacheSet(`meta:${bvid}`, value, 30 * 60 * 1000);
  return value;
}

async function getPlayerInfo(bvid, cid, env) {
  const cacheKey = `player:${bvid}:${cid}`;
  const cached = cacheGet(cacheKey);
  if (cached) return cached;

  let result = await fetchWithBrowserFallback(
    "https://api.bilibili.com/x/player/wbi/v2",
    { bvid, cid },
    env,
    bvid
  );

  if (isAntiAbuseCode(result.payload?.code) && result.strategy === "direct" && env?.BROWSER) {
    result = {
      payload: await browserFetchJson("https://api.bilibili.com/x/player/wbi/v2", { bvid, cid }, env, bvid),
      strategy: "browser_run"
    };
  }

  const payload = result.payload;
  if (payload.code !== 0) {
    const message = payload.message || "unknown error";
    if (isAntiAbuseCode(payload.code)) throw new AntiAbuseError(`Bilibili player anti-abuse response: ${message} (code ${payload.code}).`);
    throw new Error(`Bilibili player API error: ${message} (code ${payload.code}).`);
  }
  if (!payload.data || typeof payload.data !== "object") throw new Error("Bilibili player response has no data object.");

  const value = { data: payload.data, strategy: result.strategy };
  cacheSet(cacheKey, value, 10 * 60 * 1000);
  return value;
}

function pagesFromVideo(data) {
  const pages = Array.isArray(data.pages) ? data.pages : [];
  if (pages.length) return pages;
  if (data.cid) return [{ page: 1, cid: data.cid, part: data.title || "P1", duration: data.duration }];
  return [];
}

function isAiTrack(track) {
  const ai = track?.ai_type;
  return ![undefined, null, 0, "0", ""].includes(ai) || String(track?.lan || "").toLowerCase().startsWith("ai-");
}

function pickTrack(tracks, language) {
  if (!tracks.length) return null;
  const lang = String(language || "auto").trim().toLowerCase();
  if (lang && lang !== "auto") {
    const exact = tracks.find((t) => String(t.lan || "").toLowerCase() === lang);
    if (exact) return exact;
  }
  const preferred = ["zh-cn", "zh-hans", "zh", "ai-zh", "zh-hant"];
  for (const pref of preferred) {
    const found = tracks.find((t) => {
      const lan = String(t.lan || "").toLowerCase();
      return lan === pref || lan.startsWith(pref);
    });
    if (found) return found;
  }
  return tracks[0];
}

function ts(seconds) {
  let value = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(value / 3600);
  value %= 3600;
  const m = Math.floor(value / 60);
  const s = value % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

async function subtitleBody(subtitleUrl, env, bvid) {
  const normalized = subtitleUrl.startsWith("//") ? `https:${subtitleUrl}` : subtitleUrl;
  const cacheKey = `subtitle:${normalized}`;
  const cached = cacheGet(cacheKey);
  if (cached) return cached;

  const result = await fetchWithBrowserFallback(normalized, null, env, bvid);
  const payload = result.payload;
  if (!Array.isArray(payload.body)) throw new Error("Subtitle JSON has an unexpected body format.");
  const body = payload.body
    .filter((item) => item && typeof item === "object" && String(item.content || "").trim())
    .map((item) => ({
      start: Number(item.from || 0),
      end: Number(item.to ?? item.from ?? 0),
      text: String(item.content || "").trim()
    }));
  const value = { body, strategy: result.strategy };
  cacheSet(cacheKey, value, 30 * 60 * 1000);
  return value;
}

function asToolText(value) {
  return { content: [{ type: "text", text: JSON.stringify(value, null, 2) }] };
}

function createServer(env) {
  const server = new McpServer({ name: "bilibili-video-reader", version: "2.2.0" });

  server.registerTool(
    "get_bilibili_video_parts",
    {
      description: "Get title, author, description, and every P/cid in a Bilibili multi-part video. Automatically falls back to a real browser session if Bilibili blocks direct cloud requests.",
      inputSchema: {
        url: z.string().min(1).describe("A bilibili.com/b23.tv video URL or a BV ID.")
      }
    },
    async ({ url }) => {
      try {
        const info = await getVideoInfo(url, env);
        const data = info.data;
        const bvid = String(data.bvid || "");
        const owner = data.owner && typeof data.owner === "object" ? data.owner : {};
        const parts = pagesFromVideo(data)
          .filter((page) => page && page.cid)
          .map((page, index) => {
            const part = Number(page.page || index + 1);
            return {
              part,
              cid: Number(page.cid),
              title: String(page.part || `P${part}`),
              duration_seconds: page.duration == null ? null : Number(page.duration),
              url: `https://www.bilibili.com/video/${bvid}?p=${part}`
            };
          });
        return asToolText({
          status: "ok",
          bvid: bvid || null,
          title: String(data.title || "") || null,
          author: String(owner.name || "") || null,
          description: String(data.desc || "") || null,
          total_parts: parts.length,
          fetch_strategy: info.strategy,
          parts
        });
      } catch (error) {
        return asToolText({
          status: "error",
          total_parts: 0,
          parts: [],
          error: error instanceof Error ? error.message : String(error)
        });
      }
    }
  );

  server.registerTool(
    "get_bilibili_part_transcript",
    {
      description: "Fetch official/AI Bilibili subtitles for one P and return a cleaned timestamped transcript. Automatically falls back to Browser Run on HTTP 412/429. Never invent missing content.",
      inputSchema: {
        url: z.string().min(1).describe("A bilibili.com/b23.tv video URL or a BV ID."),
        part: z.number().int().min(1).optional().describe("1-based P number. Defaults to 1."),
        language: z.string().optional().describe("Preferred subtitle language, e.g. zh-CN. auto prefers Chinese."),
        max_chars: z.number().int().min(2000).max(250000).optional().describe("Maximum transcript characters. Defaults to 120000.")
      }
    },
    async ({ url, part = 1, language = "auto", max_chars = 120000 }) => {
      try {
        const info = await getVideoInfo(url, env);
        const data = info.data;
        const bvid = String(data.bvid || "");
        const pages = pagesFromVideo(data);
        const selected = pages.find((page, index) => Number(page.page || index + 1) === part);
        if (!selected) return asToolText({ status: "error", bvid: bvid || null, part, error: `Part P${part} does not exist.` });

        const playerResult = await getPlayerInfo(bvid, Number(selected.cid), env);
        const player = playerResult.data;
        const subtitle = player.subtitle && typeof player.subtitle === "object" ? player.subtitle : {};
        const tracks = Array.isArray(subtitle.subtitles) ? subtitle.subtitles.filter((t) => t && typeof t === "object") : [];
        const available_tracks = tracks.map((track) => ({
          language: String(track.lan || "unknown"),
          language_name: String(track.lan_doc || "") || null,
          is_ai: isAiTrack(track)
        }));

        if (!tracks.length) {
          const needLogin = Boolean(player.need_login_subtitle || subtitle.need_login_subtitle);
          return asToolText({
            status: needLogin ? "login_required" : "no_subtitles",
            bvid: bvid || null,
            part,
            part_title: String(selected.part || `P${part}`),
            fetch_strategy: {
              metadata: info.strategy,
              player: playerResult.strategy
            },
            available_tracks,
            error: needLogin
              ? "Bilibili reports that subtitle access requires a logged-in session. You can add BILI_COOKIE as a private Cloudflare Worker secret; never paste raw cookies into chat or commit them to Git."
              : "This part currently exposes no official/AI subtitle track."
          });
        }

        const track = pickTrack(tracks, language);
        if (!track?.subtitle_url) {
          return asToolText({ status: "no_subtitles", bvid: bvid || null, part, part_title: String(selected.part || `P${part}`), available_tracks, error: "Subtitle metadata exists but no usable subtitle URL was returned." });
        }

        const subtitleResult = await subtitleBody(String(track.subtitle_url), env, bvid);
        const segments = [];
        const lines = [];
        let chars = 0;
        for (const seg of subtitleResult.body) {
          const timestamp = ts(seg.start);
          const line = `[${timestamp}] ${seg.text}`;
          if (chars + line.length + 1 > max_chars) break;
          chars += line.length + 1;
          lines.push(line);
          segments.push({ start: seg.start, end: seg.end, timestamp, text: seg.text });
        }

        return asToolText({
          status: "ok",
          bvid: bvid || null,
          part,
          part_title: String(selected.part || `P${part}`),
          language: String(track.lan || "unknown"),
          language_name: String(track.lan_doc || "") || null,
          source: isAiTrack(track) ? "ai" : "official",
          fetch_strategy: {
            metadata: info.strategy,
            player: playerResult.strategy,
            subtitle_json: subtitleResult.strategy
          },
          available_tracks,
          segments,
          transcript: lines.join("\n")
        });
      } catch (error) {
        return asToolText({ status: "error", part, error: error instanceof Error ? error.message : String(error) });
      }
    }
  );

  return server;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({
        status: "ok",
        service: "bilibili-video-reader",
        runtime: "cloudflare-workers",
        version: "2.2.0",
        browser_fallback: Boolean(env?.BROWSER),
        login_cookie_configured: Boolean(env?.BILI_COOKIE)
      });
    }
    if (url.pathname !== "/mcp") {
      return new Response("Bilibili Video Reader MCP. Use /mcp or /health.", { status: 200 });
    }
    return createMcpHandler(() => createServer(env))(request, env, ctx);
  }
};
