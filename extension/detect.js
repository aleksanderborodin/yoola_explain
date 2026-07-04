// Detection — the UX gate only, never a security boundary (the server
// plausibility + LLM legal-check are the real gates). Three signals, cheapest
// first, and none of them phones home per page:
//   1. cheap local heuristic (URL path / title)
//   2. marker-density scan (only if #1 passes)
//   3. registry membership: the server's set of known legal-page URLs, checked
//      LOCALLY against a digest the background worker syncs — this is how a
//      page one user added by right-click lights up for everyone else, even
//      when the heuristic would miss it.

const YOOLA_URL_HINTS = /\/(terms|tos|privacy|eula|legal|conditions|agreement|policy|policies|gdpr|ccpa|cookies?)([/._-]|$)/i;
const YOOLA_TITLE_HINTS = /(terms|privacy|eula|legal|agreement|conditions|policy|licen[sc]e)/i;

const YOOLA_MARKERS = [
  "terms of service", "terms of use", "terms and conditions", "privacy policy",
  "user agreement", "these terms", "this agreement", "personal data",
  "intellectual property", "liability", "warranty", "indemnif", "arbitrat",
  "governing law", "termination", "you agree", "we reserve the right",
];

const YOOLA_TRACKING = /^(utm_|gclid$|fbclid$|msclkid$|ref$|mc_cid$|mc_eid$|igshid$)/i;

function yoolaCheapGate() {
  return (
    YOOLA_URL_HINTS.test(location.pathname) ||
    YOOLA_TITLE_HINTS.test(document.title) ||
    YOOLA_TITLE_HINTS.test(document.querySelector("h1")?.textContent ?? "")
  );
}

function yoolaDensityScan() {
  const text = (document.body?.innerText ?? "").toLowerCase();
  const words = text.split(/\s+/).length;
  if (words < 300 || words > 200000) return false;
  let hits = 0;
  for (const marker of YOOLA_MARKERS) {
    let i = -1;
    while ((i = text.indexOf(marker, i + 1)) !== -1) hits++;
  }
  return (hits * 1000) / words >= 2.0;
}

// Mirror the server's normalize_url closely enough for registry lookups. A
// mismatch only costs a missed pill (degrades to heuristic), never correctness.
function yoolaNormalizeUrl(href) {
  let u;
  try {
    u = new URL(href);
  } catch {
    return null;
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") return null;
  const params = [...u.searchParams.entries()].filter(([k]) => !YOOLA_TRACKING.test(k));
  params.sort((a, b) => (a[0] + a[1]).localeCompare(b[0] + b[1]));
  const query = params.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
  const host = u.hostname.toLowerCase().replace(/\.$/, "");
  const port = u.port && u.port !== (u.protocol === "https:" ? "443" : "80") ? `:${u.port}` : "";
  const path = u.pathname || "/";
  return `${u.protocol}//${host}${port}${path}${query ? "?" + query : ""}`;
}

async function yoolaInRegistry(href) {
  const { registry } = await chrome.storage.local.get("registry");
  if (!registry?.urls?.length) return false;
  const urlKey = yoolaNormalizeUrl(href);
  if (!urlKey) return false;
  const bytes = new TextEncoder().encode(urlKey);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return new Set(registry.urls).has(hex.slice(0, registry.hash_len));
}

// Returns "heuristic" | "registry" | null — null means keep the icon dim.
async function yoolaDetect() {
  if (yoolaCheapGate() && yoolaDensityScan()) return "heuristic";
  if (await yoolaInRegistry(location.href)) return "registry";
  return null;
}

// Fallback extractor — used ONLY when the server can't fetch (quarantined path).
function yoolaExtractText() {
  const root =
    document.querySelector("main") ??
    document.querySelector("article") ??
    document.querySelector('[role="main"]') ??
    document.body;
  return (root?.innerText ?? "").trim().slice(0, 400000);
}
