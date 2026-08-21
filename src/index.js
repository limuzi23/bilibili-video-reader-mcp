import { createMcpHandler } from "agents/mcp/server";
import { McpServer } from "@modelcontextprotocol/server";
import { z } from "zod";

const BVID_RE = /BV[0-9A-Za-z]{10,}/;
const BASE_HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
  "Referer": "https://www.bilibili.com/",
  "Accept": "application/json,text/plain,*/*",
  "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"
};

function asToolText(value) {
  return { content: [{ type: "text", text: JSON.stringify(value, null, 2) }] };
}

function ts(seconds) {
  let value = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(value / 3600);
  value %= 3600;
  const m = Math.floor(value / 60);
  const s = value % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

async function resolveBvid(input) {
  const raw = String(input || "").trim();
  const direct = raw.match(BVID_RE);
  if (direct) return direct[0];
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("Only Bilibili/B23 video links or BV IDs are supported.");
  }
  if (!parsed.hostname.endsWith("b23.tv") && !parsed.hostname.endsWith("bilibili.com")) {
    throw new Error("Only Bilibili/B23 video links or BV IDs are supported.");
  }
  const response = await fetch(raw, { headers: BASE_HEADERS, redirect: "follow" });
  if (!response.ok) throw new Error(`Could not resolve Bilibili link (HTTP ${response.status}).`);
  const match = response.url.match(BVID_RE) || (await response.text()).slice(0, 200000).match(BVID_RE);
  if (!match) throw new Error("Could not resolve a BV ID from this Bilibili link.");
  return match[0];
}

async function callRelay(env, route, payload) {
  const base = String(env?.LOCAL_RELAY_URL || "").trim().replace(/\/+$/, "");
  if (!base) throw new Error("Local relay is not configured.");
  const response = await fetch(`${base}/${route}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Local relay failed (HTTP ${response.status})${body ? `: ${body.slice(0, 500)}` : ""}`);
  }
  const data = await response.json();
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Local relay returned invalid JSON.");
  return data;
}

async function biliJson(url, params = {}) {
  const u = new URL(url);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) u.searchParams.set(key, String(value));
  }
  const response = await fetch(u.toString(), { headers: BASE_HEADERS });
  if (response.status === 412 || response.status === 429) {
    throw new Error(`Bilibili blocked the cloud request (HTTP ${response.status}). Local relay is required.`);
  }
  if (!response.ok) throw new Error(`Bilibili request failed (HTTP ${response.status}).`);
  const data = await response.json();
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Bilibili returned invalid JSON.");
  return data;
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
  const lang = String(language || "auto").toLowerCase();
  if (lang !== "auto") {
    const exact = tracks.find((t) => String(t.lan || "").toLowerCase() === lang);
    if (exact) return exact;
  }
  for (const pref of ["zh-cn", "zh-hans", "zh", "ai-zh", "zh-hant"]) {
    const found = tracks.find((t) => String(t.lan || "").toLowerCase().startsWith(pref));
    if (found) return found;
  }
  return tracks[0];
}

async function cloudParts(url) {
  const bvid = await resolveBvid(url);
  const payload = await biliJson("https://api.bilibili.com/x/web-interface/view", { bvid });
  if (payload.code !== 0) throw new Error(`Bilibili metadata API error: ${payload.message || "unknown"} (code ${payload.code}).`);
  const data = payload.data || {};
  const owner = data.owner && typeof data.owner === "object" ? data.owner : {};
  const parts = pagesFromVideo(data).filter((p) => p?.cid).map((p, i) => {
    const part = Number(p.page || i + 1);
    return {
      part,
      cid: Number(p.cid),
      title: String(p.part || `P${part}`),
      duration_seconds: p.duration == null ? null : Number(p.duration),
      url: `https://www.bilibili.com/video/${bvid}?p=${part}`
    };
  });
  return {
    status: "ok",
    bvid,
    title: String(data.title || "") || null,
    author: String(owner.name || "") || null,
    description: String(data.desc || "") || null,
    total_parts: parts.length,
    fetch_strategy: "cloud_direct",
    parts
  };
}

