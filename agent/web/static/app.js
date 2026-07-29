"use strict";

// Everything rendered here originates in captured third-party content, so
// every value goes through esc() before it reaches innerHTML.
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const main = document.getElementById("main");
const drawer = document.getElementById("drawer");
const drawerBody = document.getElementById("drawerBody");

async function get(path) {
  const res = await fetch(path);
  return res.json();
}
async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return res.json();
}

const TRUST = {
  suspicious: '<span class="tag bad">unverified source</span>',
  external: '<span class="tag">external claim</span>',
};
const KINDS = {
  decision: "Decision",
  commitment_by_user: "You promised",
  commitment_by_other: "Promised to you",
  deadline: "Deadline",
  blocker: "Blocker",
  question: "Open question",
};

function citeButton(ids) {
  if (!ids || !ids.length) return "";
  return `<button class="cite" data-ev="${esc(ids.join(","))}">evidence ${ids.length}</button>`;
}

function itemRow(it) {
  const due = it.due_date
    ? `<span class="tag ${it.deadline_state === "overdue" ? "bad" : it.deadline_state ? "warn" : ""}">`
      + `${it.deadline_state === "overdue" ? "overdue " + it.days + "d" : "due " + esc(it.due_date)}</span>`
    : "";
  return `<div class="item">
    <div class="item-h">
      <span class="tag acc">${esc(KINDS[it.kind] || it.kind)}</span>
      ${it.counterparty ? `<span class="meta">${esc(it.counterparty)}</span>` : ""}
      ${due}${TRUST[it.trust] || ""}
      ${it.confidence ? `<span class="meta">confidence ${esc(it.confidence)}</span>` : ""}
    </div>
    <div class="item-t">${esc(it.text)}</div>
    <div class="item-h" style="margin-top:5px">
      <span class="meta">open since ${esc(it.first_week)}</span>${citeButton(it.evidence)}
    </div>
  </div>`;
}

