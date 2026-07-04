// Shared site logic: demo data (real Yoola output), API hookup, panel + directory rendering.
// Set YOOLA_API to the deployed server origin to make the directory live; the
// static demo entries keep the site meaningful on GitHub Pages without it.

const YOOLA_API = "https://yoola-explain.aleksanderbor.ru";

// Real, unedited Yoola output (gemma-4-31b) — Mozilla's ToS and Yoola's own.
const DEMO_ENTRIES = [
  {
    url: "https://www.mozilla.org/en-US/about/legal/terms/mozilla/",
    grade: "C",
    alerts: 6,
    generated_at: "2026-07-04",
    tldr: [
      "Mozilla limits its total liability to $500 and disclaims all warranties, providing services 'as is'.",
      "Users grant Mozilla a worldwide, sublicensable license to use any content they submit.",
      "Mozilla can terminate or suspend accounts at its discretion for various reasons.",
    ],
    top: [
      { title: "Limitation of liability", severity: "high",
        explanation: "Mozilla limits its collective liability to $500 and excludes all indirect, special, incidental, consequential, or exemplary damages.",
        quote: "THE COLLECTIVE LIABILITY OF MOZILLA AND THE INDEMNIFIED PARTIES UNDER THIS AGREEMENT WILL NOT EXCEED $500 (FIVE HUNDRED DOLLARS)." },
      { title: "Unilateral changes to terms", severity: "medium",
        explanation: "Mozilla may update terms at any time, and continued use of the services constitutes acceptance of these changes.",
        quote: "Your continued use of our Communications after the effective date of such changes constitutes your acceptance of such changes." },
      { title: "Account termination & suspension", severity: "medium",
        explanation: "Mozilla may suspend or terminate access at any time for any reason, including commercial viability.",
        quote: "We may suspend or terminate your access to our Communications at any time for any reason…" },
    ],
  },
  {
    url: "https://yoola.example.com/terms",
    grade: "D",
    alerts: 6,
    generated_at: "2026-07-04",
    tldr: [
      "The service provides AI-generated summaries that are explicitly not legal advice and may be inaccurate or incomplete.",
      "Liability is severely limited to a maximum of $10 or the amount paid in the last year.",
      "Users waive the right to participate in class-action lawsuits.",
    ],
    top: [
      { title: "Warranty disclaimer", severity: "high",
        explanation: "The service and all summaries are provided 'as is' with all faults and without warranty of any kind.",
        quote: "THE SERVICE AND ALL SUMMARIES AND OTHER CONTENT ARE PROVIDED STRICTLY ON AN \"AS IS\" AND \"AS AVAILABLE\" BASIS, WITH ALL FAULTS AND WITHOUT WARRANTY OF ANY KIND WHATSOEVER." },
      { title: "Limitation of liability", severity: "high",
        explanation: "Aggregate liability is capped at the greater of amounts paid in twelve months or ten US dollars.",
        quote: "SHALL NOT EXCEED THE GREATER OF (a) THE TOTAL AMOUNT YOU PAID TO YOOLA FOR THE SERVICE IN THE TWELVE (12) MONTHS PRECEDING THE EVENT GIVING RISE TO THE CLAIM, OR (b) TEN UNITED STATES DOLLARS (US $10)." },
      { title: "Arbitration & class-action waiver", severity: "medium",
        explanation: "Disputes must be brought individually; class or representative actions are waived.",
        quote: "ANY PROCEEDING SHALL BE CONDUCTED ONLY ON AN INDIVIDUAL BASIS AND NOT AS A PLAINTIFF OR CLASS MEMBER IN ANY PURPORTED CLASS, COLLECTIVE, OR REPRESENTATIVE ACTION." },
    ],
  },
];

const VERDICT = { A: "Fair terms", B: "Mostly fair", C: "Mixed terms", D: "Harsh terms", E: "Very harsh" };

function el(tag, className, html) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (html != null) node.innerHTML = html;
  return node;
}
function esc(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

/* ---------- directory ---------- */

async function loadEntries() {
  if (YOOLA_API) {
    try {
      const response = await fetch(`${YOOLA_API}/v1/directory?limit=500`);
      if (response.ok) {
        const live = (await response.json()).entries;
        if (live.length) return { entries: live, live: true };
      }
    } catch {
      /* fall through to demo data */
    }
  }
  return { entries: DEMO_ENTRIES, live: false };
}

function renderDirectory(grid, entries, query, grade) {
  grid.innerHTML = "";
  const q = (query || "").trim().toLowerCase();
  const shown = entries.filter(
    (e) => (!q || e.url.toLowerCase().includes(q)) && (!grade || e.grade === grade)
  );
  if (!shown.length) {
    grid.appendChild(
      el("div", "dir-empty",
        q
          ? `Nothing here for “${esc(query)}” yet. Open that site's terms with the Yoola
             extension — your request adds it to this directory for everyone.`
          : `No entries with this grade yet.`)
    );
    return;
  }
  for (const entry of shown) {
    const u = new URL(entry.url);
    const card = el("button", "dir-card", `
      <div class="stamp g-${entry.grade}"><span>${entry.grade}</span></div>
      <div>
        <div class="dir-host">${esc(u.hostname)}</div>
        <div class="dir-meta">${VERDICT[entry.grade]} · ${entry.alerts} alert${entry.alerts === 1 ? "" : "s"}</div>
      </div>`);
    card.addEventListener("click", () => toggleDetail(grid, card, entry));
    grid.appendChild(card);
  }
}

function toggleDetail(grid, card, entry) {
  grid.querySelector(".dir-detail")?.remove();
  const detail = el("div", "dir-detail", `
    <div class="dir-host">${esc(new URL(entry.url).hostname)} — ${VERDICT[entry.grade]}</div>
    <ul>${(entry.tldr || []).map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
    <p class="dir-meta" style="margin-top:12px">
      <a href="${esc(entry.url)}" rel="noopener nofollow">Read the original ↗</a>
      &nbsp;·&nbsp; analyzed ${esc((entry.generated_at || "").slice(0, 10))}
      &nbsp;·&nbsp; full clause-by-clause view in the extension
    </p>`);
  card.after(detail);
}

async function initHome() {
  const grid = document.getElementById("dir-grid");
  const search = document.getElementById("dir-search");
  const note = document.getElementById("dir-note");
  const scale = document.getElementById("scale");

  // The grading scale: legend + directory filter in one.
  let activeGrade = null;
  let entries = [];
  const refresh = () => renderDirectory(grid, entries, search.value, activeGrade);

  const labels = { A: "fair", B: "mostly fair", C: "mixed", D: "harsh", E: "very harsh" };
  for (const grade of ["A", "B", "C", "D", "E"]) {
    const button = el("button", "scale-btn", `
      <span class="stamp g-${grade}"><span>${grade}</span></span><span>${labels[grade]}</span>`);
    button.addEventListener("click", () => {
      activeGrade = activeGrade === grade ? null : grade;
      scale.querySelectorAll(".scale-btn").forEach((b) => b.classList.remove("on"));
      if (activeGrade) button.classList.add("on");
      refresh();
    });
    scale.appendChild(button);
  }

  const loaded = await loadEntries();
  entries = loaded.entries;
  if (!loaded.live) note.textContent = "Sample entries shown — the live directory grows with every summary users request.";
  refresh();
  search.addEventListener("input", refresh);
}