async function cloudTranscript(url, part, language, maxChars) {
  const meta = await cloudParts(url);
  const selected = meta.parts.find((p) => p.part === part);
  if (!selected) return { status: "error", part, error: `Part P${part} does not exist.` };
  const payload = await biliJson("https://api.bilibili.com/x/player/wbi/v2", { bvid: meta.bvid, cid: selected.cid });
  if (payload.code !== 0) throw new Error(`Bilibili player API error: ${payload.message || "unknown"} (code ${payload.code}).`);
  const player = payload.data || {};
  const subtitle = player.subtitle && typeof player.subtitle === "object" ? player.subtitle : {};
  const tracks = Array.isArray(subtitle.subtitles) ? subtitle.subtitles.filter((t) => t && typeof t === "object") : [];
  const available_tracks = tracks.map((track) => ({
    language: String(track.lan || "unknown"),
    language_name: String(track.lan_doc || "") || null,
    is_ai: isAiTrack(track)
  }));
  if (!tracks.length) {
    const needLogin = Boolean(player.need_login_subtitle || subtitle.need_login_subtitle);
    return {
      status: needLogin ? "login_required" : "no_subtitles",
      bvid: meta.bvid,
      part,
      part_title: selected.title,
      fetch_strategy: "cloud_direct",
      available_tracks,
      error: needLogin ? "Bilibili reports that subtitle access requires login." : "No official/AI subtitle track was exposed."
    };
  }
  const track = pickTrack(tracks, language);
  if (!track?.subtitle_url) return { status: "no_subtitles", bvid: meta.bvid, part, part_title: selected.title, available_tracks };
  const subtitleUrl = String(track.subtitle_url).startsWith("//") ? `https:${track.subtitle_url}` : String(track.subtitle_url);
  const sub = await biliJson(subtitleUrl);
  const body = Array.isArray(sub.body) ? sub.body : [];
  const segments = [];
  const lines = [];
  let chars = 0;
  for (const item of body) {
    const text = String(item?.content || "").trim();
    if (!text) continue;
    const timestamp = ts(item.from);
    const line = `[${timestamp}] ${text}`;
    if (chars + line.length + 1 > maxChars) break;
    chars += line.length + 1;
    lines.push(line);
    segments.push({ start: Number(item.from || 0), end: Number(item.to ?? item.from ?? 0), timestamp, text });
  }
  return {
    status: "ok",
    bvid: meta.bvid,
    part,
    part_title: selected.title,
    language: String(track.lan || "unknown"),
    language_name: String(track.lan_doc || "") || null,
    source: isAiTrack(track) ? "ai" : "official",
    fetch_strategy: "cloud_direct",
    available_tracks,
    segments,
    transcript: lines.join("\n")
  };
}

async function partsWithFallback(url, env) {
  if (env?.LOCAL_RELAY_URL) {
    try {
      const data = await callRelay(env, "parts", { url });
      return { ...data, fetch_strategy: data.fetch_strategy || "local_relay" };
    } catch (relayError) {
      try {
        const cloud = await cloudParts(url);
        return { ...cloud, relay_warning: relayError instanceof Error ? relayError.message : String(relayError) };
      } catch (cloudError) {
        throw new Error(`Local relay failed: ${relayError instanceof Error ? relayError.message : String(relayError)}; cloud fallback failed: ${cloudError instanceof Error ? cloudError.message : String(cloudError)}`);
      }
    }
  }
  return cloudParts(url);
}

async function transcriptWithFallback(url, part, language, maxChars, env) {
  if (env?.LOCAL_RELAY_URL) {
    try {
      const data = await callRelay(env, "transcript", { url, part, language, max_chars: maxChars });
      return { ...data, fetch_strategy: data.fetch_strategy || "local_relay" };
    } catch (relayError) {
      try {
        const cloud = await cloudTranscript(url, part, language, maxChars);
        return { ...cloud, relay_warning: relayError instanceof Error ? relayError.message : String(relayError) };
      } catch (cloudError) {
        throw new Error(`Local relay failed: ${relayError instanceof Error ? relayError.message : String(relayError)}; cloud fallback failed: ${cloudError instanceof Error ? cloudError.message : String(cloudError)}`);
      }
    }
  }
  return cloudTranscript(url, part, language, maxChars);
}

function createServer(env) {
  const server = new McpServer({ name: "bilibili-video-reader", version: "3.0.0" });

  server.registerTool("get_bilibili_video_parts", {
    description: "Get all P parts of a Bilibili video. When a local relay is configured, Bilibili is accessed from the user's own computer/network to avoid cloud-IP anti-abuse blocks.",
    inputSchema: { url: z.string().min(1) }
  }, async ({ url }) => {
    try {
      return asToolText(await partsWithFallback(url, env));
    } catch (error) {
      return asToolText({ status: "error", total_parts: 0, parts: [], error: error instanceof Error ? error.message : String(error) });
    }
  });

  server.registerTool("get_bilibili_part_transcript", {
    description: "Get official/AI subtitles for one Bilibili P. Prefer the local relay so the request uses the user's residential IP and browser login state.",
    inputSchema: {
      url: z.string().min(1),
      part: z.number().int().min(1).optional(),
      language: z.string().optional(),
      max_chars: z.number().int().min(2000).max(250000).optional()
    }
  }, async ({ url, part = 1, language = "auto", max_chars = 120000 }) => {
    try {
      return asToolText(await transcriptWithFallback(url, part, language, max_chars, env));
    } catch (error) {
      return asToolText({ status: "error", part, error: error instanceof Error ? error.message : String(error) });
    }
  });

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
        version: "3.0.0",
        local_relay_configured: Boolean(env?.LOCAL_RELAY_URL)
      });
    }
    if (url.pathname !== "/mcp") return new Response("Bilibili Video Reader MCP. Use /mcp or /health.");
    return createMcpHandler(() => createServer(env))(request, env, ctx);
  }
};
