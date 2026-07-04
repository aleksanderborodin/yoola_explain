// Client-side detection — the UX gate only, never a security boundary
// (Design v4: the server plausibility gate is the enforcement point).
// Cheap gates run first; the density scan runs only when they pass.

const YOOLA_URL_HINTS = /\/(terms|tos|privacy|eula|legal|conditions|agreement|policy|policies)([/._-]|$)/i;
const YOOLA_TITLE_HINTS = /(terms|privacy|eula|legal|agreement|conditions|policy)/i;

const YOOLA_MARKERS = [
  "terms of service", "terms of use", "terms and conditions", "privacy policy",
  "user agreement", "these terms", "this agreement", "personal data",
  "intellectual property", "liability", "warranty", "indemnif", "arbitrat",
  "governing law", "termination", "you agree", "we reserve the right",
];

function yoolaCheapGate() {
  return (
    YOOLA_URL_HINTS.test(location.pathname) ||
    YOOLA_TITLE_HINTS.test(document.title) ||
    YOOLA_TITLE_HINTS.test(document.querySelector("h1")?.textContent ?? "")
  );
}

// Marker density per 1000 words, mirroring the server gate's shape.
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

function yoolaDetectLegalPage() {
  return yoolaCheapGate() && yoolaDensityScan();
}

// Crude main-content extraction — used ONLY as the fallback when the server
// cannot fetch the page itself (v4 C1: the quarantined client-content path).
function yoolaExtractText() {
  const root =
    document.querySelector("main") ??
    document.querySelector("article") ??
    document.querySelector('[role="main"]') ??
    document.body;
  return (root?.innerText ?? "").trim().slice(0, 400000);
}