const views = {
  async briefing() {
    const data = await get("/api/briefing");
    if (!data.content) {
      const other = (data.available || []).map((w) =>
        `<button class="act" data-week="${esc(w)}">${esc(w)}</button>`).join(" ");
      return `<h1>Briefing</h1><div class="sub">${esc(data.week)}</div>
        <div class="panel"><p class="empty">No briefing generated for this week yet.</p>
        <p style="margin-top:8px;font-size:12.5px">Run <code>python agent/run_pulse.py --config config/pulse_config.yaml</code>,
        or <code>--demo</code> for synthetic data.</p>
        ${other ? `<div style="margin-top:12px">${other}</div>` : ""}</div>`;
    }
    return `<h1>Briefing</h1><div class="sub">${esc(data.week)} · generated ${esc((data.generated_at || "").slice(0, 16))}</div>
      <pre class="brief">${esc(data.content)}</pre>`;
  },

  async items() {
    const data = await get("/api/items");
    const open = data.items || [];
    const stale = data.stale || [];
    const overdue = open.filter((i) => i.deadline_state === "overdue");
    return `<h1>Commitments &amp; decisions</h1>
      <div class="sub">${open.length} open · ${overdue.length} overdue · ${stale.length} untouched 2+ weeks</div>
      <div class="panel"><h2>Open</h2>${open.length ? open.map(itemRow).join("") : '<p class="empty">Nothing open in evidence.</p>'}</div>
      <div class="panel"><h2>Going stale</h2>${stale.length ? stale.map(itemRow).join("") : '<p class="empty">Nothing stale.</p>'}</div>`;
  },

  async workstreams() {
    const data = await get("/api/workstreams");
    const list = data.workstreams || [];
    if (!list.length) return `<h1>Workstreams</h1><div class="panel"><p class="empty">No workstreams yet — run a sync or the demo.</p></div>`;
    return `<h1>Workstreams</h1><div class="sub">Grouped across Gmail, GitHub, and Notion · window ${esc(data.weeks[0])}–${esc(data.weeks.at(-1))}</div>
      <div class="grid">${list.map((w) => `<div class="card" data-ws="${esc(w.id)}">
        <div class="n">${esc(w.name)}</div>
        <div class="meta">${esc(w.kind)} · ${w.events_this_week} this week · ${w.events_window} in window</div>
        ${w.trend ? `<div style="margin-top:6px"><span class="tag ${w.trend === "stalled" ? "bad" : w.trend === "rising" ? "ok" : ""}">${esc(w.trend)}</span></div>` : ""}
      </div>`).join("")}</div>`;
  },

  async workstream(id) {
    const data = await get("/api/workstream?id=" + encodeURIComponent(id));
    if (data.error) return `<h1>Not found</h1>`;
    const ws = data.workstream;
    return `<h1>${esc(ws.name)}</h1><div class="sub">${esc(ws.kind)} · ${esc(ws.id)}</div>
      <button class="act" data-v="workstreams">← all workstreams</button>
      <div class="panel" style="margin-top:14px"><h2>Items</h2>
        ${data.items.length ? data.items.map(itemRow).join("") : '<p class="empty">No items extracted for this workstream.</p>'}</div>
      <div class="panel"><h2>Recent evidence</h2>
        ${data.events.slice(0, 40).map((e) => `<div class="item">
          <div class="item-h"><span class="tag">${esc(e.source)}</span>
            <span class="meta">${esc((e.occurred_at || "").slice(0, 16))}</span>
            ${e.sensitivity !== "normal" ? TRUST[e.sensitivity] || "" : ""}</div>
          <div class="item-t">${esc(e.title)}</div>
          ${e.url ? `<a class="meta" href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.url)}</a>` : ""}
        </div>`).join("")}</div>`;
  },

  async ask() {
    return `<h1>Ask Pulse</h1>
      <div class="sub">Answers come from your local ledger, with the records behind them.</div>
      <div class="panel">
        <input type="text" id="q" placeholder="What did I promise Sarah?  ·  What changed in OmanX this week?" />
        <div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap">
          ${["What commitments are still open?", "Which projects are losing momentum?",
             "What changed in OmanX this week?",
             "What was discussed in email but never reflected in GitHub or Notion?"]
            .map((s) => `<button class="act sug">${esc(s)}</button>`).join("")}
        </div>
      </div>
      <div id="answer"></div>`;
  },

  async connectors() {
    const s = await get("/api/status");
    const rows = s.connectors.map((c) => `<div class="row">
      <div><strong>${esc(c.source)}</strong>
        <div class="meta">${c.last_success_at ? "last success " + esc(c.last_success_at.slice(0, 16)) : "never synced"}</div>
        ${c.last_error ? `<div class="meta" style="color:var(--bad)">${esc(c.last_error)}</div>` : ""}</div>
      <div style="text-align:right">
        <span class="tag ${c.last_status === "ok" ? "ok" : c.last_status === "error" ? "bad" : ""}">${esc(c.last_status)}</span>
        <div class="meta" style="margin-top:4px">key: ${esc(c.credential.masked)} (${esc(c.credential.origin)})</div>
        <button class="act test" data-src="${esc(c.source)}" style="margin-top:6px">Test connection</button>
      </div></div>`).join("");
    return `<h1>Connectors</h1><div class="sub">Week ${esc(s.week)} · ${s.counts.workstreams} workstreams · ${s.counts.open_items} open items</div>
      <div class="panel">${rows}</div>
      <div class="panel"><h2>Analysis model</h2>
        <div class="row"><div>Anthropic API key<div class="meta">optional — Pulse produces evidence-backed briefings without it</div></div>
        <div style="text-align:right"><span class="tag ${s.analysis.configured ? "ok" : ""}">${s.analysis.configured ? "configured" : "not set"}</span>
        <div class="meta" style="margin-top:4px">${esc(s.analysis.masked)} (${esc(s.analysis.origin)})</div>
        <button class="act test" data-src="anthropic" style="margin-top:6px">Test connection</button></div></div></div>
      <div id="testout"></div>`;
  },

  async sync() {
    const data = await get("/api/sync");
    const rows = (data.sync || []).map((s) => `<div class="row">
      <div><strong>${esc(s.source)}</strong><div class="meta">cursor ${esc((s.cursor_ts || "—").slice(0, 16))}</div></div>
      <div style="text-align:right"><span class="tag ${s.last_status === "ok" ? "ok" : s.last_status === "error" ? "bad" : ""}">${esc(s.last_status)}</span>
      ${s.last_error ? `<div class="meta" style="color:var(--bad)">${esc(s.last_error)}</div>` : ""}</div></div>`).join("");
    const sugg = (data.suggestions || []).map((s) => `<div class="item">
      <div class="item-t">${esc(s.member_type)} <code>${esc(s.member_key)}</code> → ${esc(s.workstream_id)}</div>
      <div class="item-h"><span class="meta">confidence ${esc(s.confidence)}</span>${citeButton(s.evidence)}</div></div>`).join("");
    return `<h1>Sync history</h1><div class="sub">Per-connector cursors and errors</div>
      <div class="panel">${rows || '<p class="empty">No syncs recorded yet.</p>'}</div>
      <div class="panel"><h2>Ambiguous links awaiting review</h2>
        ${sugg || '<p class="empty">Nothing ambiguous — all links were resolved deterministically.</p>'}</div>`;
  },

  async settings() {
    return `<h1>Settings &amp; data</h1>
      <div class="note"><strong>Everything stays on this machine.</strong> Events, items, briefings, and
      sync state live in a local SQLite file. Nothing is uploaded. Credentials come from your environment
      or OS keychain and are never written to that database, the briefing, or the logs. When an
      Anthropic key is configured, the analysis step sends event titles and short snippets — never
      message bodies — to the API.</div>
      <div class="panel"><h2>Your data</h2>
        <div class="row"><div>Export everything<div class="meta">Full JSON — events, items, history, briefings</div></div>
          <div><a class="act" href="/api/export" download>Download</a></div></div>
        <div class="row"><div>Delete everything<div class="meta">Irreversible. Removes all local Pulse data.</div></div>
          <div><button class="act danger" id="purge">Delete all data</button></div></div>
      </div>
      <div class="panel"><h2>Scheduling</h2>
        <p style="font-size:12.5px;color:var(--muted)">Weekly runs are handled by Task Scheduler via
        <code>setup_scheduler.ps1</code>. Retention is manual by design — Pulse keeps history until you delete it.</p></div>`;
  },
};

