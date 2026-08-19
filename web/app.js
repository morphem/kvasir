/* Kvasir front end: one fetch of /api/view, everything below is rendering.
   No framework and no chart library on purpose — the whole page is one file the browser
   parses in a blink, and the SVG here is simpler than the config a chart library would need. */

const TIER_STORAGE_KEY = "kvasir.tier";
const state = { view: null, showAll: false, tier: null };

/* The tier is a view setting, not a user account: it lives in localStorage, survives every
   reload and deploy, and falls back to the tier the server nominates. */
function storedTier() {
  try {
    return localStorage.getItem(TIER_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeTier(id) {
  try {
    localStorage.setItem(TIER_STORAGE_KEY, id);
  } catch {
    /* private browsing: the switch still works, it just forgets between visits */
  }
}

function plan() {
  const plans = (state.view && state.view.plans) || {};
  return plans[state.tier] || Object.values(plans)[0] || null;
}

const $ = (sel) => document.querySelector(sel);
const usd = (value) =>
  value === null || value === undefined ? "—" : `$${value < 1 ? value.toFixed(2) : value.toFixed(2)}`;
const pct = (value) => (value === null || value === undefined ? "—" : `${value.toFixed(1)}%`);
const num = (value) => (value === null || value === undefined ? "—" : value.toLocaleString("en-US"));
const credits = (value) =>
  value === null || value === undefined ? "—" : Math.round(value).toLocaleString("en-US");

function ago(iso) {
  if (!iso) return "no data";
  const then = new Date(iso);
  const minutes = Math.round((Date.now() - then.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

function until(iso) {
  if (!iso) return null;
  const minutes = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  if (minutes <= 0) return "due now";
  if (minutes < 60) return `next in ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `next in ${hours} h ${rest} min` : `next in ${hours} h`;
}

function tag(html) {
  const wrapper = document.createElement("template");
  wrapper.innerHTML = html.trim();
  return wrapper.content.firstElementChild;
}

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

/* ---------- freshness strip ---------- */

function renderFreshness(sources) {
  const box = $("#freshness");
  box.innerHTML = "";
  Object.entries(sources).forEach(([id, source]) => {
    const failing = Boolean(source.last_error);
    const overdue =
      source.last_run &&
      (Date.now() - new Date(source.last_run).getTime()) / 60000 > source.interval_minutes * 2.5;
    const dot = failing ? "bad" : overdue ? "stale" : "";
    const every =
      source.interval_minutes >= 60
        ? `every ${Math.round(source.interval_minutes / 60)} h`
        : `every ${source.interval_minutes} min`;
    const due = until(source.next_run) || every;
    box.append(
      tag(`<a class="chip" href="${escapeHtml(source.url)}" target="_blank" rel="noopener">
             <i class="dot ${dot}"></i>${escapeHtml(source.label)}
             <b class="dim" style="font-weight:400">${escapeHtml(ago(source.captured_at))} · ${escapeHtml(due)}</b>
           </a>`)
    );
  });
}

/* ---------- tier switch ---------- */

function renderTierTabs(view) {
  const tabs = $("#tier-tabs");
  tabs.innerHTML = "";
  (view.budget_tiers || []).forEach((tier) => {
    const tierPlan = view.plans[tier.id] || {};
    const active = tier.id === state.tier;
    const button = tag(`<button class="tier-tab" role="tab" aria-selected="${active}">
      <b>${escapeHtml(tier.name)}</b>
      <span>${Math.round(tier.credits / 1000)}K credits · $${num(tierPlan.usd)}</span>
    </button>`);
    button.addEventListener("click", () => {
      state.tier = tier.id;
      storeTier(tier.id);
      renderAll();
    });
    tabs.append(button);
  });

  const current = plan();
  const quote = view.credit_usd_verified
    ? `1 AI credit = $${view.credit_usd.toFixed(2)}, taken from GitHub's own pricing page`
    : `1 AI credit assumed at $${view.credit_usd.toFixed(2)} — the rate could not be read from the docs today`;
  $("#tier-note").textContent = current
    ? `Showing what ${current.name} affords: ${num(current.credits)} credits a month, about $${num(current.usd)}. ${quote}.`
    : quote;
}

/* ---------- verdict cards ---------- */

function driftBadge(drift) {
  if (!drift || drift.score === null) return '<span class="badge">not on AI Stupid Level</span>';
  const arrow = drift.trend === "up" ? "↑" : drift.trend === "down" ? "↓" : "→";
  const cls = drift.trend === "down" || drift.status === "critical" ? "bad" : drift.status === "warning" ? "warn" : "ok";
  return `<span class="badge ${cls}">drift ${Math.round(drift.score)} ${arrow}</span>`;
}

function copilotBadge(copilot) {
  if (!copilot) return '<span class="badge warn">not in Copilot</span>';
  return `<span class="badge ok">Copilot · $${copilot.input_usd}/$${copilot.output_usd} per 1M</span>`;
}

function renderVerdicts(view) {
  const box = $("#verdicts");
  const current = plan();
  box.innerHTML = "";
  view.tiers.forEach((role) => {
    const slot = current && current.roles ? current.roles[role.id] : null;
    if (!slot) return;
    const pick = slot.pick;
    if (!pick) {
      box.append(
        tag(`<article class="card ${role.id}">
          <div class="role-band">
            <span class="role-name">${escapeHtml(role.name)}</span>
            <span class="role-line">${escapeHtml(role.role)}</span>
          </div>
          <div class="pick-name dim">Nothing fits</div>
          <p class="why">${escapeHtml(slot.why || "")}</p>
        </article>`)
      );
      return;
    }
    const effort =
      pick.effort === "default" ? "" : `<em class="pick-effort">${escapeHtml(pick.effort_label)}</em>`;
    const notes = [];
    if (slot.downgraded_from) {
      notes.push(`Best regardless of budget: ${slot.downgraded_from}. This tier does not reach it.`);
    }
    if (slot.same_as) {
      notes.push(`Same model as the ${slot.same_as} at this tier — one answer, not two.`);
    }
    box.append(
      tag(`<article class="card ${role.id}">
        <div class="role-band">
          <span class="role-name">${escapeHtml(role.name)}</span>
          <span class="role-line">${escapeHtml(role.role)}</span>
        </div>
        <div class="pick-name">${escapeHtml(pick.label.split(" · ")[0])}${effort}</div>
        <div class="metrics">
          <div class="metric"><b>${pct(pick.score)}</b><span>CursorBench</span></div>
          <div class="metric"><b>${credits(slot.per_task_credits)}</b><span>credits / task</span></div>
          <div class="metric"><b>${credits(slot.month_credits)}</b><span>credits / mo</span></div>
        </div>
        <p class="why">${escapeHtml(slot.why || "")}</p>
        ${notes.map((note) => `<p class="note">${escapeHtml(note)}</p>`).join("")}
        <div class="badges">${driftBadge(pick.drift)}${copilotBadge(pick.copilot)}
          <span class="badge">${usd(pick.cost_usd)} / task</span>
          <span class="badge">${pick.steps} steps</span></div>
      </article>`)
    );
  });

  const thresholds = view.thresholds;
  $("#verdict-sub").textContent =
    `Filled under this tier's monthly credit budget. Architect: the best model its share affords. ` +
    `Worker: upgrades while they cost at most $${thresholds.steep_usd_per_pp.toFixed(2)} per point. ` +
    `Scout: bargain upgrades only, at most $${thresholds.bargain_usd_per_pp.toFixed(2)} per point.`;
}

/* ---------- monthly budget ---------- */

function renderBudget(view) {
  const current = plan();
  if (!current) return;
  const assumptions = view.assumptions;
  const used = current.used_pct ?? 0;

  $("#budget-title").textContent =
    `${current.name}: ${credits(current.month_credits)} of ${num(current.credits)} credits`;

  const fill = $("#budget-fill");
  fill.style.width = `${Math.min(100, used)}%`;
  fill.className = used > 100 ? "over" : used > 80 ? "tight" : "";

  const referenceLine = current.reference_fits
    ? `The shortlist chosen on merit alone would cost ${credits(current.reference_credits)} credits here — ${current.reference_used_pct}% of the tier, so the budget is not what decides your models.`
    : `The shortlist chosen on merit alone would cost ${credits(current.reference_credits)} credits — ${current.reference_used_pct}% of this tier. At ${current.name} the budget, not the benchmark, picks your models.`;

  $("#budget-verdict").textContent =
    `About $${num(current.month_usd)} a month for an average engineer's workload, leaving ` +
    `${credits(current.headroom_credits)} credits of headroom (${Math.max(0, 100 - used).toFixed(0)}%). ` +
    referenceLine;

  const body = $("#budget-table tbody");
  body.innerHTML = "";
  view.tiers.forEach((role) => {
    const slot = current.roles[role.id];
    if (!slot) return;
    const label = slot.pick ? slot.pick.label : "—";
    body.append(
      tag(`<tr>
        <td><span class="tier-chip ${role.accent}">${escapeHtml(role.name)}</span></td>
        <td class="pick-cell">${escapeHtml(label)}</td>
        <td class="num">${credits(slot.per_task_credits)}</td>
        <td class="num">${slot.tasks_per_month ?? "—"}</td>
        <td class="num">${credits(slot.month_credits)}</td>
        <td class="num ${slot.share_used_pct > 100 ? "violet" : "dim"}">${
          slot.share_used_pct === undefined || slot.share_used_pct === null
            ? "—"
            : slot.share_used_pct.toFixed(0) + "%"
        }</td>
      </tr>`)
    );
  });

  $("#budget-assumptions").textContent =
    `Assumes ${assumptions.working_days} working days × ${assumptions.tasks_per_day} agent tasks = ` +
    `${assumptions.tasks_per_month} tasks a month (${assumptions.tasks_by_role.architect} planning, ` +
    `${assumptions.tasks_by_role.worker} ordinary, ${assumptions.tasks_by_role.scout} mechanical), ` +
    `one project at a time and no parallel sessions, ×${assumptions.overhead} for chat and retries. ` +
    `The budget is split ${Math.round(assumptions.budget_shares.architect * 100)}/` +
    `${Math.round(assumptions.budget_shares.worker * 100)}/` +
    `${Math.round(assumptions.budget_shares.scout * 100)} between the roles. ` +
    `Code completions are not billed in credits, so they are not counted here.`;
}

/* ---------- gap tracks: the fit-axis device ---------- */

function renderGaps(gaps) {
  const box = $("#gaps");
  box.innerHTML = "";
  gaps.forEach((gap) => {
    const colour = gap.verdict === "bargain" ? "#38e1c4" : gap.verdict === "steep" ? "#7c5cff" : "#8b97a8";
    const message =
      gap.verdict === "bargain"
        ? "The surcharge is token next to the quality gained — take the dearer one, even for simple work."
        : gap.verdict === "steep"
        ? "You pay several times more for a fraction of the quality — escalate only when the cheaper one actually fails."
        : "A fair trade: the surcharge roughly matches the quality gained.";
    box.append(
      tag(`<div class="gap">
        <h3>${escapeHtml(gap.from)} → ${escapeHtml(gap.to)}</h3>
        <svg viewBox="0 0 400 74" aria-hidden="true">
          <line x1="24" y1="30" x2="376" y2="30" stroke="#222a3d" stroke-width="2"/>
          <line x1="24" y1="30" x2="376" y2="30" stroke="${colour}" stroke-width="3" stroke-dasharray="4 5"/>
          <circle cx="24" cy="30" r="7" fill="#141926" stroke="${colour}" stroke-width="2.5"/>
          <circle cx="376" cy="30" r="7" fill="${colour}"/>
          <text x="24" y="58" fill="#8b97a8" font-size="12" font-family="ui-monospace,monospace">${escapeHtml(gap.from_label)}</text>
          <text x="376" y="58" fill="#e8ecf1" font-size="12" font-family="ui-monospace,monospace" text-anchor="end">${escapeHtml(gap.to_label)}</text>
          <text x="200" y="18" fill="${colour}" font-size="13" font-family="ui-monospace,monospace" text-anchor="middle">+${gap.delta_score_pp} pp · +${usd(gap.delta_cost_usd)} · ×${gap.cost_factor}</text>
        </svg>
        <p class="verdict-line"><b class="mono" style="color:${colour}">${usd(gap.usd_per_pp)} per point</b> — ${escapeHtml(message)}</p>
      </div>`)
    );
  });
}

/* ---------- task table ---------- */

function renderTasks(view) {
  const body = $("#tasks tbody");
  const current = plan();
  body.innerHTML = "";
  view.tasks.forEach((task) => {
    const slot = current && current.roles ? current.roles[task.tier] : null;
    const pick = slot && slot.pick;
    const [name, effort] = (pick ? pick.label : "—").split(" · ");
    body.append(
      tag(`<tr>
        <td>${escapeHtml(task.label)}<br><span class="dim" style="font-size:.82rem">${escapeHtml(task.note)}</span></td>
        <td><span class="tier-chip ${task.accent}">${escapeHtml(task.tier_name)}</span></td>
        <td class="pick-cell">${escapeHtml(name)}${effort ? `<em>${escapeHtml(effort)}</em>` : ""}
            ${pick && !pick.copilot ? '<br><span class="dim" style="font-size:.75rem">not in Copilot</span>' : ""}</td>
        <td class="num">${pick ? pct(pick.score) : "—"}</td>
        <td class="num">${slot ? credits(slot.per_task_credits) : "—"}</td>
      </tr>`)
    );
  });
}

/* ---------- scatter: cost vs score ---------- */

function renderScatter(view) {
  const svg = $("#scatter");
  const W = 1000;
  const H = 470;
  const pad = { l: 62, r: 24, t: 24, b: 54 };
  const points = view.candidates.filter((c) => c.cost_usd > 0);
  if (!points.length) return;

  const costs = points.map((p) => Math.log10(p.cost_usd));
  const scores = points.map((p) => p.score);
  const x0 = Math.min(...costs) - 0.08;
  const x1 = Math.max(...costs) + 0.08;
  const y0 = Math.min(...scores) - 2;
  const y1 = Math.max(...scores) + 2;
  const sx = (cost) => pad.l + ((Math.log10(cost) - x0) / (x1 - x0)) * (W - pad.l - pad.r);
  const sy = (score) => H - pad.b - ((score - y0) / (y1 - y0)) * (H - pad.t - pad.b);

  const picks = {};
  const current = plan();
  Object.entries((current && current.roles) || {}).forEach(([id, slot]) => {
    if (slot.pick) picks[`${slot.pick.key}|${slot.pick.effort}`] = id;
  });
  const colour = { architect: "#7c5cff", worker: "#38e1c4", scout: "#8b97a8" };

  const parts = [];
  [0.03, 0.1, 0.3, 1, 3, 10, 20].forEach((tick) => {
    const x = sx(tick);
    if (x < pad.l - 2 || x > W - pad.r + 2) return;
    parts.push(`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${H - pad.b}" stroke="#222a3d" stroke-width="1"/>`);
    parts.push(`<text x="${x}" y="${H - pad.b + 22}" fill="#8b97a8" font-size="12" text-anchor="middle" font-family="ui-monospace,monospace">$${tick}</text>`);
  });
  for (let score = Math.ceil(y0 / 5) * 5; score <= y1; score += 5) {
    const y = sy(score);
    parts.push(`<line x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}" stroke="#222a3d" stroke-width="1"/>`);
    parts.push(`<text x="${pad.l - 12}" y="${y + 4}" fill="#8b97a8" font-size="12" text-anchor="end" font-family="ui-monospace,monospace">${score}%</text>`);
  }
  parts.push(`<text x="${W / 2}" y="${H - 8}" fill="#8b97a8" font-size="12" text-anchor="middle" font-family="ui-monospace,monospace" letter-spacing="1.6">AVERAGE COST PER TASK</text>`);

  const frontier = view.ladder.filter((rung) => rung.cost_usd > 0);
  if (frontier.length > 1) {
    const path = frontier.map((rung) => `${sx(rung.cost_usd)},${sy(rung.score)}`).join(" ");
    parts.push(`<polyline points="${path}" fill="none" stroke="#38e1c4" stroke-width="1.5" stroke-dasharray="5 6" opacity=".55"/>`);
  }

  points.forEach((point) => {
    const role = picks[`${point.key}|${point.effort}`];
    const fill = role ? colour[role] : "#3a4257";
    const radius = role ? 7 : 4.5;
    parts.push(
      `<circle cx="${sx(point.cost_usd)}" cy="${sy(point.score)}" r="${radius}" fill="${fill}" ${
        role ? 'stroke="#0b0e14" stroke-width="2"' : 'opacity=".85"'
      }><title>${escapeHtml(point.label)} — ${pct(point.score)}, ${usd(point.cost_usd)}, ${point.steps} steps</title></circle>`
    );
    if (role) {
      const x = sx(point.cost_usd);
      const anchor = x > W - 200 ? "end" : "start";
      const dx = anchor === "end" ? -12 : 12;
      parts.push(
        `<text x="${x + dx}" y="${sy(point.score) + 4}" fill="${fill}" font-size="13" font-weight="600" text-anchor="${anchor}" font-family="system-ui,sans-serif">${escapeHtml(point.label)}</text>`
      );
    }
  });

  svg.innerHTML = parts.join("");
}

/* ---------- value ladder ---------- */

function renderLadder(ladder) {
  const box = $("#ladder");
  box.innerHTML = "";
  ladder.forEach((rung, index) => {
    if (index === 0) {
      box.append(
        tag(`<div class="rung fair">
          <div><span class="headline">${escapeHtml(rung.label)}</span>
            <div class="step">starting point — as cheap as it gets</div></div>
          <div class="price">${pct(rung.score)} · ${usd(rung.cost_usd)}</div>
        </div>`)
      );
      return;
    }
    const message =
      rung.verdict === "bargain"
        ? "pennies for a real jump in quality"
        : rung.verdict === "steep"
        ? "expensive for very little — only when it truly matters"
        : "a fair trade";
    box.append(
      tag(`<div class="rung ${rung.verdict}">
        <div><span class="headline">${escapeHtml(rung.label)}</span>
          <div class="step">from ${escapeHtml(rung.from_label)}: +${rung.delta_score_pp} pp for +${usd(rung.delta_cost_usd)} → <b>${usd(rung.usd_per_pp)}/pp</b> — ${message}</div></div>
        <div class="price">${pct(rung.score)} · ${usd(rung.cost_usd)}</div>
      </div>`)
    );
  });
}

/* ---------- drift ---------- */

function sparkline(points, delta) {
  if (!points || points.length < 2) return '<span class="dim mono" style="font-size:.75rem">no history yet</span>';
  const values = points.map((p) => p[1]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const W = 132;
  const H = 30;
  const sx = (i) => (i / (points.length - 1)) * W;
  const sy = (value) => H - 3 - ((value - min) / span) * (H - 6);
  const raw = values.map((value, i) => `${sx(i).toFixed(1)},${sy(value).toFixed(1)}`).join(" ");
  const window = 5;
  const smooth = values
    .map((_, i) => {
      const slice = values.slice(Math.max(0, i - window + 1), i + 1);
      return slice.reduce((a, b) => a + b, 0) / slice.length;
    })
    .map((value, i) => `${sx(i).toFixed(1)},${sy(value).toFixed(1)}`)
    .join(" ");
  const colour = delta === null || delta === undefined ? "#8b97a8" : delta < 0 ? "#7c5cff" : "#38e1c4";
  return `<svg viewBox="0 0 ${W} ${H}" style="width:132px;height:30px">
    <polyline points="${raw}" fill="none" stroke="#3a4257" stroke-width="1"/>
    <polyline points="${smooth}" fill="none" stroke="${colour}" stroke-width="2"/>
  </svg>`;
}

function renderDrift(drift) {
  const body = $("#drift tbody");
  body.innerHTML = "";
  drift.forEach((row) => {
    const arrow = row.trend === "up" ? "↑ rising" : row.trend === "down" ? "↓ falling" : "→ steady";
    const cls = row.trend === "down" ? "violet" : row.trend === "up" ? "cyan" : "dim";
    const delta =
      row.delta_7d === null || row.delta_7d === undefined
        ? "—"
        : `${row.delta_7d > 0 ? "+" : ""}${row.delta_7d}`;
    const deltaCls = row.delta_7d < 0 ? "violet" : row.delta_7d > 0 ? "cyan" : "dim";
    body.append(
      tag(`<tr>
        <td>${escapeHtml(row.label)} ${row.stale ? '<span class="dim mono" style="font-size:.68rem">· not refreshed</span>' : ""}</td>
        <td class="num"><b>${row.score === null ? "—" : Math.round(row.score)}</b></td>
        <td>${sparkline(row.points, row.delta_7d)}</td>
        <td class="num ${deltaCls}">${delta}</td>
        <td class="num dim">${row.min_7d ?? "—"}–${row.max_7d ?? "—"}</td>
        <td class="${cls} mono" style="font-size:.78rem">${arrow}</td>
      </tr>`)
    );
  });
}

/* ---------- copilot pricing ---------- */

function renderCopilot(view) {
  const body = $("#copilot tbody");
  body.innerHTML = "";
  const best = new Map();
  view.candidates.forEach((candidate) => {
    if (!candidate.copilot) return;
    const current = best.get(candidate.key);
    if (!current || candidate.score > current.score) best.set(candidate.key, candidate);
  });

  const rows = [];
  best.forEach((candidate) => {
    rows.push({
      label: candidate.label.split(" · ")[0],
      category: candidate.copilot.category,
      input: candidate.copilot.input_usd,
      cached: candidate.copilot.cached_input_usd,
      output: candidate.copilot.output_usd,
      score: candidate.score,
      effort: candidate.effort_label,
    });
  });
  view.copilot_only.forEach((model) => {
    rows.push({
      label: model.label,
      category: model.category,
      input: model.input_usd,
      cached: model.cached_input_usd,
      output: model.output_usd,
      score: null,
      effort: null,
    });
  });
  rows.sort((a, b) => (b.score ?? -1) - (a.score ?? -1) || (a.input ?? 0) - (b.input ?? 0));

  rows.forEach((row) => {
    body.append(
      tag(`<tr>
        <td>${escapeHtml(row.label)}</td>
        <td class="dim">${escapeHtml(row.category || "—")}</td>
        <td class="num">${usd(row.input)}</td>
        <td class="num dim">${usd(row.cached)}</td>
        <td class="num">${usd(row.output)}</td>
        <td class="num">${row.score === null ? '<span class="dim">not benchmarked</span>' : `${pct(row.score)} <span class="dim" style="font-size:.72rem">${escapeHtml(row.effort)}</span>`}</td>
      </tr>`)
    );
  });
}

/* ---------- footer ---------- */

function renderMethod(view) {
  const method = $("#method");
  const thresholds = view.thresholds;
  const hidden = (view.hidden_by_config || []).join(", ");
  method.innerHTML = `
    <div>Cost, score, tokens and steps come from CursorBench ${escapeHtml(view.benchmark_version || "")} —
      always for the effort level named on the card. Drift comes from AI Stupid Level and acts as a
      veto rather than another number in an average: a model on the way down loses to a comparable
      model that is holding steady.</div>
    <div>Thresholds: architect ≤ ${thresholds.architect_score_slack_pp} pp below the top score (cheapest of that group),
      worker ≤ $${thresholds.worker_max_cost_usd.toFixed(2)} per task, scout ≤ $${thresholds.scout_max_cost_usd.toFixed(2)} per task.
      Under $${thresholds.bargain_usd_per_pp.toFixed(2)} per point is a bargain, over $${thresholds.steep_usd_per_pp.toFixed(2)} is overpaying.</div>
    <div>Hidden from the default view because they are not enabled in our Copilot subscription:
      ${escapeHtml(hidden || "nothing")}. They are still collected and archived.</div>
    <div>Credits: 1 AI credit = $${view.credit_usd.toFixed(2)}, ${
      view.credit_usd_verified ? "read today from" : "assumed — not readable today in"
    } GitHub's pricing page${
      view.credit_usd_quote ? `: <i class="dim">“${escapeHtml(view.credit_usd_quote)}”</i>` : ""
    }</div>`;

  const archive = view.archive;
  $("#archive").innerHTML = `<p class="mono" style="font-size:.75rem;letter-spacing:.1em">
      ARCHIVE: ${archive.snapshots} SNAPSHOTS · ${num(archive.observations)} READINGS · SINCE ${escapeHtml(
    (archive.since || "").slice(0, 16).replace("T", " ")
  )} · ${(archive.db_bytes / 1024).toFixed(0)} KB</p>`;
}

/* ---------- boot ---------- */

function renderAll() {
  const view = state.view;
  if (!view) return;
  const current = plan();
  renderTierTabs(view);
  renderFreshness(view.sources);
  renderVerdicts(view);
  renderBudget(view);
  renderGaps((current && current.gaps) || view.gaps);
  renderTasks(view);
  renderScatter(view);
  renderLadder(view.ladder);
  renderDrift(view.drift);
  renderCopilot(view);
  renderMethod(view);
}

async function load() {
  const response = await fetch(`/api/view${state.showAll ? "?all=1" : ""}`, { cache: "no-store" });
  const view = await response.json();
  state.view = view;

  const remembered = storedTier();
  if (!view.plans || !view.plans[state.tier]) {
    state.tier =
      remembered && view.plans && view.plans[remembered] ? remembered : view.default_tier;
  }

  if (!view.ready) {
    $("#verdict-sub").textContent =
      "Collecting from the sources — this page reloads itself every 5 minutes.";
  }
  renderAll();
}

$("#toggle-all").addEventListener("click", (event) => {
  state.showAll = !state.showAll;
  event.currentTarget.setAttribute("aria-pressed", String(state.showAll));
  event.currentTarget.textContent = state.showAll ? "Hide filtered models" : "Show hidden models";
  load();
});

load();
setInterval(load, 5 * 60 * 1000);
