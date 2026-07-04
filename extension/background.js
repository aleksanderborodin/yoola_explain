// Yoola service worker: the ONLY thing that talks to the server (Design v4 §5).
// Owns the L1 cache, the badge, the right-click menu, and the registry sync.

importScripts("detect.js"); // for yoolaNormalizeUrl — one normalization everywhere

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
  if (msg.type === "popup-open-url") {
    try {
      await sendToContent(msg.tabId, {
        type: "summarize-url",
        url: msg.url,
        label: msg.label,
        list: msg.list, // the popup's dossier — lets the panel offer "← back to the list"
      });
      return { ok: true };
    } catch {
      return { ok: false };
    }
  }
  if (msg.type === "extract-remote") return extractViaTab(msg.url);
  if (msg.type === "site-agreements") {
    // What Yoola already knows about this host — instant, graded. The server
    // matches the host and its subdomains; when the user stands on a deep
    // subdomain (app.foo.example.com) with no entries, retry from the site's
    // base domain so terms living on example.com still show up.
    let entries = await fetchDirectory(msg.host);
    if (!entries.length) {
      const base = baseHost(msg.host);
      if (base && base !== msg.host.replace(/^www\./, "")) entries = await fetchDirectory(base);
    }
    return { entries };
  }
  if (msg.type === "page-links") {
    // Legal links visible on the current page (footer Terms/Privacy etc.).
    // An old content script answers undefined (no such handler) rather than
    // throwing — treat that as "missing" and inject the current one.
    try {
      let reply = await sendToContent(msg.tabId, { type: "get-legal-links" });
      if (!reply?.links) {
        await chrome.scripting.executeScript({
          target: { tabId: msg.tabId },
          files: ["detect.js", "content.js"],
        });
        reply = await chrome.tabs.sendMessage(msg.tabId, { type: "get-legal-links" });
      }
      return reply?.links ? reply : { links: [] };
    } catch {
      return { links: [] };
    }
  }
  return { ok: false, detail: "unknown message" };
}

async function fetchDirectory(host) {
  try {
    const response = await fetch(`${API_BASE}/v1/directory?host=${encodeURIComponent(host)}`, {
      signal: AbortSignal.timeout(8000),
    });
    if (response.ok) return (await response.json()).entries ?? [];
  } catch {
    /* offline / blocked — the page-links half of the popup still renders */
  }
  return [];
}

// app.foo.example.com -> example.com; keeps three labels for common
// second-level suffixes (example.co.uk). Heuristic only — a miss just means
// no extra directory rows, never an error.
function baseHost(host) {
  const labels = host.replace(/^www\./, "").split(".");
  if (labels.length <= 2) return null;
  const take = /^(co|com|net|org|gov|edu|ac)$/.test(labels[labels.length - 2]) ? 3 : 2;
  return labels.length > take ? labels.slice(-take).join(".") : null;
}

// Last-resort reader for documents the SERVER can't fetch (bot walls,
// JS-rendered pages): open the URL in a background tab, let the user's own
// browser render it, pull the text, close the tab. The text then goes through
// the quarantined client_content path (never trusted as the URL's identity).
// Fails cleanly on pages Chrome won't script (its PDF viewer, chrome://).
async function extractViaTab(url) {
  let tab;
  try {
    tab = await chrome.tabs.create({ url, active: false });
    await waitForLoad(tab.id, 25000);
    let text = await grabText(tab.id);
    if ((text ?? "").length < 500) {
      // likely an SPA still rendering after "complete" — one more chance
      await new Promise((resolve) => setTimeout(resolve, 2500));
      text = await grabText(tab.id);
    }
    return text && text.length >= 200 ? { ok: true, content: text } : { ok: false };
  } catch {
    return { ok: false };
  } finally {
    if (tab?.id != null) chrome.tabs.remove(tab.id).catch(() => {});
  }
}

function waitForLoad(tabId, timeoutMs) {
  const SETTLE_MS = 1200; // let scripts/fonts finish after "complete"
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("load timeout"));
    }, timeoutMs);
    const onUpdated = (id, info) => {
      if (id !== tabId || info.status !== "complete") return;
      cleanup();
      setTimeout(resolve, SETTLE_MS);
    };
    const cleanup = () => {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
    };
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.get(tabId).then((t) => {
      if (t.status === "complete") {
        cleanup();
        setTimeout(resolve, SETTLE_MS);
      }
    }).catch(() => {});
  });
}

async function grabText(tabId) {
  // Self-contained func (mirrors detect.js#yoolaExtractText) — injecting
  // detect.js here would redeclare its top-level consts in tabs that already
  // have the content scripts and throw.
  const [res] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const root =
        document.querySelector("main") ??
        document.querySelector("article") ??
        document.querySelector('[role="main"]') ??
        document.body;
      return (root?.innerText ?? "").trim().slice(0, 400000);
    },
  });
  return res?.result ?? "";
}

async function summarize({ url, language, clientContent }) {
  // One key per document: location.href arrives with fragments/tracking params
  // that the server strips anyway — normalizing here keeps the L1 cache from
  // storing terms#a and terms#b as different entries.
  url = yoolaNormalizeUrl(url) ?? url;
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
    if (response.status === 422) {
      // Remember the verdict so this URL stops being offered as a candidate
      // (in the popup and pickers). Right-click still allows a manual retry.
      await rememberNotLegal(url);
      return { ok: false, code: 422, detail: "This page doesn't look like a legal agreement." };
    }
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

// URLs the server judged "not a legal agreement" (422). Kept so lists stop
// offering them; capped, oldest pruned first.
const NOT_LEGAL_MAX = 200;
async function rememberNotLegal(url) {
  const { notLegal = {} } = await chrome.storage.local.get("notLegal");
  notLegal[url] = Date.now();
  const keys = Object.keys(notLegal);
  if (keys.length > NOT_LEGAL_MAX) {
    keys.sort((a, b) => notLegal[a] - notLegal[b]);
    for (const key of keys.slice(0, keys.length - NOT_LEGAL_MAX)) delete notLegal[key];
  }
  await chrome.storage.local.set({ notLegal });
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
