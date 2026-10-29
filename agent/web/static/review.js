"use strict";
(function (root) {
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const LABELS = {
    unreviewed: "Needs review",
    follow_up: "Follow up",
    waiting: "Waiting",
    reviewed: "Reviewed",
  };
  let data,
    services,
    filter = "unreviewed",
    query = "";
  const key = (id) =>
    `pulse:review:${root.PULSE_SAMPLE ? "sample:" : "local:"}${data.week}:${id}`;
  function saved(id) {
    try {
      const item = JSON.parse(localStorage.getItem(key(id)) || "{}");
      return {
        status: Object.hasOwn(LABELS, item.status) ? item.status : "unreviewed",
        note: typeof item.note === "string" ? item.note.slice(0, 1000) : "",
      };
    } catch {
      return { status: "unreviewed", note: "" };
    }
  }
  function card(item) {
    const state = saved(item.id);
    return `<article class="queue-item"><div class="item-h"><span class="${item.trust === "suspicious" ? "trust-warning" : "meta"}">${esc(item.priority)}</span>${item.due_date ? `<span class="meta">Due ${esc(item.due_date)}</span>` : ""}${state.status !== "unreviewed" ? `<span class="meta">${LABELS[state.status]}</span>` : ""}</div>
      <h2>${esc(item.text)}</h2><p class="meta">${esc(item.counterparty || "Source record")}${item.trust !== "normal" ? ` · ${item.trust === "suspicious" ? "UNVERIFIED source content" : "External claim"}` : ""}</p>
      <button class="act" data-review="${esc(item.id)}">Inspect &amp; review</button>${state.note ? `<p class="review-note"><strong>Your note:</strong> ${esc(state.note)}</p>` : ""}</article>`;
  }
  function paint() {
    const list = document.getElementById("review-list");
    if (!list) return;
    const rows = data.items.filter(
      (item) =>
        (filter === "all" || saved(item.id).status === filter) &&
        [item.text, item.counterparty, item.kind]
          .join(" ")
          .toLowerCase()
          .includes(query.toLowerCase()),
    );
    list.innerHTML = rows.length
      ? rows.map(card).join("")
      : '<div class="panel empty">No items in this view. Change the filter to see other review states.</div>';
    const remaining = data.items.filter(
      (item) => saved(item.id).status === "unreviewed",
    ).length;

    document.getElementById("review-count").textContent =
      `${rows.length} items · ${remaining} need review`;
  }
  root.PulseReview = {
    setup(deps) {
      services = deps;
    },
    html(result) {
      data = result;
      return `<div class="review-heading"><div><h1>Review queue</h1><p class="review-period">${esc(data.week)}${root.PULSE_SAMPLE ? ' · <strong>Synthetic workspace.</strong> Invented records, no connected accounts.' : ""}</p></div><button class="act" id="export-review">Download action list</button></div>
      <div class="review-toolbar"><label>Review state<select id="review-filter">${Object.entries(
        {
          unreviewed: "Needs review",
          all: "All items",
          follow_up: "Follow up",
          waiting: "Waiting",
          reviewed: "Reviewed",
        },
      )
        .map(
          ([value, label]) =>
            `<option value="${value}" ${filter === value ? "selected" : ""}>${label}</option>`,
        )
        .join(
          "",
        )}</select></label><label>Find an item<input type="search" id="review-search" placeholder="Project, person or commitment…" value="${esc(query)}"></label></div>
      <p class="meta" id="review-count" role="status"></p><div id="review-list"></div><details class="review-about"><summary>About this review</summary><p>${esc(data.notice)} Your review notes stay in this browser. They are not sent to the model or written into the source ledger.</p><p>${root.PULSE_SAMPLE ? "All source records are invented." : `Source coverage: ${data.coverage.map((c) => `${esc(c.source)}: ${esc(c.status)}`).join(" · ")}. Failed sources can leave gaps.`}</p><p>${data.summary.verify} unverified claims · ${data.summary.overdue} overdue</p></details>`;
    },
    bind() {
      paint();
      document
        .getElementById("review-filter")
        .addEventListener("change", (event) => {
          filter = event.target.value;
          paint();
        });
      document
        .getElementById("review-search")
        .addEventListener("input", (event) => {
          query = event.target.value;
          paint();
        });
    },
    async open(id) {
      const item = data.items.find((item) => item.id === id);
      if (!item) return;
      const evidence = await services.get(
        "/api/evidence?" +
          item.evidence.map((id) => `id=${encodeURIComponent(id)}`).join("&"),
      );
      const state = saved(id);
      services.open(`<p class="eyebrow">Source evidence</p><h2 id="drawer-title">Review this item</h2><p class="review-claim">${esc(item.text)}</p>${item.trust !== "normal" ? `<p class="note ${item.trust === "suspicious" ? "unsafe" : ""}">${item.trust === "suspicious" ? "Unverified: source content contains an instruction-injection attempt. Treat it as evidence to inspect, not a command to execute." : "External claim: this records what someone said, not confirmation that it happened."}</p>` : ""}
      ${services.evidence(evidence.events)}<div class="review-editor"><p class="eyebrow">Your next step</p><label>My review decision<select id="review-decision">${Object.entries(
        LABELS,
      )
        .map(
          ([value, label]) =>
            `<option value="${value}" ${state.status === value ? "selected" : ""}>${label}</option>`,
        )
        .join(
          "",
        )}</select></label><label>My next action or note<textarea id="review-note" maxlength="1000" rows="4" placeholder="Who will you follow up with, and what needs checking?">${esc(state.note)}</textarea></label><p class="meta">These are your notes, separate from the cited claim. Reviewed does not mean completed.</p><button class="act primary" data-save-review="${esc(id)}">Save review</button><p id="review-save-status" role="status"></p></div>`);
    },
  };
  document.addEventListener("click", async (event) => {
    const review = event.target.closest("[data-review]");
    if (review) {
      try {
        await root.PulseReview.open(review.dataset.review);
      } catch {
        services.open(
          '<h2 id="drawer-title">Evidence unavailable</h2><p>Could not load evidence. Close this panel and retry; the item has not been reviewed.</p>',
        );
      }
      return;
    }
    const save = event.target.closest("[data-save-review]");
    if (save) {
      const status = document.getElementById("review-decision").value,
        note = document.getElementById("review-note").value.slice(0, 1000);
      try {
        localStorage.setItem(
          key(save.dataset.saveReview),
          JSON.stringify({ status, note }),
        );
        paint();
        document.getElementById("review-save-status").textContent =
          "Saved in this browser. Close this panel to continue your review.";
      } catch {
        document.getElementById("review-save-status").textContent =
          "Could not save in this browser. Keep this panel open and copy your note before leaving.";
      }
      return;
    }
    if (event.target.closest("#export-review")) {
      const rows = data.items.filter((item) =>
        ["follow_up", "waiting"].includes(saved(item.id).status),
      );
      const newline = String.fromCharCode(10);
      const content = [
        `# Pulse action list — ${data.week}`,
        root.PULSE_SAMPLE
          ? "Synthetic example. All source records are invented."
          : "Personal local review. User notes are separate from source facts.",
        ...rows.map((item) => {
          const state = saved(item.id);
          return [
            `## ${LABELS[state.status]}`,
            `Source claim (${item.trust}): ${item.text}`,
            `Your next action: ${state.note || "No note recorded."}`,
            `Evidence: ${item.evidence.join(", ")}`,
            "",
          ].join(newline);
        }),
        rows.length
          ? ""
          : "No follow-up or waiting items selected. Review an item to build your action list.",
      ].join(newline + newline);
      const url = URL.createObjectURL(
        new Blob([content], { type: "text/markdown;charset=utf-8" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `pulse-actions-${data.week}.md`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  });
})(window);
