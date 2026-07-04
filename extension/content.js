// Yoola content script: the detection tab + the summary "dossier" panel.
// Auto-DETECT, never auto-summarize (Design v4 §5): nothing leaves the page
// until the user acts (tab, popup, or right-click).

(() => {
  if (window.__yoolaLoaded) return;
  window.__yoolaLoaded = true;

  const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 };
  const VERDICT = { A: "Fair terms", B: "Mostly fair", C: "Mixed terms", D: "Harsh terms", E: "Very harsh" };
  let shadow = null;

  yoolaDetect().then((hit) => {
    if (!hit) return;
    chrome.runtime.sendMessage({ type: "detected" });
    mountTab(hit.kind, hit.links);
  });

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "summarize-current") summarize();
    if (msg.type === "summarize-url") summarize({ url: msg.url, remote: true });
  });

  function ui() {
    if (shadow) return shadow;
    const host = document.createElement("div");
    host.id = "yoola-host";
    shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = CSS;
    shadow.appendChild(style);
    document.documentElement.appendChild(host);
    return shadow;
  }

  const TAB_MSG = {
    heuristic: "Terms detected",
    registry: "Summary available",
    links: "Check the terms first?",
  };

  function mountTab(kind, links) {
    const root = ui();
    root.querySelector(".tab")?.remove();
    const tab = document.createElement("button");
    tab.className = "tab";
    tab.innerHTML = `<span class="mark">Yoola</span><span class="tab-msg">${TAB_MSG[kind]}</span>`;
    tab.addEventListener("click", () => {
      tab.remove();
      if (kind === "links" && links.length > 1) showPicker(links);
      else if (kind === "links") summarize({ url: links[0].url, label: links[0].label, remote: true });
      else summarize();
    });
    root.appendChild(tab);
  }

  function openPanel() {
    const root = ui();
    root.querySelector(".panel")?.remove();
    const panel = document.createElement("div");
    panel.className = "panel";
    panel.innerHTML = `
      <header class="hd">
        <span class="mark">Yoola</span>
        <button class="x" title="Close" aria-label="Close">✕</button>
      </header>
      <div class="bd"></div>`;
    panel.querySelector(".x").addEventListener("click", () => panel.remove());
    root.appendChild(panel);
    return panel.querySelector(".bd");
  }

  // The consent-page chooser: this page links to several legal documents;
  // summarize any of them without leaving the page.
  function showPicker(links) {
    const body = openPanel();
    body.innerHTML = `
      <h2>Before you agree</h2>
      <p class="pick-intro">This page asks you to accept legal documents. Pick one to review — you won't leave this page.</p>
      <div class="picks"></div>`;
    const box = body.querySelector(".picks");
    for (const link of links) {
      const button = document.createElement("button");
      button.className = "pick";
      const host = new URL(link.url).hostname;
      button.innerHTML = `<span class="pick-label">${escapeHtml(link.label)}</span><span class="pick-host">${escapeHtml(host)}</span>`;
      button.addEventListener("click", () => summarize({ url: link.url, label: link.label, remote: true }));
      box.appendChild(button);
    }
  }

  // target: {url, label?, remote?} — defaults to the page you're on. `remote`
  // means we're summarizing a LINKED document (v4 A5/link-mode): quotes deep-link
  // to the source instead of highlighting in this page.
  async function summarize(target = { url: location.href, remote: false }) {
    const body = openPanel();
    body.innerHTML = `<div class="loading"><span class="spin"></span>Reading the fine print…</div>`;

    const language = (navigator.language || "en").split("-")[0];
    let reply = await chrome.runtime.sendMessage({ type: "summarize", url: target.url, language });
    if (reply?.needClientContent) {
      if (target.remote) {
        body.innerHTML = `<div class="notice err">That site blocks our reader. Open the document and use Yoola there.</div>`;
        return;
      }
      body.innerHTML = `<div class="loading"><span class="spin"></span>Site blocks our reader — sending the page text…</div>`;
      reply = await chrome.runtime.sendMessage({
        type: "summarize",
        url: target.url,
        language,
        clientContent: yoolaExtractText(),
      });
    }
    if (!reply?.ok) {
      body.innerHTML = `<div class="notice err">${escapeHtml(reply?.detail || "Something went wrong.")}</div>`;
      return;
    }
    render(body, reply.payload, reply.fromL1, target);
  }

  function render(body, s, fromL1, target) {
    const present = s.categories
      .filter((c) => c.status === "present")
      .sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
    const alerts = present.filter((c) => c.severity !== "low");
    const standard = present.filter((c) => c.severity === "low");
    const notAddressed = s.categories.filter((c) => c.status === "not_addressed");
    const docLine = target?.remote
      ? `<div class="doc-line">${escapeHtml(target.label || "Linked document")} · ${escapeHtml(new URL(s.url || target.url).hostname)}</div>`
      : "";

    body.innerHTML = `
      ${docLine}
      ${s.disputed ? `<div class="notice flag">Readers flagged this summary. Weigh it carefully and check the source.</div>` : ""}
      <section class="verdict">
        <div class="stamp g-${s.grade}"><span>${s.grade}</span></div>
        <div class="verdict-txt">
          <div class="verdict-word">${VERDICT[s.grade] || "Reviewed"}</div>
          <div class="verdict-meta">${alerts.length} alert${alerts.length === 1 ? "" : "s"} · ${sourceLabel(s, fromL1)}</div>
        </div>
      </section>
      <section class="alerts"></section>
      <h2>In brief</h2>
      <ul class="tldr">${s.tldr.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>
      <details class="more">
        <summary>All ${s.categories.length} clauses checked</summary>
        <div class="more-body"></div>
      </details>
      <footer class="disc">
        ${s.source_verified === false ? `<span class="chip warn">unverified source</span>` : ""}
        ${escapeHtml(s.disclaimer)}
      </footer>`;

    const ctx = { docVersion: s.doc_version, remote: !!target?.remote, url: s.url || target?.url };
    const alertsBox = body.querySelector(".alerts");
    if (!alerts.length) {
      alertsBox.innerHTML = `<div class="clear">No high-risk clauses stood out. The routine terms are below.</div>`;
    } else {
      alertsBox.innerHTML = `<h2>Watch out for</h2>`;
      for (const c of alerts) alertsBox.appendChild(card(c, ctx));
    }

    const moreBody = body.querySelector(".more-body");
    for (const c of standard) moreBody.appendChild(card(c, ctx, true));
    if (notAddressed.length) {
      const na = document.createElement("p");
      na.className = "na";
      na.innerHTML = `<span>Not addressed</span> ${notAddressed.map((c) => escapeHtml(c.title)).join(" · ")}`;
      moreBody.appendChild(na);
    }
  }

  function card(c, ctx, quiet = false) {
    const el = document.createElement("article");
    el.className = `card sev-${c.severity}${quiet ? " quiet" : ""}`;
    el.innerHTML = `
      <div class="card-hd">
        <span class="dot"></span>
        <span class="card-title">${escapeHtml(c.title)}</span>
        ${c.confidence === "possible" ? `<span class="chip warn">possible</span>` : ""}
      </div>
      ${c.explanation ? `<p class="card-exp">${escapeHtml(c.explanation)}</p>` : ""}
      <div class="quotes"></div>
      <div class="card-ft"></div>`;

    const quotes = el.querySelector(".quotes");
    for (const q of c.quotes || []) {
      const wrap = document.createElement("div");
      wrap.className = "quote";
      const text = document.createElement("blockquote");
      text.textContent = `“${q.text}”`;
      const jump = document.createElement("button");
      jump.className = "jump";
      if (ctx.remote) {
        // Summarizing a linked document: deep-link into the source with a
        // text fragment so the browser highlights the clause on arrival.
        jump.textContent = "read at source ↗";
        jump.addEventListener("click", () => window.open(textFragmentUrl(ctx.url, q.text), "_blank"));
      } else {
        jump.textContent = "find in page ↗";
        jump.addEventListener("click", () => highlight(q.text));
      }
      wrap.append(text, jump);
      quotes.appendChild(wrap);
    }

    const report = document.createElement("button");
    report.className = "report";
    report.textContent = "Report this as wrong";
    report.addEventListener("click", async () => {
      report.disabled = true;
      report.textContent = "Thanks — reported";
      await chrome.runtime.sendMessage({ type: "report", docVersion: ctx.docVersion, category: c.id });
    });
    el.querySelector(".card-ft").appendChild(report);
    return el;
  }

  function textFragmentUrl(url, quote) {
    const words = quote.replace(/\s+/g, " ").trim().split(" ").slice(0, 8).join(" ");
    return `${url}#:~:text=${encodeURIComponent(words)}`;
  }

  function sourceLabel(s, fromL1) {
    if (fromL1) return "cached, offline";
    return { generated: "fresh analysis", translated: "translated", cache: "cached" }[s.source] || "cached";
  }

  // Highlight the quote in the LIVE DOM by searching for its text (offsets are
  // meaningless here — v4 C4), shrinking the needle until window.find hits.
  function highlight(quote) {
    window.getSelection()?.removeAllRanges();
    for (const attempt of [quote, quote.slice(0, 80), quote.slice(0, 50), quote.slice(0, 30)]) {
      const needle = attempt.replace(/\s+/g, " ").trim();
      if (needle.length >= 12 && window.find(needle, false, false, true, false, true, false)) return;
    }
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text ?? "";
    return div.innerHTML;
  }

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .tab, .panel {
      --ink: #171A21; --raised: #1E222B; --line: #2B3140;
      --fg: #ECEEF2; --fg2: #9AA3B2; --fg3: #6B7382;
      --brass: #C9A24B; --brass-hi: #DDB65E;
      --high: #E5654B; --med: #E0A73C; --low: #5B6472;
      font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
      -webkit-font-smoothing: antialiased;
    }
    .serif { font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; }

    /* Detection tab */
    .tab {
      position: fixed; right: 0; bottom: 84px; z-index: 2147483647;
      display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
      background: var(--ink); color: var(--fg); cursor: pointer;
      border: 1px solid var(--line); border-right: none;
      border-radius: 10px 0 0 10px; padding: 9px 14px 9px 13px;
      box-shadow: -6px 6px 22px rgba(0,0,0,.34);
      border-left: 3px solid var(--brass);
      animation: yoola-slide .32s cubic-bezier(.2,.7,.3,1) both;
    }
    .tab:hover { background: var(--raised); }
    .tab .mark {
      font-family: "Iowan Old Style", Palatino, Georgia, serif;
      font-weight: 700; font-size: 15px; letter-spacing: .3px; color: var(--brass);
    }
    .tab-msg { font-size: 11.5px; color: var(--fg2); }

    /* Panel */
    .panel {
      position: fixed; top: 14px; right: 14px; bottom: 14px; width: 396px; max-width: 94vw;
      z-index: 2147483647; background: var(--ink); color: var(--fg);
      border: 1px solid var(--line); border-radius: 16px;
      display: flex; flex-direction: column; overflow: hidden;
      box-shadow: 0 20px 60px rgba(0,0,0,.5);
      animation: yoola-slide .34s cubic-bezier(.2,.7,.3,1) both;
      font-size: 13.5px; line-height: 1.5;
    }
    .hd {
      display: flex; align-items: center; justify-content: space-between;
      padding: 13px 16px; border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(201,162,75,.06), transparent);
    }
    .hd .mark {
      font-family: "Iowan Old Style", Palatino, Georgia, serif;
      font-weight: 700; font-size: 18px; letter-spacing: .4px; color: var(--brass);
    }
    .x { background: none; border: none; color: var(--fg3); font-size: 17px; cursor: pointer; padding: 4px; }
    .x:hover { color: var(--fg); }
    .bd { padding: 16px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--line) transparent; }
    .bd::-webkit-scrollbar { width: 8px; }
    .bd::-webkit-scrollbar-thumb { background: var(--line); border-radius: 8px; }

    .loading { color: var(--fg2); display: flex; align-items: center; gap: 10px; padding: 24px 4px; }
    .spin { width: 15px; height: 15px; border: 2px solid var(--line); border-top-color: var(--brass);
      border-radius: 50%; animation: yoola-spin .8s linear infinite; }
    .doc-line { color: var(--fg2); font-size: 12px; padding: 2px 2px 10px;
      border-bottom: 1px solid var(--line); margin-bottom: 12px; }
    .pick-intro { color: var(--fg2); font-size: 13px; margin: 6px 0 12px; }
    .pick { display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
      width: 100%; text-align: left; background: var(--raised); border: 1px solid var(--line);
      border-left: 3px solid var(--brass); border-radius: 10px; padding: 11px 13px;
      margin: 8px 0; cursor: pointer; color: var(--fg); }
    .pick:hover { background: #232834; }
    .pick-label { font-weight: 600; font-size: 13.5px; }
    .pick-host { color: var(--fg3); font-size: 11.5px; }
    .notice { border-radius: 10px; padding: 11px 13px; font-size: 13px; margin-bottom: 4px; }
    .notice.err { background: rgba(229,101,75,.12); color: #F0A594; border: 1px solid rgba(229,101,75,.3); }
    .notice.flag { background: rgba(224,167,60,.1); color: #ECC578; border: 1px solid rgba(224,167,60,.28); margin-bottom: 14px; }

    /* Verdict stamp — the signature */
    .verdict { display: flex; align-items: center; gap: 16px; padding: 6px 2px 18px; }
    .stamp {
      flex: none; width: 74px; height: 74px; border-radius: 50%;
      border: 2.5px solid currentColor; display: grid; place-items: center;
      position: relative; transform: rotate(-5deg);
      animation: yoola-stamp .4s cubic-bezier(.2,1.5,.4,1) .1s both;
    }
    .stamp::before { content: ""; position: absolute; inset: 6px; border: 1px solid currentColor; border-radius: 50%; opacity: .45; }
    .stamp span {
      font-family: "Iowan Old Style", Palatino, Georgia, serif;
      font-weight: 700; font-size: 38px; line-height: 1;
    }
    .g-A { color: #5FB98E; } .g-B { color: #8FBE6A; } .g-C { color: #E0A73C; }
    .g-D { color: #E58B4B; } .g-E { color: #E5654B; }
    .verdict-word { font-family: "Iowan Old Style", Palatino, Georgia, serif; font-size: 21px; color: var(--fg); }
    .verdict-meta { font-size: 12px; color: var(--fg2); margin-top: 3px; }

    h2 {
      font-size: 11px; text-transform: uppercase; letter-spacing: 1.4px;
      color: var(--fg3); margin: 18px 0 8px; font-weight: 600;
    }
    .clear { color: var(--fg2); font-size: 13px; padding: 2px 0 4px; }

    /* Clause cards */
    .card {
      background: var(--raised); border: 1px solid var(--line);
      border-left: 3px solid var(--low); border-radius: 10px; padding: 11px 13px; margin: 8px 0;
    }
    .card.sev-high { border-left-color: var(--high); }
    .card.sev-medium { border-left-color: var(--med); }
    .card.quiet { background: transparent; padding: 9px 13px; }
    .card-hd { display: flex; align-items: center; gap: 8px; }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--low); flex: none; }
    .sev-high .dot { background: var(--high); } .sev-medium .dot { background: var(--med); }
    .card-title { font-weight: 600; font-size: 13.5px; }
    .card-exp { margin: 7px 0 0; color: #C5CBD5; }
    .quote { margin-top: 9px; }
    .quote blockquote {
      margin: 0; padding: 6px 0 6px 11px; border-left: 2px solid var(--brass);
      font-family: "Iowan Old Style", Palatino, Georgia, serif; font-style: italic;
      color: #CBD1DB; font-size: 12.5px; line-height: 1.45;
    }
    .jump { background: none; border: none; color: var(--brass); cursor: pointer; font-size: 11.5px; padding: 3px 0; }
    .jump:hover { color: var(--brass-hi); }
    .card-ft { margin-top: 8px; }
    .report { background: none; border: none; color: var(--fg3); cursor: pointer; font-size: 11.5px; padding: 0; }
    .report:hover { color: #F0A594; }
    .report:disabled { color: var(--fg3); cursor: default; }

    .chip { font-size: 10px; padding: 2px 7px; border-radius: 999px; margin-left: auto; white-space: nowrap; }
    .chip.warn { background: rgba(224,167,60,.16); color: #ECC578; }

    .tldr { margin: 4px 0; padding-left: 18px; }
    .tldr li { margin: 5px 0; color: #C5CBD5; }
    .more { margin-top: 16px; border-top: 1px solid var(--line); padding-top: 10px; }
    .more summary { cursor: pointer; color: var(--fg2); font-size: 12.5px; list-style: none; }
    .more summary::-webkit-details-marker { display: none; }
    .more summary::before { content: "⌄ "; color: var(--brass); }
    .na { color: var(--fg3); font-size: 12px; margin: 10px 0 2px; line-height: 1.5; }
    .na span { color: var(--fg2); font-weight: 600; }

    .disc {
      margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--line);
      color: var(--fg3); font-size: 11px; line-height: 1.5;
    }
    .disc .chip { margin: 0 6px 0 0; }

    @keyframes yoola-slide { from { opacity: 0; transform: translateX(24px); } to { opacity: 1; transform: none; } }
    @keyframes yoola-spin { to { transform: rotate(360deg); } }
    @keyframes yoola-stamp { from { opacity: 0; transform: rotate(-14deg) scale(1.4); } to { opacity: 1; transform: rotate(-5deg) scale(1); } }
    @media (prefers-reduced-motion: reduce) {
      .tab, .panel, .stamp, .spin { animation: none; }
    }
  `;
})();
