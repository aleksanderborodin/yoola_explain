// Yoola service worker: the ONLY thing that talks to the server (Design v4 §5).
// Owns the L1 cache, the badge, the right-click menu, and the registry sync.

const API_BASE = "http://127.0.0.1:8000"; // switch to the deployed origin for release
const L1_MAX_ENTRIES = 50;
const L1_REFRESH_DAYS = 7;
const REGISTRY_SYNC_HOURS = 6;

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "yoola-summarize",
    title: "Summarize this page with Yoola",
    contexts: ["page", "selection", "link", "action"],
  });
  chrome.alarms.create("yoola-registry", { periodInMinutes: REGISTRY_SYNC_HOURS * 60 });
  syncRegistry();
});
chrome.runtime.onStartup.addListener(syncRegistry);
chrome.alarms.onAlarm.addListener((a) => a.name === "yoola-registry" && syncRegistry());

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "yoola-summarize" && tab?.id != null) {
    chrome.tabs.sendMessage(tab.id, { type: "summarize-current" });
  }
});

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
    const got = await fetch(
      `${API_BASE}/v1/summary?url=${encodeURIComponent(url)}&lang=${encodeURIComponent(language)}`
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
    });
    return { ok: true };
  } catch {
    return { ok: false };
  }
}

async function syncRegistry() {
  try {
    const response = await fetch(`${API_BASE}/v1/registry`);
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
