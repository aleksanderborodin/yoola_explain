// Detection — the UX gate only, never a security boundary (the server
// plausibility + LLM legal-check are the real gates). Three signals, cheapest
// first, and none of them phones home per page:
//   1. cheap local heuristic (URL path / title)
//   2. marker-density scan (only if #1 passes)
//   3. registry membership: the server's set of known legal-page URLs, checked
//      LOCALLY against a digest the background worker syncs — this is how a
//      page one user added by right-click lights up for everyone else, even
//      when the heuristic would miss it.

const YOOLA_URL_HINTS = /\/(terms|tos|privacy|eula|legal|conditions|agreement|policy|policies|gdpr|ccpa|cookies?|pravila|usloviya|soglashenie|oferta)([/._-]|$)/i;
const YOOLA_TITLE_HINTS = /(terms|privacy|eula|legal|agreement|conditions|policy|licen[sc]e|правил|условия|соглашени|конфиденциальн|оферта|политика)/i;

const YOOLA_MARKERS = [
  // en
  "terms of service", "terms of use", "terms and conditions", "privacy policy",
  "user agreement", "these terms", "this agreement", "personal data",
  "intellectual property", "liability", "warranty", "indemnif", "arbitrat",
  "governing law", "termination", "you agree", "we reserve the right",
  // ru (mirrors the server's multilingual plausibility markers)
  "условия использования", "пользовательское соглашение", "политика конфиденциальности",
  "настоящие условия", "персональные данные", "персональных данных", "конфиденциальность",
  "ответственность", "интеллектуальной собственности", "вы соглашаетесь",
  "оставляем за собой право", "расторжение", "оферта", "третьим лицам",
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

// Stamp each found link with whether Yoola ALREADY has a summary for it —
// same normalize-and-hash membership check as detection, applied to the link
// target. (Registry keys are requested-URL hashes, so a link that only reaches
// a known document through a redirect won't match here — the server's alias
// map still resolves it instantly on click.) Links the server judged NOT a
// legal agreement (422, remembered by the worker) are dropped entirely —
// never re-offered as candidates.
async function yoolaMarkKnown(links) {
  const { notLegal = {} } = await chrome.storage.local.get("notLegal");
  const kept = links.filter((link) => !(link.url in notLegal));
  await Promise.all(
    kept.map(async (link) => {
      link.known = await yoolaInRegistry(link.url);
    })
  );
  return kept;
}

// Consent-moment detection: a page that ASKS you to accept terms (signup/checkout)
// rather than being the terms. If it links to legal documents, Yoola can
// summarize the LINKED docs in place — the user never has to navigate away
// (the server fetches by URL, so being on the page is never required).
const YOOLA_LINK_TEXT = /(terms|conditions|privacy|policy|eula|licen[sc]e|agreement|правил|услови|соглашен|согласи|конфиденциальн|оферт|политик|персональн|обработк)/i;

function yoolaConsentContext() {
  if (document.querySelector('input[type="password"]')) return true;
  const checkboxes = document.querySelectorAll('input[type="checkbox"]');
  for (const box of checkboxes) {
    const label = (box.closest("label") ?? box.parentElement)?.textContent ?? "";
    if (/(agree|accept|consent)/i.test(label) && YOOLA_LINK_TEXT.test(label)) return true;
  }
  return false;
}

// Human label for a legal link: its text when it reads like one, else a
// cleaned-up filename (decoded — Cyrillic paths must not show as %D0%BF…).
function yoolaLinkLabel(a, textHit, text) {
  if (textHit) return text.slice(0, 90);
  const title = (a.getAttribute("title") ?? "").trim();
  if (title) return title.slice(0, 90);
  let segment = (a.pathname ?? "").split("/").filter(Boolean).pop() ?? "";
  try {
    segment = decodeURIComponent(segment);
  } catch {
    /* keep raw on malformed escapes */
  }
  segment = segment
    .replace(/\.(pdf|docx?|html?|php|aspx?)$/i, "")
    .replace(/[_\-+]+/g, " ")
    .trim();
  return segment.slice(0, 90) || "Legal document";
}

function yoolaFindLegalLinks() {
  const found = new Map(); // normalized url -> label
  for (const a of document.querySelectorAll("a[href]")) {
    const text = (a.textContent ?? "").trim().replace(/\s+/g, " ");
    if (!text || text.length > 90) continue;
    const textHit = YOOLA_LINK_TEXT.test(text);
    const hrefHit = YOOLA_URL_HINTS.test(a.pathname ?? "") || YOOLA_LINK_TEXT.test(a.pathname ?? "");
    if (!textHit && !hrefHit) continue;
    const url = yoolaNormalizeUrl(a.href);
    if (!url || url === yoolaNormalizeUrl(location.href)) continue;
    if (!found.has(url)) found.set(url, yoolaLinkLabel(a, textHit, text));
    if (found.size >= 4) break;
  }
  return [...found].map(([url, label]) => ({ url, label }));
}

// Returns {kind: "heuristic" | "registry" | "links", links} or null (icon stays dim).
async function yoolaDetect() {
  if (yoolaCheapGate() && yoolaDensityScan()) return { kind: "heuristic", links: [] };
  if (await yoolaInRegistry(location.href)) return { kind: "registry", links: [] };
  if (yoolaConsentContext()) {
    const links = await yoolaMarkKnown(yoolaFindLegalLinks());
    if (links.length) return { kind: "links", links };
  }
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
