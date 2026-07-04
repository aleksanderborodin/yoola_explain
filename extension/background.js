// Yoola service worker: the ONLY thing that talks to the server (Design v4 §5).
// Owns the L1 cache, the badge, the right-click menu, and the registry sync.

const API_BASE = "https://yoola-explain.aleksanderbor.ru"; // dev: "http://127.0.0.1:8000"
const L1_MAX_ENTRIES = 50;
const L1_REFRESH_DAYS = 7;
const REGISTRY_SYNC_HOURS = 6;

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "yoola-summarize",
    title: "Summarize this page with Yoola",
    contexts: ["page", "selection", "action"],
  });
  // Right-click a "Terms"/"Privacy" link on a signup page: summarize the LINKED
  // document without navigating to it (the server fetches by URL, so being on
  // the page is never required).
  chrome.contextMenus.create({
    id: "yoola-summarize-link",
    title: "Summarize linked document with Yoola",
    contexts: ["link"],
  });
  chrome.alarms.create("yoola-registry", { periodInMinutes: REGISTRY_SYNC_HOURS * 60 });
  syncRegistry();
});
chrome.runtime.onStartup.addListener(syncRegistry);
chrome.alarms.onAlarm.addListener((a) => a.name === "yoola-registry" && syncRegistry());

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (tab?.id == null) return;
  if (info.menuItemId === "yoola-summarize") {
    sendToContent(tab.id, { type: "summarize-current" });
  } else if (info.menuItemId === "yoola-summarize-link" && info.linkUrl) {
    sendToContent(tab.id, { type: "summarize-url", url: info.linkUrl });
  }
});

// Deliver a message to the tab's content script, injecting it first if it's
// missing (after an extension reload, existing tabs lose their content scripts;
// they must self-heal rather than tell the user to refresh). Throws only where
// injection is impossible (chrome:// pages, the PDF viewer, the web store).
async function sendToContent(tabId, msg) {
  try {
    return await chrome.tabs.sendMessage(tabId, msg);
  } catch {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["detect.js", "content.js"],
    });
    return await chrome.tabs.sendMessage(tabId, msg);
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  handle(msg, sender).then(sendResponse);
  return true;
});

async function handle(msg, sender) {
  if (msg.type === "detected") {
    if (sender.tab?.id != null) {
      chrome.action.setBadgeText({ tabId: sender.tab.id, text: "ToS" });
      chrome.action.setBadgeBackgroundColor({ tabId: sender.tab.id, color: "#C9A24B" });
    }
    return { ok: true };
  }
  if (msg.type === "summarize") return summarize(msg);
  if (msg.type === "report") return report(msg);
  if (msg.type === "popup-summarize") {
    try {
      await sendToContent(msg.tabId, { type: "summarize-current" });
      return { ok: true };
    } catch {
      return { ok: false }; // genuinely uninjectable page (PDF viewer, chrome://)
    }
  }
  return { ok: false, detail: "unknown message" };
}

async function summarize({ url, language, clientContent }) {
  const key = `l1:${url}:${language}`;
  const cached = (await chrome.storage.local.get(key))[key];
  if (cached && !isStale(cached.payload)) {
    await putL1(key, cached.payload);
    return { ok: true, payload: cached.payload, fromL1: true };
  }

  try {
    // Timeouts matter: a connection dropped mid-path (e.g. DPI, gotcha #14)
    // otherwise hangs the panel on "Summarizing…" forever.
    const got = await fetch(
      `${API_BASE}/v1/summary?url=${encodeURIComponent(url)}&lang=${encodeURIComponent(language)}`,
      { signal: AbortSignal.timeout(20000) }
    );
    if (got.ok) {
      const payload = await got.json();
      if (!isStale(payload)) {
        await putL1(key, payload);
        return { ok: true, payload };
      }
    }

    const body = { url, language };
    if (clientContent) body.client_content = clientContent;
    const response = await fetch(`${API_BASE}/v1/summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(300000), // a first analysis legitimately takes 1-2 min
    });

    if (response.status === 200) {
      const payload = await response.json();
      await putL1(key, payload);
      syncRegistry(); // a fresh generation may have added this URL for everyone
      return { ok: true, payload };
    }
    if (response.status === 502 && !clientContent) return { ok: false, needClientContent: true };
    if (response.status === 202)
      return { ok: false, detail: "Busy right now — the daily limit was reached. Try again later." };
    if (response.status === 422)
      return { ok: false, detail: "This page doesn't look like a legal agreement." };
    if (response.status === 429)
      return { ok: false, detail: "Daily limit reached for your connection. Cached pages still work." };
    if (response.status === 503)
      return { ok: false, detail: "Yoola is at capacity right now. Try again later." };
    const err = await response.json().catch(() => ({}));
    return { ok: false, detail: err.detail || `Server error (${response.status}).` };
  } catch {
    if (cached) return { ok: true, payload: cached.payload, fromL1: true };
    return { ok: false, detail: "Can't reach the Yoola server." };
  }
}

async function report({ docVersion, category }) {
  try {
    await fetch(`${API_BASE}/v1/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc_version: docVersion, category }),
      signal: AbortSignal.timeout(15000),
    });
    return { ok: true };
  } catch {
    return { ok: false };
  }
}

async function syncRegistry() {
  try {
    const response = await fetch(`${API_BASE}/v1/registry`, {
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) return;
    const data = await response.json();
    await chrome.storage.local.set({ registry: { hash_len: data.hash_len, urls: data.urls } });
  } catch {
    // offline / server down — keep the last synced digest
  }
}

function isStale(payload) {
  return Date.now() - new Date(payload.generated_at).getTime() > L1_REFRESH_DAYS * 864e5;
}

async function putL1(key, payload) {
  await chrome.storage.local.set({ [key]: { payload, at: Date.now() } });
  const all = await chrome.storage.local.get(null);
  const entries = Object.entries(all).filter(([k]) => k.startsWith("l1:"));
  if (entries.length <= L1_MAX_ENTRIES) return;
  entries.sort((a, b) => a[1].at - b[1].at);
  await chrome.storage.local.remove(entries.slice(0, entries.length - L1_MAX_ENTRIES).map(([k]) => k));
}
