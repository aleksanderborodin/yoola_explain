# Yoola user guide

Yoola gives you a second opinion on the fine print. It watches for legal
documents — terms of service, privacy policies, EULAs — and, only when you ask,
shows a graded checklist: the alarming clauses first, each backed by a verbatim
quote you can jump to in the original.

## Install (developer build)

1. Run the server: `cd server && uv sync && cp env.example .env` (add your key),
   then `uv run uvicorn --factory yoola.app:create_app --port 8000`.
2. Open `chrome://extensions`, enable Developer mode, **Load unpacked**, pick
   the `extension/` folder.

## Three ways to summarize

- **The tab.** When a page is detected, a quiet "Yoola" tab appears at the
  bottom-right. On a terms page it says *Terms detected*; on a page another
  user already added it says *Summary available*; on a **signup or checkout
  page that links to legal documents** it says *Check the terms first?* — click
  it and Yoola summarizes the linked Terms/Privacy documents **without you
  leaving the page** (if there are several, you pick from a list).
- **Right-click.** *Summarize this page with Yoola* on any page, or right-click
  a "Terms"/"Privacy" **link** and choose *Summarize linked document with
  Yoola* — again, no navigation needed.
- **The toolbar popup.** *Summarize this page*, for anything the detector missed.

Detection is automatic; summarizing never is. Nothing about a page leaves your
browser until you click.

## Reading the panel

- **The stamp** is the overall verdict, A (fair) to E (very harsh), computed
  from how many high/medium-severity clauses were found.
- **Watch out for** lists the clauses that deserve attention, worst first. Each
  card explains the clause in plain language and quotes the exact source text —
  *find in page* highlights it right there (or *read at source* opens the
  original with the clause highlighted, when you summarized a linked document).
- **possible** on a clause means Yoola could not fully verify it against the
  source — treat it as a lead, not a fact.
- **disputed** at the top means other readers flagged this summary as
  inaccurate. It is still shown, with that warning, until reviewed.
- **unverified source** means the site blocked our server and the summary was
  built from text a browser submitted — it is never shared with other users
  until the server can verify it.
- **Report this as wrong** on any clause feeds the review queue. Enough
  distinct reporters mark the summary disputed for everyone.

## What Yoola sends and stores

The extension sends only the **URL** of the legal page you asked about — the
server fetches the public document itself. Your browsing history is never
collected; detection (including the "summary available" check) happens entirely
on your machine. Only if a site blocks our server does the extension offer to
send the page text you're looking at, and that result is quarantined.

---

## Yoola, explained by Yoola

We ran Yoola on **our own [Terms of Service](legal/terms-of-service.md)** — the
long, deliberately lawyer-grade document that governs this very tool. This is
the actual, unedited output (generated 2026-07-04, `gemma-4-31b`):

> ### Stamp: **D — Harsh terms**
>
> **In brief**
> - The service provides AI-generated summaries that are explicitly not legal advice and may be inaccurate or incomplete.
> - Liability is severely limited to a maximum of $10 or the amount paid in the last year.
> - Users waive the right to participate in class-action lawsuits.
> - Yoola can change terms unilaterally and terminate user access at any time without notice.
> - The service is restricted to users aged 16 and older.
>
> **Watch out for**
> - **Limitation of liability** · high · verified — *"IN NO EVENT SHALL YOOLA … BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, EXEMPLARY, OR PUNITIVE DAMAGES …"*
> - **Warranty disclaimer** · high · verified — *"THE SERVICE AND ALL SUMMARIES AND OTHER CONTENT ARE PROVIDED STRICTLY ON AN 'AS IS' AND 'AS AVAILABLE' BASIS, WITH ALL FAULTS AND WITHOUT WARRANTY OF ANY KIND WHATSOEVER."*
> - **Arbitration & class-action waiver** · medium · verified — *"YOU AGREE THAT ANY PROCEEDING SHALL BE CONDUCTED ONLY ON AN INDIVIDUAL BASIS AND NOT AS A PLAINTIFF OR CLASS MEMBER IN ANY PURPORTED CLASS, COLLECTIVE, OR REPRESENTATIVE ACTION."*
> - **Unilateral changes** · medium · verified — *"We reserve the right, at our sole and absolute discretion, to modify, amend, supplement, or replace these Terms at any time …"*
> - **Termination** · medium · verified — *"We reserve the right to suspend, restrict, throttle, or permanently terminate access to the Service … for any reason or no reason …"*
> - Also found: governing law & venue (medium), feedback license (low), 16+ age limit (low).

**Why show you this?** Because it's the point of the product. Our terms grade a
**D** — like most software terms, they protect the operator: no warranties, a
$10 liability cap, no class actions. The difference is that *we're the ones
telling you*, in plain language, with the exact clauses quoted — before you
agree. That's what Yoola does for every other agreement you meet. Read the
[full Terms](legal/terms-of-service.md); the summary above is, as always, not
legal advice.