async function render(view, arg) {
  document.querySelectorAll("nav button").forEach((b) =>
    b.classList.toggle("on", b.dataset.v === view));
  main.innerHTML = '<p class="empty">Loading…</p>';
  try {
    main.innerHTML = await views[view](arg);
  } catch (err) {
    main.innerHTML = `<div class="panel"><p class="empty">Could not load: ${esc(err.message)}</p></div>`;
  }
}

document.addEventListener("click", async (e) => {
  const nav = e.target.closest("[data-v]");
  if (nav) return render(nav.dataset.v);

  const ws = e.target.closest("[data-ws]");
  if (ws) return render("workstream", ws.dataset.ws);

  const cite = e.target.closest("[data-ev]");
  if (cite) {
    const ids = cite.dataset.ev.split(",");
    const data = await get("/api/evidence?" + ids.map((i) => "id=" + encodeURIComponent(i)).join("&"));
    drawerBody.innerHTML = (data.events || []).map((ev) => `<div class="ev">
      <div class="item-h"><span class="tag">${esc(ev.source)}</span>
        <span class="meta">${esc((ev.occurred_at || "").slice(0, 16))}</span></div>
      <div class="item-t">${esc(ev.title)}</div>
      ${ev.actor ? `<div class="meta">${esc(ev.actor)}</div>` : ""}
      <div class="meta"><code>${esc(ev.id)}</code></div>
      ${ev.url ? `<a href="${esc(ev.url)}" target="_blank" rel="noopener">${esc(ev.url)}</a>` : ""}
    </div>`).join("") || '<p class="empty">Evidence not found in the ledger.</p>';
    drawer.classList.add("open");
    return;
  }

  if (e.target.id === "drawerClose") return drawer.classList.remove("open");

  const week = e.target.closest("[data-week]");
  if (week) {
    const data = await get("/api/briefing?week=" + encodeURIComponent(week.dataset.week));
    main.innerHTML = `<h1>Briefing</h1><div class="sub">${esc(data.week)}</div><pre class="brief">${esc(data.content || "")}</pre>`;
    return;
  }

  const test = e.target.closest(".test");
  if (test) {
    test.textContent = "Testing…";
    const result = await post("/api/test-connector", { source: test.dataset.src });
    const out = document.getElementById("testout");
    if (out) out.innerHTML = `<div class="panel"><span class="tag ${result.ok ? "ok" : "bad"}">${result.ok ? "connected" : "failed"}</span>
      <span class="meta" style="margin-left:8px">${esc(result.source)}: ${esc(result.detail)}</span></div>`;
    test.textContent = "Test connection";
    return;
  }

  if (e.target.id === "purge") {
    if (!confirm("Delete all local Pulse data? This cannot be undone.")) return;
    await post("/api/purge", { confirm: "DELETE" });
    render("settings");
    return;
  }

  const sug = e.target.closest(".sug");
  if (sug) {
    document.getElementById("q").value = sug.textContent;
    return submitAsk();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.id === "q") submitAsk();
  if (e.key === "Escape") drawer.classList.remove("open");
});

async function submitAsk() {
  const box = document.getElementById("q");
  const out = document.getElementById("answer");
  if (!box || !box.value.trim()) return;
  out.innerHTML = '<div class="panel"><p class="empty">Searching your ledger…</p></div>';
  const data = await post("/api/ask", { question: box.value.trim() });
  const evidence = (data.evidence || []).map((e) => `<div class="ev">
    <div class="item-h"><span class="tag">${esc(e.source)}</span><span class="meta">${esc((e.occurred_at || "").slice(0, 16))}</span></div>
    <div class="item-t">${esc(e.title)}</div>
    ${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.url)}</a>` : ""}</div>`).join("");
  out.innerHTML = `<div class="panel">
      <div class="item-h" style="margin-bottom:8px">
        <span class="tag ${data.grounded ? "ok" : "warn"}">${data.grounded ? "grounded in evidence" : "no matching evidence"}</span>
        ${data.interpretation ? '<span class="tag warn">model interpretation</span>' : '<span class="tag">computed</span>'}
      </div>
      <div style="white-space:pre-wrap">${esc(data.answer)}</div>
    </div>
    ${evidence ? `<div class="panel"><h2>Evidence</h2>${evidence}</div>` : ""}`;
}

render("briefing");
