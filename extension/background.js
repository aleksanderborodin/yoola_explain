// Yoola service worker: the ONLY thing that talks to the server (Design v4 §5).
// Owns the L1 cache (chrome.storage.local, LRU) and the badge.

const API_BASE = "http://127.0.0.1:8000"; // switch to the deployed origin for release
const L1_MAX_ENTRIES = 50;
const L1_REFRESH_DAYS = 7; // older cached entries get re-POSTed so the server can revalidate

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  handle(msg, sender).then(sendResponse);
  return true; // async response
});

async function handle(msg, sender) {
  if (msg.type === "detected") {
    if (sender.tab?.id != null) {
      chrome.action.setBadgeText({ tabId: sender.tab.id, text: "ToS" });
      chrome.action.setBadgeBackgroundColor({ tabId: sender.tab.id, color: "#f0a050" });
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
    touchL1(key, cached.payload);
    return { ok: true, payload: cached.payload, fromL1: true };
  }

  try {
    // Cheap read first; generate only on a miss (v4 C11).
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
      return { ok: true, payload };
    }
    if (response.status === 502 && !clientContent) {
      return { ok: false, needClientContent: true };
    }
    if (response.status === 202) {
      return { ok: false, detail: "Busy right now (daily budget reached) — try again later." };
    }
    if (response.status === 422) {
      return { ok: false, detail: "This page doesn't look like a legal agreement." };
    }
    if (response.status === 429) {
      return { ok: false, detail: "Daily limit reached for your connection — cached pages still work." };
    }
    const err = await response.json().catch(() => ({}));
    return { ok: false, detail: err.detail || `Server error (${response.status}).` };
  } catch {
    if (cached) return { ok: true, payload: cached.payload, fromL1: true }; // stale beats nothing
    return { ok: false, detail: "Cannot reach the Yoola server." };
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

function isStale(payload) {
  const age = Date.now() - new Date(payload.generated_at).getTime();
  return age > L1_REFRESH_DAYS * 24 * 3600 * 1000;
}

async function putL1(key, payload) {
  await chrome.storage.local.set({ [key]: { payload, at: Date.now() } });
  await evictL1();
}

async function touchL1(key, payload) {
  await chrome.storage.local.set({ [key]: { payload, at: Date.now() } });
}

async function evictL1() {
  const all = await chrome.storage.local.get(null);
  const entries = Object.entries(all).filter(([k]) => k.startsWith("l1:"));
  if (entries.length <= L1_MAX_ENTRIES) return;
  entries.sort((a, b) => a[1].at - b[1].at);
  const doomed = entries.slice(0, entries.length - L1_MAX_ENTRIES).map(([k]) => k);
  await chrome.storage.local.remove(doomed);
}
