// The site dossier: everything this site asks you to agree to, in one click.
// Two sources merged — documents Yoola has already graded for this host
// (server directory, instant) and legal links visible on the current page
// (candidates, analyzed on request). Clicking any row opens the panel in-page.

const VERDICT = { A: "Fair terms", B: "Mostly fair", C: "Mixed terms", D: "Harsh terms", E: "Very harsh" };

init();

async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const list = document.getElementById("list");
  if (tab?.id == null) return;

  let host = null;
  try {
    const u = new URL(tab.url);
    if (u.protocol === "http:" || u.protocol === "https:") host = u.hostname;
  } catch {
    /* chrome:// etc. */
  }
  document.getElementById("host-line").textContent = host
    ? `Agreements on ${host.replace(/^www\./, "")}`
    : "This page";

  // The worker builds the dossier (directory entries + page links, deduped,
  // labels unified) — the SAME rows the in-page panel shows, by construction.
  const page = await chrome.runtime.sendMessage({ type: "page-links", tabId: tab.id });
  const reply = await chrome.runtime.sendMessage({
    type: "site-dossier",
    host,
    links: page?.links ?? [],
  });
  const dossier = reply?.rows ?? [];

  list.innerHTML = "";
  for (const item of dossier) list.appendChild(rowFor(item, tab, dossier));
  if (!list.children.length) {
    list.innerHTML = `<div class="muted">No agreements found here yet. Open a terms or
      privacy page (or use the button below) — once analyzed, it shows up for everyone.</div>`;
  }
}

function rowFor(item, tab, dossier) {
  // `known` = the registry says a summary exists for this exact URL (e.g. a
  // link to another site's terms) — it opens instantly, just ungraded here.
  const stamp = item.grade
    ? `<span class="stamp g-${item.grade}"><span>${item.grade}</span></span>`
    : item.known
      ? `<span class="stamp known"><span>✓</span></span>`
      : `<span class="stamp new"><span>?</span></span>`;
  const sub = item.grade
    ? `${VERDICT[item.grade]} · ${item.alerts} alert${item.alerts === 1 ? "" : "s"}`
    : item.known
      ? "Already summarized — opens instantly"
      : "Not analyzed yet — click to analyze";
  const row = row_(stamp, item.label, sub);
  row.addEventListener("click", () => openInPage(tab, item.url, item.label, dossier));
  return row;
}

function row_(stampHtml, label, sub) {
  const row = document.createElement("button");
  row.className = "row";
  row.innerHTML = `${stampHtml}<span><span class="row-label"></span><br><span class="row-sub"></span></span>`;
  row.querySelector(".row-label").textContent = label;
  row.querySelector(".row-sub").textContent = sub;
  return row;
}

async function openInPage(tab, url, label, dossier) {
  const reply = await chrome.runtime.sendMessage({
    type: "popup-open-url",
    tabId: tab.id,
    url,
    label,
    list: dossier?.length > 1 ? dossier : undefined,
  });
  if (reply?.ok) window.close();
  else cannotRun();
}

document.getElementById("summarize").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id == null) return;
  const reply = await chrome.runtime.sendMessage({ type: "popup-summarize", tabId: tab.id });
  if (reply?.ok) window.close();
  else cannotRun();
});

function cannotRun() {
  const button = document.getElementById("summarize");
  button.disabled = true;
  button.textContent = "Can't run on this page";
  document.getElementById("fine").textContent =
    "Chrome doesn't let extensions run on this page type (PDF viewer, browser pages, " +
    "the web store), so the panel can't open here. Visit any regular page on the site " +
    "and click the row there — or right-click a link to the document → Summarize " +
    "linked document with Yoola.";
}

