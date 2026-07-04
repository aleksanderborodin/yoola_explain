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

  const [known, page] = await Promise.all([
    host ? chrome.runtime.sendMessage({ type: "site-agreements", host }) : { entries: [] },
    chrome.runtime.sendMessage({ type: "page-links", tabId: tab.id }),
  ]);
  const entries = known?.entries ?? [];
  const knownUrls = new Set(entries.map((e) => e.url));
  const candidates = (page?.links ?? []).filter((l) => !knownUrls.has(l.url));

  list.innerHTML = "";
  for (const entry of entries) list.appendChild(gradedRow(entry, tab));
  for (const link of candidates) list.appendChild(candidateRow(link, tab));
  if (!list.children.length) {
    list.innerHTML = `<div class="muted">No agreements found here yet. Open a terms or
      privacy page (or use the button below) — once analyzed, it shows up for everyone.</div>`;
  }
}

function gradedRow(entry, tab) {
  const label = pathLabel(entry.url);
  const row = row_(
    `<span class="stamp g-${entry.grade}"><span>${entry.grade}</span></span>`,
    label,
    `${VERDICT[entry.grade]} · ${entry.alerts} alert${entry.alerts === 1 ? "" : "s"}`
  );
  row.addEventListener("click", () => openInPage(tab, entry.url, label));
  return row;
}

function candidateRow(link, tab) {
  const row = row_(
    `<span class="stamp new"><span>?</span></span>`,
    link.label,
    "Not analyzed yet — click to analyze"
  );
  row.addEventListener("click", () => openInPage(tab, link.url, link.label));
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

async function openInPage(tab, url, label) {
  const reply = await chrome.runtime.sendMessage({
    type: "popup-open-url",
    tabId: tab.id,
    url,
    label,
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
    "the web store). For a PDF: go back to the page that links to it and right-click " +
    "the link → Summarize linked document with Yoola.";
}

function pathLabel(url) {
  try {
    const u = new URL(url);
    const segment = decodeURIComponent(u.pathname.split("/").filter(Boolean).pop() ?? "");
    const cleaned = segment
      .replace(/\.(pdf|docx?|html?|php|aspx?)$/i, "")
      .replace(/[_\-+]+/g, " ")
      .trim();
    return cleaned || u.hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
