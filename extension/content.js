// Yoola content script: quiet detection pill + summary panel.
// Auto-DETECT, never auto-summarize (Design v4 §5): nothing leaves the page
// until the user clicks.

(() => {
  if (window.__yoolaLoaded) return;
  window.__yoolaLoaded = true;

  const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 };
  let host = null;
  let shadow = null;

  if (yoolaDetectLegalPage()) {
    chrome.runtime.sendMessage({ type: "detected" });
    mountPill();
  }

  function ui() {
    if (shadow) return shadow;
    host = document.createElement("div");
    host.id = "yoola-host";
    shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    shadow.appendChild(style);
    document.documentElement.appendChild(host);
    return shadow;
  }

  function mountPill() {
    const root = ui();
    const pill = document.createElement("button");
    pill.className = "pill";
    pill.textContent = "📄 Terms detected — summarize?";
    pill.title = "Yoola: summarize this legal page";
    pill.addEventListener("click", () => {
      pill.remove();
      summarize();
    });
    root.appendChild(pill);
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "summarize-current") summarize();
  });

  async function summarize() {
    const root = ui();
    root.querySelector(".panel")?.remove();
    const panel = document.createElement("div");
    panel.className = "panel";
    panel.innerHTML = `<div class="hd"><span class="logo">Yoola</span><button class="x">×</button></div>
      <div class="bd"><p class="status">Summarizing…</p></div>`;
    panel.querySelector(".x").addEventListener("click", () => panel.remove());
    root.appendChild(panel);
    const body = panel.querySelector(".bd");

    const language = (navigator.language || "en").split("-")[0];
    let reply = await chrome.runtime.sendMessage({
      type: "summarize",
      url: location.href,
      language,
    });
    if (reply?.needClientContent) {
      body.querySelector(".status").textContent =
        "Site blocks our server — sending the page text instead…";
      reply = await chrome.runtime.sendMessage({
        type: "summarize",
        url: location.href,
        language,
        clientContent: yoolaExtractText(),
      });
    }
    if (!reply?.ok) {
      body.innerHTML = `<p class="status err">${escapeHtml(reply?.detail || "Something went wrong.")}</p>`;
      return;
    }
    render(body, reply.payload, reply.fromL1);
  }

  function render(body, s, fromL1) {
    const present = s.categories
      .filter((c) => c.status === "present")
      .sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
    const alerts = present.filter((c) => c.severity !== "low");
    const notAddressed = s.categories.filter((c) => c.status === "not_addressed");
    const sourceLabel = fromL1 ? "offline · cached" : s.source;

    body.innerHTML = `
      <div class="meta">
        <span class="grade g${s.grade}">${s.grade}</span>
        <span class="badge">${escapeHtml(sourceLabel)}</span>
        ${s.source_verified === false ? '<span class="badge warn">unverified source</span>' : ""}
      </div>
      <h3>⚠️ Alerts</h3>
      <div class="alerts"></div>
      <h3>TL;DR</h3>
      <ul class="tldr">${s.tldr.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>
      <details><summary>All ${s.categories.length} checks</summary><div class="all"></div></details>
      <p class="disclaimer">${escapeHtml(s.disclaimer)}</p>`;

    const alertsBox = body.querySelector(".alerts");
    if (!alerts.length) alertsBox.innerHTML = '<p class="none">No high-severity clauses found.</p>';
    for (const c of alerts) alertsBox.appendChild(categoryCard(c, s.doc_version));

    const allBox = body.querySelector(".all");
    for (const c of present.filter((c) => c.severity === "low")) {
      allBox.appendChild(categoryCard(c, s.doc_version));
    }
    const na = document.createElement("p");
    na.className = "none";
    na.textContent = "Not addressed: " + notAddressed.map((c) => c.title).join(", ");
    allBox.appendChild(na);
  }

  function categoryCard(c, docVersion) {
    const card = document.createElement("div");
    card.className = `card sev-${c.severity}`;
    card.innerHTML = `
      <div class="row">
        <strong>${escapeHtml(c.title)}</strong>
        <span class="sev">${c.severity}</span>
        ${c.confidence === "possible" ? '<span class="badge warn">possible — verify</span>' : ""}
      </div>
      <p>${escapeHtml(c.explanation || "")}</p>`;
    for (const quote of c.quotes || []) {
      const link = document.createElement("button");
      link.className = "quotelink";
      link.textContent = "verify in page →";
      link.title = quote.text;
      link.addEventListener("click", () => highlight(quote.text));
      card.appendChild(link);
    }
    const report = document.createElement("button");
    report.className = "report";
    report.textContent = "report wrong";
    report.addEventListener("click", async () => {
      report.disabled = true;
      report.textContent = "reported ✓";
      await chrome.runtime.sendMessage({
        type: "report",
        docVersion,
        category: c.id,
      });
    });
    card.appendChild(report);
    return card;
  }

  // Locate a quote in the live DOM. Offsets into extracted text are useless
  // here (v4 C4) — we search for the quote text itself, shrinking the prefix
  // until window.find succeeds.
  function highlight(quote) {
    const attempts = [quote, quote.slice(0, 80), quote.slice(0, 50), quote.slice(0, 30)];
    window.getSelection()?.removeAllRanges();
    for (const attempt of attempts) {
      const needle = attempt.replace(/\s+/g, " ").trim();
      if (needle.length >= 12 && window.find(needle, false, false, true, false, true, false)) {
        return;
      }
    }
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text ?? "";
    return div.innerHTML;
  }

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: -apple-system, "Segoe UI", Roboto, sans-serif; }
    .pill { position: fixed; right: 16px; bottom: 16px; z-index: 2147483647;
      background: #1a1c22; color: #f5f6f8; border: 1px solid #3a3f4a; border-radius: 999px;
      padding: 9px 14px; font-size: 13px; cursor: pointer; box-shadow: 0 4px 14px rgba(0,0,0,.35); }
    .pill:hover { background: #262a33; }
    .panel { position: fixed; top: 12px; right: 12px; bottom: 12px; width: 380px; max-width: 92vw;
      z-index: 2147483647; background: #14161b; color: #e8eaee; border: 1px solid #30343d;
      border-radius: 12px; display: flex; flex-direction: column; overflow: hidden;
      box-shadow: 0 8px 30px rgba(0,0,0,.5); font-size: 13.5px; line-height: 1.45; }
    .hd { display: flex; justify-content: space-between; align-items: center;
      padding: 10px 14px; border-bottom: 1px solid #262a33; }
    .logo { font-weight: 700; letter-spacing: .4px; }
    .x { background: none; border: none; color: #9aa1ad; font-size: 20px; cursor: pointer; }
    .bd { padding: 12px 14px; overflow-y: auto; }
    .status { color: #9aa1ad; } .status.err { color: #ff8080; }
    .meta { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
    .grade { width: 34px; height: 34px; border-radius: 8px; display: inline-flex;
      align-items: center; justify-content: center; font-weight: 800; font-size: 18px; color: #101216; }
    .gA { background: #7ade8a; } .gB { background: #b8e07a; } .gC { background: #f0d060; }
    .gD { background: #f0a050; } .gE { background: #f07070; }
    .badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: #262a33; color: #aeb6c2; }
    .badge.warn { background: #4a3a1a; color: #f0c060; }
    h3 { margin: 12px 0 6px; font-size: 12px; text-transform: uppercase; letter-spacing: .6px; color: #9aa1ad; }
    .tldr { margin: 4px 0; padding-left: 18px; } .tldr li { margin: 3px 0; }
    .card { border: 1px solid #262a33; border-left-width: 3px; border-radius: 8px; padding: 8px 10px; margin: 6px 0; }
    .card.sev-high { border-left-color: #f07070; } .card.sev-medium { border-left-color: #f0d060; }
    .card.sev-low { border-left-color: #4a5160; }
    .card p { margin: 4px 0; color: #c8cdd6; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .sev { font-size: 10px; text-transform: uppercase; color: #9aa1ad; }
    .quotelink, .report { background: none; border: none; color: #7ab8f0; cursor: pointer;
      font-size: 12px; padding: 2px 8px 2px 0; }
    .report { color: #8a919d; } .report:hover { color: #f0a0a0; }
    details { margin-top: 8px; } summary { cursor: pointer; color: #9aa1ad; }
    .none { color: #8a919d; font-size: 12.5px; }
    .disclaimer { margin-top: 14px; padding-top: 8px; border-top: 1px solid #262a33;
      color: #8a919d; font-size: 11.5px; }
  `;
})();
