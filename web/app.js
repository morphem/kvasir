/* Kvasir front end: one fetch of /api/view, everything below is rendering.
   No framework and no chart library on purpose — the whole page is one file the browser
   parses in a blink, and the SVG here is simpler than the config a chart library would need. */

const TIER_STORAGE_KEY = "kvasir.tier";
const PATIENCE_STORAGE_KEY = "kvasir.patience";
const PANEL_STORAGE_KEY = "kvasir.panel";

/* The page grew past the point where scrolling is navigation: seven sections of tables, and
   the one you want is always the fourth or the fifth. The verdict stays pinned above — it is
   the reason the page exists — and everything below it becomes one switchable panel, so a
   question like "what do all the Opus variants wait" is a click rather than a hunt. */
/* The map comes first: intelligence against cost and against time is the page's main source
   of knowledge, and the tab most visitors should land on. */
const PANELS = [
  { id: "map", label: "Where to use what" },
  { id: "tasks", label: "Task → agent" },
  { id: "budget", label: "Month on this tier" },
  { id: "value", label: "Is the upgrade worth it" },
  { id: "models", label: "All models" },
  { id: "drift", label: "Drift" },
  { id: "method", label: "Method" },
];
const state = {
  view: null,
  showAll: false,
  tier: null,
  patience: null,
  waitFilter: null, // minutes per task, or null for any — the models table's own filter
  map: null, // which chart the map shows: cost, time or tokens
  market: false, // draw the models we cannot start behind the board, for scale
  selected: null,
  everyVariant: false,
  families: [], // model keys with their variant line drawn on the scatter, in activation order
};

/* Family line colours, in activation order. The frontier stays dashed grey-cyan, so even
   the first hue reads as a different kind of line; three is where distinct hues run out. */
const FAMILY_HUES = ["#38e1c4", "#7c5cff", "#f5b544"];
const MAX_FAMILIES = FAMILY_HUES.length;

function familyHue(key) {
  const index = state.families.indexOf(key);
  return index === -1 ? null : FAMILY_HUES[index];
}

/* The tier and the patience are view settings, not a user account: they live in
   localStorage, survive every reload and deploy, and fall back to what the server nominates. */
function stored(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function store(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private browsing: the switch still works, it just forgets between visits */
  }
}

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* A switch re-answers the whole page. The View Transition turns that into one cross-fade
   in which each card keeps its place, so the eye sees which picks moved rather than a
   flash of new text. Browsers without it, and readers who asked for less motion, get the
   plain re-render. */
function rerender() {
  if (document.startViewTransition && !reducedMotion()) {
    document.startViewTransition(() => renderAll({ animate: true }));
  } else {
    renderAll({ animate: !reducedMotion() });
  }
}

function storedPanel() {
  const fromHash = (location.hash || "").replace("#", "");
  if (PANELS.some((panel) => panel.id === fromHash)) return fromHash;
  try {
    return localStorage.getItem(PANEL_STORAGE_KEY);
  } catch {
    return null;
  }
}

function showPanel(id, { scroll = false } = {}) {
  const known = PANELS.some((panel) => panel.id === id) ? id : PANELS[0].id;
  state.panel = known;
  try {
    localStorage.setItem(PANEL_STORAGE_KEY, known);
  } catch {
    /* private browsing: the switch works, it just forgets */
  }
  if (location.hash !== `#${known}`) history.replaceState(null, "", `#${known}`);

  // Scoped to sections on purpose: the tab buttons carry the same attribute, and an
  // unscoped query hid six of the seven switches it had just drawn.
  document.querySelectorAll("section[data-panel]").forEach((section) => {
    section.hidden = section.dataset.panel !== known;
  });
  document.querySelectorAll("#section-tabs .tab").forEach((tab) => {
    tab.setAttribute("aria-selected", String(tab.dataset.panel === known));
  });

  // Only pull the page up when the tab strip has scrolled out of sight — switching while
  // the verdict is on screen should not move anything.
  const tabs = $("#section-tabs");
  if (scroll && tabs && tabs.getBoundingClientRect().top < 0) {
    tabs.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
  }
}

function renderTabs() {
  const box = $("#section-tabs");
  if (!box || box.dataset.ready) return;
  box.dataset.ready = "1";
  PANELS.forEach((panel) => {
    const tab = tag(
      `<button class="tab" role="tab" data-panel="${panel.id}" aria-selected="false">${escapeHtml(
        panel.label
      )}</button>`
    );
    tab.addEventListener("click", () => showPanel(panel.id, { scroll: true }));
    box.append(tab);
  });
}

function plan(tier = state.tier) {
  const plans = (state.view && state.view.plans) || {};
  const byPatience = plans[tier] || Object.values(plans)[0] || {};
  return byPatience[state.patience] || Object.values(byPatience)[0] || null;
}

/* ---------- variant selection: the chart and the ladder share one detail panel ---------- */

const candidateId = (c) => `${c.key}|${c.effort}`;

function findCandidate(id) {
  if (!state.view || !id) return null;
  return state.view.candidates.find((c) => candidateId(c) === id) || null;
}

function frontierIds() {
  return new Set((state.view ? state.view.ladder : []).map((rung) => `${rung.key}|${rung.effort}`));
}

/* The frontier rung that already beats this variant: the first one, walking up from the
   cheapest, whose score reaches it. A variant off the frontier is exactly a variant such a
   rung exists for — that is what "dominated" means here. */
function dominatorOf(candidate) {
  return (state.view ? state.view.ladder : []).find((rung) => rung.score >= candidate.score) || null;
}

function selectVariant(id) {
  state.selected = id;
  renderMap(state.view);
  renderChartDetail();
  renderLadder(state.view);
}

function toggleVariant(id) {
  selectVariant(state.selected === id ? null : id);
}

/* ---------- family lines: one model's effort ladder drawn through its dots ---------- */

function familyName(candidates) {
  return candidates[0].label.split(" · ")[0];
}

/* Families worth a line: two or more efforts. The line runs low to max, so on every chart
   it reads as the same thing — what turning the effort dial up buys, and what it costs.
   Alphabetical, so the list never reshuffles when scores move. */
function families(view) {
  const groups = new Map();
  // Current models only: a retired family's ladder is history, and seventeen chips above the
  // chart buried the seven that matter.
  view.candidates.filter((c) => !c.deprecated).forEach((c) => {
    if (!groups.has(c.key)) groups.set(c.key, []);
    groups.get(c.key).push(c);
  });
  return [...groups.values()]
    .filter((members) => members.length >= 2)
    .map((members) => ({
      key: members[0].key,
      name: familyName(members),
      variants: members.sort((a, b) => (EFFORT_RANK[a.effort] ?? 9) - (EFFORT_RANK[b.effort] ?? 9)),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

function toggleFamily(key) {
  const index = state.families.indexOf(key);
  if (index !== -1) {
    state.families.splice(index, 1);
  } else if (state.families.length < MAX_FAMILIES) {
    state.families.push(key);
  }
  renderFamilyPicker(state.view);
  renderMap(state.view);
}

function renderFamilyPicker(view) {
  const box = $("#family-picker");
  if (!box || !view) return;
  const all = families(view);
  if (!all.length) {
    box.innerHTML = "";
    box.hidden = true;
    return;
  }
  const full = state.families.length >= MAX_FAMILIES;
  box.innerHTML =
    `<span class="eyebrow" style="align-self:center">Variant lines</span>` +
    all
      .map((family) => {
        const active = state.families.includes(family.key);
        const blocked = !active && full;
        const hue = familyHue(family.key);
        return `<button class="family-chip" data-key="${escapeHtml(family.key)}"
            aria-pressed="${active}" ${blocked ? "disabled" : ""}
            ${active && hue ? `style="border-color:${hue};color:${hue}"` : ""}>
          <i style="background:${hue || "#3a4257"}"></i>${escapeHtml(family.name)}
          <b class="dim" style="font-weight:400">${family.variants.length}</b>
        </button>`;
      })
      .join("");
  box.hidden = false;
  box.querySelectorAll(".family-chip:not([disabled])").forEach((chip) => {
    chip.addEventListener("click", () => toggleFamily(chip.getAttribute("data-key")));
  });
}

const $ = (sel) => document.querySelector(sel);
const usd = (value) =>
  value === null || value === undefined ? "—" : `$${value < 1 ? value.toFixed(2) : value.toFixed(2)}`;
/* The Intelligence Index is a score, not a percentage: it is printed bare. */
const idx = (value) => (value === null || value === undefined ? "—" : value.toFixed(1));
const secs = (value) =>
  value === null || value === undefined ? "—" : value < 10 ? `${value.toFixed(1)} s` : `${Math.round(value)} s`;
const taskCredits = (candidate, view) =>
  candidate && candidate.cost_usd !== null && candidate.cost_usd !== undefined
    ? candidate.cost_usd / ((view && view.credit_usd) || 0.01)
    : null;
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
      tag(`<a class="chip" href="${escapeHtml(source.url)}" target="_blank" rel="noopener"
             title="${escapeHtml(source.label)} — last change ${escapeHtml(ago(source.captured_at))}, ${escapeHtml(due)}, polled ${every}">
             <i class="dot ${dot}"></i>${escapeHtml(source.label)}
             <b class="dim" style="font-weight:400">${escapeHtml(ago(source.captured_at))}</b>
           </a>`)
    );
  });
}

/* ---------- tier switch ---------- */

function renderTierTabs(view) {
  const tabs = $("#tier-tabs");
  tabs.innerHTML = "";
  (view.budget_tiers || []).forEach((tier) => {
    const tierPlan = plan(tier.id) || {};
    const active = tier.id === state.tier;
    const button = tag(`<button class="tier-tab" role="tab" aria-selected="${active}">
      <b>${escapeHtml(tier.name)}</b>
      <span>${Math.round(tier.credits / 1000)}K credits · $${num(tierPlan.usd)}</span>
    </button>`);
    button.addEventListener("click", () => {
      if (state.tier === tier.id) return;
      state.tier = tier.id;
      store(TIER_STORAGE_KEY, tier.id);
      rerender();
    });
    tabs.append(button);
  });

  const current = plan();
  // The provenance of the credit rate is a method question, not a header one.
  $("#tier-note").textContent = current
    ? `${num(current.credits)} credits a month · about $${num(current.usd)}`
    : "";
}

/* Patience is the second switch, and it reads like the first: a name, and underneath it the
   numbers it stands for — the longest wait before the first answer the scout and the worker
   may put you through. The architect is never on this clock. */
const ceilingText = (minutes) => (minutes === null || minutes === undefined ? "any" : `${minutes} min`);

function renderPatienceTabs(view) {
  const tabs = $("#patience-tabs");
  if (!tabs) return;
  tabs.innerHTML = "";
  (view.patience || []).forEach((level) => {
    const active = level.id === state.patience;
    const detail =
      level.scout === null && level.worker === null
        ? "no limit on waiting"
        : `scout ${ceilingText(level.scout)} · worker ${ceilingText(level.worker)}`;
    // a task, per loop
    const button = tag(`<button class="tier-tab" role="tab" aria-selected="${active}">
      <b>${escapeHtml(level.label)}</b>
      <span>${escapeHtml(detail)}</span>
    </button>`);
    button.addEventListener("click", () => {
      if (state.patience === level.id) return;
      state.patience = level.id;
      store(PATIENCE_STORAGE_KEY, level.id);
      rerender();
    });
    tabs.append(button);
  });
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

/* ---------- the clock: one time scale for the whole page ----------

   Minutes per task — the length of one loop — on one square-root scale shared by every card,
   so a one-minute task and a four-minute task stay apart and a fifteen-minute one still fits.
   The ticks are the patience ceilings: the limits a loop role has to beat. */
const CLOCK_MAX_MIN = 16;
const clockX = (minutes) => Math.min(1, Math.sqrt(Math.max(0, minutes) / CLOCK_MAX_MIN));

function clockTicks() {
  const values = new Set();
  ((state.view && state.view.patience) || []).forEach((p) => {
    [p.scout, p.worker].forEach((v) => v !== null && v !== undefined && values.add(v));
  });
  return [...values].sort((a, b) => a - b);
}

function clock(role, pick, ceiling, animate) {
  const minutes = loopMinutes(pick);
  const floorFrom = pick && pick.speed ? pick.speed.task_minutes_floor_from : null;
  const ticks = clockTicks()
    .map(
      (t) =>
        `<span class="tick ${t === ceiling ? "limit" : ""}" style="left:${(clockX(t) * 100).toFixed(1)}%">
           <em>${t}</em></span>`
    )
    .join("");
  if (minutes === null || minutes === undefined) {
    return `<div class="clock untimed">
      <div class="clock-head"><b>not timed</b><span>no time per task measured at this effort</span></div>
      <div class="clock-track">${ticks}</div>
    </div>`;
  }
  // The bar takes longer to fill the longer the real task is: the role that finishes first
  // lands first. Only on load and on a switch — never on the background refresh.
  const duration = Math.round(250 + 1100 * clockX(minutes));
  const limit =
    role === "architect"
      ? "a task — planning runs once, so it is not on the clock"
      : ceiling === null || ceiling === undefined
      ? "a task — no limit set"
      : `a task — limit ${ceiling} min`;
  const value = `${floorFrom ? "≥ " : ""}${minutes < 10 ? minutes.toFixed(1) : Math.round(minutes)}`;
  return `<div class="clock ${floorFrom ? "floor" : ""}">
    <div class="clock-head"><b>${value}<small>min</small></b><span>${escapeHtml(
      floorFrom ? `a task — not timed; ${EFFORT_NAMES[floorFrom] || floorFrom} already takes this long` : limit
    )}</span></div>
    <div class="clock-track">
      <i class="clock-bar ${role === "architect" ? "free" : ""} ${animate ? "run" : ""}"
         style="--to:${(clockX(minutes) * 100).toFixed(1)}%;--dur:${duration}ms"></i>
      ${ticks}
    </div>
  </div>`;
}

/* Numbers that change on a switch count to their new value instead of snapping, so the eye
   can tell what moved. Remembered by key across re-renders; the first render just sets. */
const COUNTED = new Map();

function countTo(el, key, to, animate) {
  const from = COUNTED.get(key);
  COUNTED.set(key, to);
  if (!animate || from === undefined || from === to || to === null) {
    el.textContent = credits(to);
    return;
  }
  const start = performance.now();
  const span = 480;
  const step = (now) => {
    const t = Math.min(1, (now - start) / span);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = credits(from + (to - from) * eased);
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function runCounters(root, animate) {
  root.querySelectorAll("[data-count]").forEach((el) => {
    const value = el.dataset.value === "" ? null : Number(el.dataset.value);
    countTo(el, el.dataset.count, value, animate);
  });
}

function renderVerdicts(view, animate) {
  // Bars are only readable against a common scale, and the board is the honest one: the
  // fastest model on it sets full width.
  const measured = view.candidates.map((c) => c.speed).filter(Boolean);
  view._scales = { speed: Math.max(1, ...measured.map((s) => s.tokens_per_second || 0)) };

  const box = $("#verdicts");
  const current = plan();
  box.innerHTML = "";
  const roles = (current && current.roles) || {};
  view.tiers.forEach((role) => {
    const slot = roles[role.id];
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
    const asides = [];
    if (slot.out_of_reach) {
      const reach = slot.out_of_reach;
      notes.push(
        `The best on the board is ${reach.label} at ${idx(reach.score)}, ` +
          `${credits(reach.per_task_credits)} credits a task — above this tier's ` +
          `${credits(reach.ceiling_credits)}-credit ceiling for planning.`
      );
    }
    if (slot.drift_replaced) {
      notes.push(`Drift veto: ${slot.drift_replaced} scores as well but is sliding on AI Stupid Level.`);
    }
    if (slot.same_as) {
      notes.push(`Same model and effort as the ${slot.same_as} at this tier — one answer, not two.`);
    } else {
      // One model at three efforts is a real answer when it leads at every price point, and
      // it is worth saying so rather than letting three cards look like three choices.
      const siblings = Object.entries(roles)
        .filter(([other, data]) => other !== role.id && data.pick && data.pick.key === pick.key)
        .map(([other]) => other);
      if (siblings.length && role.id !== "architect") {
        asides.push(`Same model as the ${siblings.join(" and the ")}, at a different effort.`);
      }
    }
    box.append(
      tag(`<article class="card ${role.id}" style="view-transition-name:card-${role.id}">
        <div class="role-band">
          <span class="role-name">${escapeHtml(role.name)}</span>
          <span class="role-line">${escapeHtml(role.role)}</span>
        </div>
        <div class="pick-name">${escapeHtml(pick.label.split(" · ")[0])}${effort}</div>
        ${clock(role.id, pick, slot.ceiling_minutes, animate)}
        <div class="metrics">
          <div class="metric"><b>${idx(pick.score)}</b><span>Intelligence</span></div>
          <div class="metric"><b data-count="card-${role.id}-task" data-value="${slot.per_task_credits ?? ""}"></b><span>credits / task</span></div>
          <div class="metric"><b data-count="card-${role.id}-month" data-value="${slot.month_credits ?? ""}"></b><span>credits / mo</span></div>
        </div>
        <p class="why">${escapeHtml(slot.why || "")}</p>
        ${notes.map((note) => `<p class="note">${escapeHtml(note)}</p>`).join("")}
        ${asides.map((aside) => `<p class="why aside">${escapeHtml(aside)}</p>`).join("")}
        ${propertyRows(pick, view)}
      </article>`)
    );
  });
  runCounters(box, animate);

  renderBenchmarkNote(view);
  renderPricingNote(view);

  const tier = plan();
  const level = (view.patience || []).find((p) => p.id === state.patience);
  $("#verdict-sub").textContent = tier
    ? `Filled inside the ${tier.name} tier's monthly budget at ${
        level ? level.label.toLowerCase() : state.patience
      } patience — ${tier.used_pct}% of it planned, about $${num(tier.month_usd)} a month.`
    : "";
}

const firstAnswer = (candidate) => (candidate && candidate.speed ? candidate.speed.first_answer_seconds : null);

/* A model GitHub already sells can arrive before its price does: Artificial Analysis times
   and scores a release on day one and prices it days later. Until then it cannot be planned,
   and the page says so instead of letting it look forgotten. */
function renderPricingNote(view) {
  // Only models with no priced variant at all: an old model whose low effort was never priced
  // is not waiting for anything, and "not priced yet" would be a false promise about it.
  const pricedKeys = new Set(view.candidates.filter((c) => c.priced).map((c) => c.key));
  const fresh = [];
  const never = [];
  const seen = new Set();
  (view.unpriced || []).forEach((u) => {
    if (pricedKeys.has(u.key) || seen.has(u.key)) return;
    seen.add(u.key);
    const name = u.label.split(" · ")[0];
    const days = u.released ? (Date.now() - new Date(u.released).getTime()) / 86400000 : Infinity;
    (days <= 30 ? fresh : never).push(name);
  });
  const verdict = fresh.length
    ? `Not priced yet: ${fresh.join(", ")}. Artificial Analysis has scored and timed ` +
      `${fresh.length > 1 ? "them" : "it"} but not published a cost per task, so ` +
      `${fresh.length > 1 ? "they cannot" : "it cannot"} be planned into a tier yet — listed under All models, ` +
      `and joining the roles as soon as the price lands.`
    : "";
  const value = [
    verdict,
    never.length ? `Scored but never priced by Artificial Analysis, so off this chart: ${never.join(", ")}.` : "",
  ]
    .filter(Boolean)
    .join(" ");
  [["#pricing-note", verdict], ["#unpriced-note", value]].forEach(([sel, text]) => {
    const el = $(sel);
    if (!el) return;
    el.hidden = !text;
    el.textContent = text;
  });
}

/* A re-baselined benchmark is the single change most likely to make this page look broken:
   the board shrinks, every score drops, and nothing on the page says why. It gets a line of
   its own for as long as the previous version is still in living memory. */
function renderBenchmarkNote(view) {
  const note = $("#benchmark-note");
  if (!note) return;
  const history = view.benchmark_history || [];
  note.hidden = history.length < 2;
  if (history.length < 2) return;

  const current = history[history.length - 1];
  const previous = history[history.length - 2];
  const since = new Date(current.first_seen);
  const days = Math.round((Date.now() - since.getTime()) / 86400000);
  if (days > 45) {
    note.hidden = true;
    return;
  }
  const top = Math.max(...view.candidates.map((candidate) => candidate.score));
  note.textContent =
    `Intelligence Index v${current.version} replaced v${previous.version} on ` +
    `${since.toLocaleDateString("en-GB", { day: "numeric", month: "short" })} — top score now ` +
    `${top.toFixed(1)}, and scores either side of that date are not the same measurement.`;
}

/* The card foot is a property sheet, not a bag of chips.

   Chips wrapped differently in every card — two lines here, one there — so nothing lined up
   and two models could not be read against each other. These rows are fixed in number and
   order, and a missing value keeps its row, because an absent line is what breaks a column
   scan. The two bars are the only ornament, and they carry the one thing this page could
   not say until now: how long you sit there. */
function bar(fraction, tone) {
  const width = Math.max(2, Math.min(100, Math.round(fraction * 100)));
  return `<span class="meter"><i class="${tone}" style="width:${width}%"></i></span>`;
}

function propertyRows(pick, view) {
  const speed = pick.speed || {};
  const scales = view._scales || { speed: 1 };
  const drift = pick.drift;
  const copilot = pick.copilot;
  const borrowed =
    speed.tokens_per_second && speed.measured_effort && speed.measured_effort !== pick.effort
      ? ` <span class="dim">at ${escapeHtml(speed.measured_effort)}</span>`
      : "";

  const rows = [
    speed.tokens_per_second
      ? [
          "types",
          `<b class="cyan">${Math.round(speed.tokens_per_second)}</b> tok/s${borrowed}`,
          bar(speed.tokens_per_second / scales.speed, "cyan-fill"),
        ]
      : ["types", '<span class="dim">not measured</span>', ""],
    speed.first_answer_seconds
      ? ["first answer", `${secs(speed.first_answer_seconds)} before it starts`, ""]
      : ["first answer", '<span class="dim">not measured</span>', ""],
    [
      "coding",
      pick.terminal_bench === null || pick.terminal_bench === undefined
        ? '<span class="dim">not run</span>'
        : `${pick.terminal_bench.toFixed(1)}% <span class="dim">Terminal-Bench</span>`,
      "",
    ],
    [
      "drift",
      drift && drift.score !== null
        ? `${Math.round(drift.score)} · ${
            drift.trend === "up" ? "rising" : drift.trend === "down" ? "falling" : "steady"
          }`
        : '<span class="dim">not tracked</span>',
      "",
    ],
    [
      "per task",
      `${usd(pick.cost_usd)}${
        pick.output_tokens ? ` · ${num(pick.output_tokens)} tokens out` : ""
      }`,
      "",
    ],
    [
      "copilot",
      copilot
        ? `$${copilot.input_usd} / $${copilot.output_usd} per 1M`
        : '<span class="dim">not sold to us</span>',
      "",
    ],
  ];

  return `<dl class="props">${rows
    .map(
      ([label, value, meter]) =>
        `<dt>${label}</dt><dd><span class="val">${value}</span>${meter}</dd>`
    )
    .join("")}</dl>`;
}

/* ---------- monthly budget ---------- */

function renderBudget(view, animate) {
  const current = plan();
  if (!current) return;
  const assumptions = view.assumptions;
  const used = current.used_pct ?? 0;

  const title = $("#budget-title");
  title.innerHTML = `${escapeHtml(current.name)}: <span data-count="budget-month" data-value="${
    current.month_credits
  }"></span> of ${num(current.credits)} credits`;
  runCounters(title, animate);

  const fill = $("#budget-fill");
  fill.style.width = `${Math.min(100, used)}%`;
  fill.className = used > 100 ? "over" : used > 80 ? "tight" : "";

  const referenceLine = current.reference_fits
    ? `The shortlist chosen on merit alone would cost ${credits(current.reference_credits)} credits here — ${current.reference_used_pct}% of the tier, so the budget is not what decides your models.`
    : `The shortlist chosen on merit alone would cost ${credits(current.reference_credits)} credits — ${current.reference_used_pct}% of this tier. At ${current.name} the budget, not the benchmark, picks your models.`;

  const stopped = current.stopped_note
    ? ` It stops there because ${current.stopped_note}.`
    : "";
  $("#budget-verdict").textContent =
    `About $${num(current.month_usd)} a month for an average engineer's workload, leaving ` +
    `${credits(current.headroom_credits)} credits of headroom (${Math.max(0, 100 - used).toFixed(0)}%).` +
    stopped +
    " " +
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
    `A task is one Artificial Analysis Intelligence Index task, averaged over its ten evaluations. ` +
    `The worker and the scout are the roles you iterate with, so at this patience a variant that ` +
    `takes longer than ${ceilingText((assumptions.patience[state.patience] || {}).worker)} (worker) or ` +
    `${ceilingText((assumptions.patience[state.patience] || {}).scout)} (scout) per task cannot take ` +
    `one — the architect is exempt, because a plan is made once and on purpose. A variant nobody has ` +
    `timed is not treated as slow, unless a lower effort of the same model already takes longer. ` +
    `The plan then spends the surplus up to ${Math.round(assumptions.target_utilisation * 100)}% of the ` +
    `tier and never plans past ${Math.round(assumptions.max_utilisation * 100)}% — an unused credit ` +
    `buys nothing, and the month is a model rather than a meter. ` +
    `The opening split is ${Math.round(assumptions.budget_shares.architect * 100)}/` +
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
          <text x="200" y="18" fill="${colour}" font-size="13" font-family="ui-monospace,monospace" text-anchor="middle">+${gap.delta_score_pp} pts · +${usd(gap.delta_cost_usd)} · ×${gap.cost_factor}</text>
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
        <td class="num">${pick ? idx(pick.score) : "—"}</td>
        <td class="num">${pick ? minutesText(loopMinutes(pick)) : "—"}</td>
        <td class="num">${slot ? credits(slot.per_task_credits) : "—"}</td>
      </tr>`)
    );
  });
}

/* ---------- the map: intelligence against cost, time or tokens ----------

   Three charts, one frame, the way Artificial Analysis draws them: intelligence up, a
   measure of expense across, a split in each axis, and the top-left quadrant — smarter and
   cheaper, or smarter and quicker — tinted as the place to shop. The dotted line is the Pareto
   line: the variants nothing else beats on both axes at once.

   The board is what we can start. The rest of the market can be drawn behind it for scale,
   as hollow grey dots that never move the Pareto line and never enter a role.

   Switching charts moves the dots rather than redrawing them: each point is a group that
   keeps its identity between renders, and its position is a CSS transform, so the browser
   animates the move. The eye follows one model from cheap-but-slow to fast-but-dear. */

const EFFORT_RANK = { low: 0, medium: 1, high: 2, xhigh: 3, max: 4 };
const EFFORT_NAMES = { low: "Low", medium: "Medium", high: "High", xhigh: "Extra High", max: "Max" };
const loopMinutes = (c) => (c && c.speed ? c.speed.task_minutes : c && c.task_minutes !== undefined ? c.task_minutes : null);

const shortTokens = (v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : `${Math.round(v)}`);
const minutesText = (v) => (v === null || v === undefined ? "—" : `${v < 10 ? v.toFixed(1) : Math.round(v)} min`);

function patienceLevel() {
  return ((state.view && state.view.patience) || []).find((p) => p.id === state.patience) || null;
}

const MAPS = {
  cost: {
    tab: "Cost per task",
    title: "Intelligence against cost per task",
    axis: "COST OF ONE INDEX TASK (USD, LOG SCALE)",
    log: true,
    x: (c) => (c.cost_usd > 0 ? c.cost_usd : null),
    ticks: [0.005, 0.01, 0.03, 0.1, 0.3, 1, 3, 10],
    fmt: (v) => (v < 0.1 ? `$${v.toFixed(3).replace(/0+$/, "")}` : `$${v < 1 ? v.toFixed(2) : v}`),
    split: () => ({ x: 1, label: "$1 a task" }),
    corner: "smarter and cheaper",
    sub: () =>
      "What one Intelligence Index task costs, per effort level. Left of $1 and above the middle " +
      "is where the value is. The loop roles live there; the architect may sit to the right on purpose. " +
      "Each half of the cost axis has its own scale, so $1 sits in the middle.",
  },
  time: {
    tab: "Time per task",
    title: "Intelligence against time per task",
    axis: "TIME PER TASK (MINUTES)",
    log: false,
    x: (c) => loopMinutes(c),
    fmt: (v) => `${v}`,
    split: (domain) => {
      const level = patienceLevel();
      if (level && level.worker !== null) {
        return { x: level.worker, label: `worker ≤ ${level.worker} min`, second: level.scout, secondLabel: `scout ≤ ${level.scout} min` };
      }
      const middle = Math.round((domain[0] + domain[1]) / 2);
      return { x: middle, label: `${middle} min` };
    },
    corner: "smarter and quicker",
    sub: () => {
      const level = patienceLevel();
      return (
        "How long one task takes — decode time, reasoning included. You iterate with the worker and " +
        "the scout, so this is the length of every loop; the architect plans once and may take its time. " +
        (level && level.worker !== null
          ? `The split is the worker's limit at ${level.label.toLowerCase()} patience, the dashed line the scout's; each half of the axis has its own scale.`
          : "No patience limit is set, so the split is the middle of the range.")
      );
    },
  },
  tokens: {
    tab: "Output tokens per task",
    title: "Intelligence against output tokens per task",
    axis: "OUTPUT TOKENS PER INDEX TASK (LOG SCALE)",
    log: true,
    x: (c) => (c.output_tokens > 0 ? c.output_tokens : null),
    ticks: [1000, 3000, 10000, 30000, 100000, 300000],
    fmt: shortTokens,
    split: (domain) => {
      const middle = Math.pow(10, (Math.log10(domain[0]) + Math.log10(domain[1])) / 2);
      const nice = Number(middle.toPrecision(1));
      return { x: nice, label: `${shortTokens(nice)} tokens` };
    },
    corner: "smarter with fewer words",
    sub: () =>
      "How many tokens a model writes to finish one task, reasoning included — the thing both the " +
      "bill and the clock are made of. Fewer tokens for the same score is efficiency you pay for twice.",
  },
};

function renderMapTabs() {
  const box = $("#map-tabs");
  if (!box) return;
  box.innerHTML = Object.entries(MAPS)
    .map(
      ([id, map]) =>
        `<button class="map-tab" role="tab" data-map="${id}" aria-selected="${state.map === id}">${escapeHtml(map.tab)}</button>`
    )
    .join("");
  box.querySelectorAll(".map-tab").forEach((button) => {
    button.addEventListener("click", () => {
      state.map = button.dataset.map;
      store("kvasir.map", state.map);
      hideTip();
      renderMapTabs();
      renderMap(state.view);
    });
  });
}

function paretoOf(points) {
  const ordered = [...points].sort((a, b) => a.x - b.x || b.score - a.score);
  const out = [];
  let best = -Infinity;
  ordered.forEach((p) => {
    if (p.score > best) {
      out.push(p);
      best = p.score;
    }
  });
  return out;
}

function renderMap(view) {
  const svg = $("#scatter");
  if (!svg || !view) return;
  const map = MAPS[state.map] || MAPS.cost;
  $("#map-title").textContent = map.title;
  $("#map-sub").textContent = map.sub();
  const W = 1000;
  const H = 520;
  const pad = { l: 62, r: 24, t: 26, b: 58 };

  const board = view.candidates
    .map((c) => ({ c, id: candidateId(c), x: map.x(c), score: c.score }))
    .filter((p) => p.x !== null && p.x !== undefined);
  const market = state.market
    ? (view.market || [])
        .map((m) => ({ c: m, id: `market|${m.key}`, x: map.x(m), score: m.score, ghost: true }))
        .filter((p) => p.x !== null && p.x !== undefined)
    : [];
  const all = [...board, ...market];
  if (!all.length) {
    svg.innerHTML = "";
    return;
  }

  // The split sits in the middle of both axes, so the four quadrants are four real areas and
  // the attractive one is a quarter of the chart, not a sliver. On y that is the middle of the
  // range, as on the source's own charts. On x each half of the axis is scaled on its own —
  // minimum to split on the left, split to maximum on the right — because a fixed split ($1,
  // the worker's limit) would otherwise land wherever the data happens to put it: at 75% of
  // the width for cost, at 30% for time. The subtitle says so; ordering is never changed.
  const xs = all.map((p) => p.x);
  const ys = all.map((p) => p.score);
  const tf = (v) => (map.log ? Math.log10(v) : v);
  const rawLo = Math.min(...xs);
  const rawHi = Math.max(...xs);
  const domain = [rawLo, rawHi];
  const split = map.split(domain);
  const lo = map.log ? tf(Math.min(rawLo, split.x)) - 0.12 : 0;
  const hi = map.log ? tf(Math.max(rawHi, split.x)) + 0.12 : Math.max(rawHi, split.x) * 1.06;
  const sp = Math.min(Math.max(tf(split.x), lo + 1e-6), hi - 1e-6);
  const half = (W - pad.l - pad.r) / 2;
  const sx = (v) => {
    const u = tf(v);
    return u <= sp ? pad.l + ((u - lo) / (sp - lo)) * half : pad.l + half + ((u - sp) / (hi - sp)) * half;
  };
  const y0 = Math.floor((Math.min(...ys) - 2) / 5) * 5;
  const y1 = Math.ceil((Math.max(...ys) + 2) / 5) * 5;
  const sy = (v) => H - pad.b - ((v - y0) / (y1 - y0)) * (H - pad.t - pad.b);
  const ySplit = Math.round((y0 + y1) / 2);

  const parts = [];
  // Quadrants first, so everything else sits on them.
  const qx = pad.l + half;
  const qy = sy(ySplit);
  parts.push(`<rect class="quad-best" x="${pad.l}" y="${pad.t}" width="${qx - pad.l}" height="${qy - pad.t}"/>`);
  parts.push(`<rect class="quad-worst" x="${qx}" y="${qy}" width="${W - pad.r - qx}" height="${H - pad.b - qy}"/>`);
  parts.push(`<text x="${pad.l + 10}" y="${pad.t + 18}" class="quad-label">${escapeHtml(map.corner)}</text>`);

  // Grid and ticks — per half, since each half has its own scale.
  const ticks = map.log
    ? map.ticks.filter((t) => tf(t) >= lo && tf(t) <= hi)
    : (() => {
        const out = [];
        const stepLeft = split.x <= 3 ? 0.5 : split.x <= 8 ? 1 : 2;
        for (let t = 0; t < split.x - 1e-9; t += stepLeft) out.push(Number(t.toFixed(2)));
        const right = hi - split.x;
        const stepRight = right > 30 ? 10 : right > 12 ? 5 : right > 5 ? 2 : 1;
        out.push(split.x);
        const first = Math.ceil((split.x + stepRight / 2) / stepRight) * stepRight;
        for (let t = first; t <= hi; t += stepRight) out.push(Number(t.toFixed(2)));
        return out;
      })();
  ticks.forEach((tick) => {
    const x = sx(tick);
    parts.push(`<line x1="${x}" y1="${pad.t}" x2="${x}" y2="${H - pad.b}" class="grid"/>`);
    parts.push(`<text x="${x}" y="${H - pad.b + 22}" class="tick-label" text-anchor="middle">${escapeHtml(map.fmt(tick))}</text>`);
  });
  for (let score = y0; score <= y1; score += 5) {
    const y = sy(score);
    parts.push(`<line x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}" class="grid"/>`);
    parts.push(`<text x="${pad.l - 12}" y="${y + 4}" class="tick-label" text-anchor="end">${score}</text>`);
  }
  // The splits, named where they meet the axis.
  parts.push(`<line x1="${qx}" y1="${pad.t}" x2="${qx}" y2="${H - pad.b}" class="split"/>`);
  parts.push(`<line x1="${pad.l}" y1="${qy}" x2="${W - pad.r}" y2="${qy}" class="split"/>`);
  parts.push(`<text x="${qx + 6}" y="${H - pad.b - 8}" class="split-label">${escapeHtml(split.label)}</text>`);
  if (split.second !== undefined && split.second !== null) {
    const x2 = sx(split.second);
    parts.push(`<line x1="${x2}" y1="${pad.t}" x2="${x2}" y2="${H - pad.b}" class="split second"/>`);
    parts.push(`<text x="${x2 + 6}" y="${H - pad.b - 24}" class="split-label">${escapeHtml(split.secondLabel)}</text>`);
  }
  parts.push(`<text x="${pad.l - 44}" y="${(pad.t + H - pad.b) / 2}" class="axis-label" transform="rotate(-90 ${pad.l - 44} ${(pad.t + H - pad.b) / 2})" text-anchor="middle">INTELLIGENCE INDEX</text>`);
  parts.push(`<text x="${(pad.l + W - pad.r) / 2}" y="${H - 10}" class="axis-label" text-anchor="middle">${escapeHtml(map.axis)}</text>`);

  // Pareto line over the board only — what we can actually start — and only over measured
  // points: a variant drawn at its lower-bound time is an estimate, not a place on the line.
  const front = paretoOf(board.filter((p) => !(state.map === "time" && p.c.speed && p.c.speed.task_minutes_floor_from)));
  if (front.length > 1) {
    parts.push(`<polyline class="pareto" points="${front.map((p) => `${sx(p.x)},${sy(p.score)}`).join(" ")}"/>`);
  }
  // Family lines: one model's efforts in order, drawn under the dots.
  families(view).forEach((family) => {
    const hue = familyHue(family.key);
    if (!hue) return;
    const path = family.variants
      .map((v) => ({ v, x: map.x(v) }))
      .filter((p) => p.x !== null && p.x !== undefined)
      .map((p) => `${sx(p.x)},${sy(p.v.score)}`);
    if (path.length > 1) parts.push(`<polyline points="${path.join(" ")}" fill="none" stroke="${hue}" stroke-width="2" opacity=".85"/>`);
  });
  svg.querySelectorAll(":scope > :not(g.pts)").forEach((el) => el.remove());
  svg.insertAdjacentHTML("afterbegin", parts.join(""));

  // Points: persistent groups, moved by transform.
  let layer = svg.querySelector("g.pts");
  if (!layer) {
    layer = document.createElementNS("http://www.w3.org/2000/svg", "g");
    layer.setAttribute("class", "pts");
    svg.append(layer);
  } else {
    svg.append(layer); // keep it on top of the freshly drawn frame
  }
  const picks = {};
  const current = plan();
  Object.entries((current && current.roles) || {}).forEach(([role, slot]) => {
    if (slot.pick) picks[candidateId(slot.pick)] = role;
  });
  const onFront = new Set(front.map((p) => p.id));
  const colour = { architect: "#7c5cff", worker: "#38e1c4", scout: "#8b97a8" };

  // Labels: role picks always, Pareto points when there is room. Placed greedily so they do
  // not print over each other; a dot without a label still answers to hover.
  // Dots are obstacles too: a label printed over the next point on the Pareto line hid it.
  const placed = all.map((p) => ({ x0: sx(p.x) - 6, x1: sx(p.x) + 6, y0: sy(p.score) - 6, y1: sy(p.score) + 6 }));
  const fits = (box) =>
    box.x0 >= pad.l && box.x1 <= W - pad.r && box.y0 >= pad.t &&
    !placed.some((o) => box.x0 < o.x1 && box.x1 > o.x0 && box.y0 < o.y1 && box.y1 > o.y0);
  const labelFor = (p, text, weight) => {
    const x = sx(p.x);
    const y = sy(p.score);
    const width = text.length * (weight ? 7.4 : 6.6) + 4;
    const tries = [
      { dx: 11, dy: 4, anchor: "start" },
      { dx: -11, dy: 4, anchor: "end" },
      { dx: 0, dy: -12, anchor: "middle" },
      { dx: 0, dy: 20, anchor: "middle" },
    ];
    for (const t of tries) {
      const left = t.anchor === "start" ? x + t.dx : t.anchor === "end" ? x + t.dx - width : x - width / 2;
      const box = { x0: left, x1: left + width, y0: y + t.dy - 12, y1: y + t.dy + 3 };
      if (fits(box)) {
        placed.push(box);
        return t;
      }
    }
    // A role pick is always named, even over a neighbour: it is the answer the chart is for.
    if (weight) return x > W - pad.r - width - 12 ? tries[1] : tries[0];
    return null;
  };
  // Picks claim their label space first.
  const order = [...all].sort((a, b) => (picks[b.id] ? 2 : onFront.has(b.id) ? 1 : 0) - (picks[a.id] ? 2 : onFront.has(a.id) ? 1 : 0));
  const seen = new Set();
  order.forEach((p) => {
    seen.add(p.id);
    const role = p.ghost ? null : picks[p.id];
    const hue = p.ghost ? null : familyHue(p.c.key);
    const selected = state.selected === p.id;
    let g = layer.querySelector(`g.pt[data-id="${CSS.escape(p.id)}"]`);
    const fresh = !g;
    if (fresh) {
      g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("class", "pt");
      g.dataset.id = p.id;
      layer.append(g);
    }
    const fill = p.ghost ? "none" : hue || (role ? colour[role] : "#3a4257");
    const radius = role ? 7 : p.ghost ? 4 : hue ? 6 : 4.5;
    const floor = !p.ghost && state.map === "time" && p.c.speed && p.c.speed.task_minutes_floor_from;
    let label = "";
    if (role) {
      const t = labelFor(p, p.c.label, true);
      if (t) label = `<text x="${t.dx}" y="${t.dy}" text-anchor="${t.anchor}" class="pt-label pick" fill="${colour[role]}">${escapeHtml(p.c.label)}</text>`;
    } else if (!p.ghost && (onFront.has(p.id) || hue)) {
      const text = hue ? p.c.effort_label : p.c.label;
      const t = labelFor(p, text, false);
      if (t) label = `<text x="${t.dx}" y="${t.dy}" text-anchor="${t.anchor}" class="pt-label" ${hue ? `fill="${hue}"` : ""}>${escapeHtml(text)}</text>`;
    }
    g.innerHTML = `
      <circle r="${radius}" fill="${floor ? "none" : fill}" class="${p.ghost ? "ghost" : role || hue ? "ring" : "dot"}"
        ${floor ? `stroke="${hue || (role ? colour[role] : "#8b97a8")}" stroke-width="2" stroke-dasharray="2 2"` : ""}/>
      ${selected ? `<circle r="${radius + 3.5}" fill="none" stroke="#e8ecf1" stroke-width="1.8" pointer-events="none"/>` : ""}
      ${label}
      <circle class="hit" r="11" fill="transparent" ${p.ghost ? "" : `data-id="${escapeHtml(p.id)}" tabindex="0" role="button"`}
        aria-label="${escapeHtml(`${p.c.label}: ${idx(p.score)}, ${map.fmt(p.x)}`)}"/>`;
    g.dataset.x = sx(p.x);
    g.dataset.y = sy(p.score);
    g.dataset.ghost = p.ghost ? "1" : "";
    if (fresh) {
      g.style.transition = "none";
      g.style.transform = `translate(${sx(p.x)}px, ${sy(p.score)}px)`;
      g.getBoundingClientRect(); // commit the start position before transitions resume
      g.style.transition = "";
    } else {
      g.style.transform = `translate(${sx(p.x)}px, ${sy(p.score)}px)`;
    }
  });
  layer.querySelectorAll("g.pt").forEach((g) => {
    if (!seen.has(g.dataset.id)) g.remove();
  });

  parts.length = 0;
  svg.insertAdjacentHTML(
    "beforeend",
    `<g id="crosshair" visibility="hidden" pointer-events="none">
      <line id="cross-x" class="cross"/><line id="cross-y" class="cross"/>
    </g>`
  );
  svg.dataset.padL = pad.l;
  svg.dataset.baseY = H - pad.b;
  const keyMarket = $("#key-market");
  if (keyMarket) keyMarket.hidden = !market.length;
}

/* ---------- map hover: one tooltip, one crosshair ---------- */

function showTip(hit) {
  const svg = $("#scatter");
  const tip = $("#scatter-tip");
  const g = hit.closest("g.pt");
  if (!svg || !tip || !g) return;
  const id = g.dataset.id;
  const candidate = id.startsWith("market|")
    ? (state.view.market || []).find((m) => `market|${m.key}` === id)
    : findCandidate(id);
  if (!candidate) return;
  const cx = Number(g.dataset.x);
  const cy = Number(g.dataset.y);

  const cross = svg.querySelector("#crosshair");
  const lineX = svg.querySelector("#cross-x");
  const lineY = svg.querySelector("#cross-y");
  lineX.setAttribute("x1", cx); lineX.setAttribute("x2", cx);
  lineX.setAttribute("y1", cy); lineX.setAttribute("y2", svg.dataset.baseY);
  lineY.setAttribute("x1", svg.dataset.padL); lineY.setAttribute("x2", cx);
  lineY.setAttribute("y1", cy); lineY.setAttribute("y2", cy);
  cross.setAttribute("visibility", "visible");

  const ghost = Boolean(g.dataset.ghost);
  const minutes = loopMinutes(candidate);
  const floor = !ghost && candidate.speed && candidate.speed.task_minutes_floor_from;
  const roles = ghost ? [] : rolesPickingNow(candidate);
  const onFrontier = !ghost && frontierIds().has(candidateId(candidate));
  tip.innerHTML = `
    <b>${escapeHtml(candidate.label)}</b>
    <span>${idx(candidate.score)} Intelligence · ${
      candidate.cost_usd ? `${credits(taskCredits(candidate, state.view))} credits a task` : "not priced"
    }</span>
    <span>${
      minutes === null || minutes === undefined
        ? "time per task not measured"
        : floor
        ? `at least ${minutesText(minutes)} a task — untimed, ${escapeHtml(EFFORT_NAMES[floor] || floor)} takes that long`
        : `${minutesText(minutes)} a task`
    }${candidate.output_tokens ? ` · ${shortTokens(candidate.output_tokens)} tokens` : ""}</span>
    ${ghost ? `<span class="dim">${escapeHtml(candidate.reason || "not available to us")}</span>` : ""}
    ${roles.length ? `<span class="cyan">today's ${escapeHtml(roles.join(" + "))}</span>` : ""}
    ${!roles.length && onFrontier ? '<span class="cyan">on the cost frontier</span>' : ""}`;
  const rect = svg.getBoundingClientRect();
  const scale = rect.width / 1000;
  const left = cx * scale;
  tip.style.left = `${Math.min(rect.width - 12, Math.max(12, left))}px`;
  tip.style.top = `${cy * scale}px`;
  tip.classList.toggle("flip", left > rect.width * 0.62);
  tip.hidden = false;
}

function hideTip() {
  const tip = $("#scatter-tip");
  const cross = $("#crosshair");
  if (tip) tip.hidden = true;
  if (cross) cross.setAttribute("visibility", "hidden");
}

/* ---------- variant detail: what a clicked dot opens ---------- */

function rolesPickingNow(candidate) {
  const current = plan();
  const out = [];
  Object.entries((current && current.roles) || {}).forEach(([id, slot]) => {
    if (slot.pick && candidateId(slot.pick) === candidateId(candidate)) out.push(id);
  });
  return out;
}

function renderChartDetail() {
  const box = $("#chart-detail");
  if (!box) return;
  const candidate = findCandidate(state.selected);
  if (!candidate) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  const onFrontier = frontierIds().has(candidateId(candidate));
  const dominator = onFrontier ? null : dominatorOf(candidate);
  const roles = rolesPickingNow(candidate);
  const family = state.view.candidates
    .filter((c) => c.key === candidate.key)
    .sort((a, b) => (a.cost_uusd ?? 0) - (b.cost_uusd ?? 0));

  const standing =
    roles.length > 0
      ? `<span class="badge">today's ${roles.join(" + ")}</span>`
      : "";
  const frontierLine = onFrontier
    ? `<span class="badge ok">on the value frontier</span>`
    : dominator
    ? `<span class="badge bad" title="a cheaper variant already scores at least as much">beaten by ${escapeHtml(
        dominator.label
      )}</span>`
    : "";

  box.innerHTML = `
    <div class="detail-head">
      <div>
        <div class="eyebrow">Variant</div>
        <h3>${escapeHtml(candidate.label)}</h3>
      </div>
      <button class="toggle" id="detail-close" aria-label="Close">×</button>
    </div>
    <div class="badges">
      <span class="badge">${idx(candidate.score)} Intelligence</span>
      <span class="badge">${
        candidate.priced ? `${credits(taskCredits(candidate, state.view))} credits / task` : "not priced yet"
      }</span>
      <span class="badge">${
        loopMinutes(candidate) === null || loopMinutes(candidate) === undefined
          ? "time not measured"
          : `${minutesText(loopMinutes(candidate))} a task`
      }</span>
      ${candidate.output_tokens ? `<span class="badge">${num(candidate.output_tokens)} tokens out</span>` : ""}
      ${driftBadge(candidate.drift)}
      ${copilotBadge(candidate.copilot)}
      ${frontierLine}
      ${standing}
    </div>
    ${
      dominator && !onFrontier
        ? `<p class="why">A cheaper variant (${escapeHtml(
            dominator.label
          )}) reaches ${idx(dominator.score)} for ${usd(dominator.cost_usd)} — this one only makes
           sense when you specifically want more than that and accept paying for it.</p>`
        : ""
    }
    ${
      family.length > 1
        ? `<div class="family">
             <div class="eyebrow">Every ${escapeHtml(
               candidate.label.split(" · ")[0]
             )} effort level, cheapest first</div>
             ${family
               .map((variant) => {
                 const id = candidateId(variant);
                 const here = id === candidateId(candidate);
                 const vFrontier = frontierIds().has(id);
                 return `<button class="family-row ${here ? "here" : ""}" data-id="${escapeHtml(id)}">
                   <span class="headline">${escapeHtml(variant.effort_label)}${vFrontier ? ' <i class="fmark cyan">frontier</i>' : ""}</span>
                   <span class="mono">${idx(variant.score)} · ${
                     variant.priced ? `${credits(taskCredits(variant, state.view))} cr` : "unpriced"
                   } · ${minutesText(loopMinutes(variant))}</span>
                 </button>`;
               })
               .join("")}
           </div>`
        : ""
    }`;
  box.hidden = false;

  $("#detail-close").addEventListener("click", () => selectVariant(null));
  box.querySelectorAll(".family-row").forEach((row) => {
    row.addEventListener("click", () => toggleVariant(row.getAttribute("data-id")));
  });
}

/* ---------- value ladder ---------- */

function renderLadder(view) {
  const box = $("#ladder");
  box.innerHTML = "";
  const onFrontier = frontierIds();

  /* Frontier only (the default reading), or every loaded variant, cheapest first — the
     frontier rungs keep their verdict styling, the dominated ones say what beats them. */
  const rows = state.everyVariant
    ? view.candidates
        .filter((c) => c.priced && c.cost_usd > 0)
        .sort((a, b) => (a.cost_uusd ?? 0) - (b.cost_uusd ?? 0))
        .map((candidate) => ({
          id: candidateId(candidate),
          candidate,
          rung: view.ladder.find((r) => `${r.key}|${r.effort}` === candidateId(candidate)) || null,
        }))
    : view.ladder.map((rung) => ({
        id: `${rung.key}|${rung.effort}`,
        candidate: null,
        rung,
      }));

  rows.forEach(({ id, candidate, rung }) => {
    const selected = state.selected === id;
    const cls = ["rung", rung ? rung.verdict || "fair" : "off", selected ? "here" : ""]
      .filter(Boolean)
      .join(" ");
    if (!rung) {
      /* Off the frontier: dominated by the cheapest frontier variant that scores as much. */
      const dominator = dominatorOf(candidate);
      box.append(
        tag(`<button class="${cls}" data-id="${escapeHtml(id)}">
          <div><span class="headline">${escapeHtml(candidate.label)}</span>
            <div class="step">off the frontier — ${escapeHtml(dominator ? dominator.label : "a cheaper variant")} scores at least as much for less</div></div>
          <div class="price">${idx(candidate.score)} · ${usd(candidate.cost_usd)}</div>
        </button>`)
      );
      return;
    }
    /* The cheapest frontier rung has no step before it, so it introduces the ladder instead.
       In every-variant mode the same rule holds: no verdict field means no step was priced. */
    if (!rung.verdict) {
      box.append(
        tag(`<button class="${cls}" data-id="${escapeHtml(id)}">
          <div><span class="headline">${escapeHtml(rung.label)}</span>
            <div class="step">starting point — as cheap as it gets</div></div>
          <div class="price">${idx(rung.score)} · ${usd(rung.cost_usd)}</div>
        </button>`)
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
      tag(`<button class="${cls}" data-id="${escapeHtml(id)}">
        <div><span class="headline">${escapeHtml(rung.label)}</span>
          <div class="step">from ${escapeHtml(rung.from_label)}: +${rung.delta_score_pp} pts for +${usd(rung.delta_cost_usd)} → <b>${usd(rung.usd_per_pp)} a point</b> — ${message}</div></div>
        <div class="price">${idx(rung.score)} · ${usd(rung.cost_usd)}</div>
      </button>`)
    );
  });

  box.querySelectorAll(".rung").forEach((rung) => {
    // The ladder lives on its own tab now; a rung opens its variant on the cost map.
    rung.addEventListener("click", () => {
      state.map = "cost";
      renderMapTabs();
      showPanel("map", { scroll: true });
      selectVariant(rung.getAttribute("data-id"));
    });
  });
}

/* ---------- sortable tables ----------

   Two of the four tables on this page are data you scan (drift, all models); the other two
   carry an order that means something (the task catalogue is grouped by role, the budget breakdown reads
   architect-worker-scout) and sorting them would destroy the point. So this is opt-in.

   Cells carry `data-sort` with the raw value, because the rendered text is formatted for
   reading — "$0.075", "59–88", "+3.8" — and sorting the formatting gives nonsense. An empty
   `data-sort` means "no value": those rows sink to the bottom in both directions, so
   ascending by score never opens with a wall of models nobody benchmarked. */

const SORT_STATE = {};

function sortValue(cell) {
  const raw = cell.dataset.sort;
  if (raw === undefined) return cell.textContent.trim().toLowerCase();
  if (raw === "") return null;
  const num = Number(raw);
  return Number.isNaN(num) ? raw.toLowerCase() : num;
}

function applySort(tableId) {
  const table = document.getElementById(tableId);
  const state = SORT_STATE[tableId];
  if (!table || !state || !table.tBodies[0]) return;
  const body = table.tBodies[0];
  [...body.rows]
    .sort((a, b) => {
      const left = sortValue(a.cells[state.index]);
      const right = sortValue(b.cells[state.index]);
      if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1;
      if (left === right) return 0;
      return (left > right ? 1 : -1) * state.dir;
    })
    .forEach((row) => body.append(row));
  [...table.tHead.rows[0].cells].forEach((th, index) => {
    if (th.dataset.nosort !== undefined) return;
    th.setAttribute(
      "aria-sort",
      index === state.index ? (state.dir === 1 ? "ascending" : "descending") : "none"
    );
  });
}

function makeSortable(tableId, fallback) {
  const table = document.getElementById(tableId);
  if (!table) return;
  if (!SORT_STATE[tableId] && fallback) SORT_STATE[tableId] = fallback;
  if (!table.dataset.sortable) {
    table.dataset.sortable = "1";
    [...table.tHead.rows[0].cells].forEach((th, index) => {
      if (th.dataset.nosort !== undefined) return;
      th.tabIndex = 0;
      th.setAttribute("role", "button");
      th.setAttribute("aria-sort", "none");
      const toggle = () => {
        const current = SORT_STATE[tableId];
        // Numbers open large-first, names open A-Z: the useful end of each, first click.
        const dir =
          current && current.index === index ? -current.dir : th.classList.contains("num") ? -1 : 1;
        SORT_STATE[tableId] = { index, dir };
        applySort(tableId);
      };
      th.addEventListener("click", toggle);
      th.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggle();
        }
      });
    });
  }
  applySort(tableId);
}

/* Which role, if any, this model fills at the selected tier — the line back from a table of
   numbers to the decision the page exists to make. */
function roleChips(key, effort) {
  const current = plan();
  if (!current || !current.roles) return "";
  return Object.entries(current.roles)
    .filter(
      ([, slot]) =>
        slot.pick && slot.pick.key === key && (effort === undefined || slot.pick.effort === effort)
    )
    .map(([role]) => {
      const tier = (state.view.tiers || []).find((t) => t.id === role);
      return tier
        ? `<span class="tier-chip ${tier.accent}" style="margin-left:.4rem">${escapeHtml(tier.name)}</span>`
        : "";
    })
    .join("");
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

function renderDrift(drift, history, source) {
  // The score column and the sparklines come from different endpoints of the same site, and
  // since September they fail apart: scores went key-only, the run history stayed open. If
  // half the section is frozen, the section has to say which half.
  const stale = $("#drift-stale");
  if (stale) {
    // Two separate conditions: the source failing its last poll, and the data being old
    // enough to stop deciding anything. Either is worth a banner; neither is worth one
    // once the source has recovered and the numbers are current again.
    const failing = source && (source.failing || source.last_error);
    const untrusted = state.view && state.view.drift_trusted === false;
    const error = failing ? source.last_error : null;
    stale.hidden = !(failing || untrusted);
    if (failing || untrusted) {
      const why = !error
        ? "the last reading is older than the drift check trusts"
        : /api key|401|403/i.test(error)
        ? "the scores endpoint now requires an API key"
        : "the scores endpoint is failing";
      const suspended =
        state.view && state.view.drift_trusted === false
          ? " The drift veto is suspended while the scores are this old, so the verdict above is " +
            "decided on cost and score alone."
          : "";
      stale.textContent =
        `Scores frozen at ${(source.captured_at || "").slice(0, 16).replace("T", " ")} — ${why}. ` +
        "The sparklines, Δ7d and min–max below come from the run history, which is still current." +
        suspended;
    }
  }
  const note = $("#drift-refreshed");
  if (note) {
    const every =
      history && history.interval_minutes
        ? `every ${Math.round(history.interval_minutes / 60)} h`
        : "";
    note.textContent =
      history && history.last_run
        ? ` Run history pulled ${ago(history.last_run)}, ${every}.`
        : " Run history has not been pulled yet.";
  }
  const body = $("#drift tbody");
  body.innerHTML = "";

  // A model can look excellent here and still be unusable at work. Saying so in the row
  // stops the table from arguing for a model the verdict is not allowed to pick.
  const view = state.view || {};
  const offBoard = new Map((view.excluded || []).map((c) => [c.key, c.unavailable_reason]));
  // Anything Copilot sells, benchmarked or not. A drift row in neither list is a model this
  // page cannot put to work at all — retired from Copilot, or never carried.
  const sold = new Set([
    ...(view.candidates || []).map((c) => c.key),
    ...(view.excluded || []).filter((c) => c.copilot).map((c) => c.key),
    ...(view.copilot_only || []).map((c) => c.key),
  ]);

  drift.forEach((row) => {
    const arrow = row.trend === "up" ? "↑ rising" : row.trend === "down" ? "↓ falling" : "→ steady";
    const trendRank = row.trend === "up" ? 1 : row.trend === "down" ? -1 : 0;
    const cls = row.trend === "down" ? "violet" : row.trend === "up" ? "cyan" : "dim";
    const delta =
      row.delta_7d === null || row.delta_7d === undefined
        ? "—"
        : `${row.delta_7d > 0 ? "+" : ""}${row.delta_7d}`;
    const deltaCls = row.delta_7d < 0 ? "violet" : row.delta_7d > 0 ? "cyan" : "dim";
    const spread =
      row.min_7d === null || row.min_7d === undefined || row.max_7d === null || row.max_7d === undefined
        ? ""
        : row.max_7d - row.min_7d;
    const reason = offBoard.get(row.key) || (sold.has(row.key) ? null : "not in Copilot");
    const marks = [
      row.stale ? "· not refreshed" : "",
      reason ? `· ${reason}` : "",
    ]
      .filter(Boolean)
      .join(" ");
    body.append(
      tag(`<tr>
        <td data-sort="${escapeHtml(row.label)}">${escapeHtml(row.label)}${roleChips(row.key)}
          ${marks ? `<span class="dim mono" style="font-size:.68rem"> ${escapeHtml(marks)}</span>` : ""}</td>
        <td class="num" data-sort="${row.score ?? ""}"><b>${row.score === null ? "—" : Math.round(row.score)}</b></td>
        <td data-nosort>${sparkline(row.points, row.delta_7d)}</td>
        <td class="num ${deltaCls}" data-sort="${row.delta_7d ?? ""}">${delta}</td>
        <td class="num dim" data-sort="${spread}">${row.min_7d ?? "—"}–${row.max_7d ?? "—"}</td>
        <td class="${cls} mono" style="font-size:.78rem" data-sort="${trendRank}">${arrow}</td>
      </tr>`)
    );
  });
  makeSortable("drift", { index: 1, dir: -1 });
}

/* ---------- all models: score, price and time in one table ----------

   This used to be two tables — "how it feels" and "Copilot prices" — that repeated each
   other's columns. One row per variant now, because the interesting fact lives between
   efforts of one model rather than between models. The time filter uses the same ceilings as
   the patience switch, so the two speak one vocabulary. */

function timeFilters() {
  return [null, ...clockTicks()];
}

function renderWaitFilter() {
  const box = $("#wait-filter");
  if (!box) return;
  box.innerHTML = timeFilters()
    .map(
      (limit) =>
        `<button class="toggle" data-limit="${limit ?? ""}" aria-pressed="${state.waitFilter === limit}">${
          limit === null ? "Any time" : `≤ ${limit} min`
        }</button>`
    )
    .join("");
  box.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      const raw = button.getAttribute("data-limit");
      state.waitFilter = raw === "" ? null : Number(raw);
      renderWaitFilter();
      renderModels(state.view);
    });
  });
}

function renderModels(view) {
  const body = $("#models tbody");
  if (!body) return;
  body.innerHTML = "";

  // Everything GitHub sells us belongs here, including the models the organisation has
  // switched off — their numbers are facts, and their absence from the verdict is a choice
  // worth showing next to them.
  const rows = [...view.candidates, ...(view.excluded || [])].filter((candidate) => {
    if (state.waitFilter === null) return true;
    const minutes = loopMinutes(candidate);
    return minutes !== null && minutes !== undefined && minutes <= state.waitFilter;
  });

  rows.forEach((candidate) => {
    const minutes = loopMinutes(candidate);
    const floor = candidate.speed && candidate.speed.task_minutes_floor_from;
    const first = firstAnswer(candidate);
    const cr = taskCredits(candidate, view);
    const speed = candidate.speed || {};
    const drift = candidate.drift;
    const copilot = candidate.copilot;
    // A loop under two minutes keeps you in the flow; past six you have gone to do something else.
    const feel = !minutes ? "" : minutes < 2 ? "stay in the flow" : minutes <= 6 ? "a coffee" : "come back later";
    const marks = [
      candidate.available === false ? candidate.unavailable_reason : "",
      candidate.deprecated ? "retired by its vendor" : "",
    ].filter(Boolean);
    body.append(
      tag(`<tr class="${candidate.available === false ? "off" : ""}">
        <td data-sort="${escapeHtml(candidate.label)}">${escapeHtml(candidate.label)}${roleChips(
          candidate.key,
          candidate.effort
        )}${
          marks.length
            ? `<span class="dim" style="font-size:.75rem"> · ${escapeHtml(marks.join(" · "))}</span>`
            : ""
        }</td>
        <td class="num" data-sort="${candidate.score ?? ""}">${idx(candidate.score)}</td>
        <td class="num dim" data-sort="${candidate.terminal_bench ?? ""}">${
          candidate.terminal_bench === null || candidate.terminal_bench === undefined
            ? "—"
            : `${candidate.terminal_bench.toFixed(0)}%`
        }</td>
        <td class="num" data-sort="${cr ?? ""}">${
          cr === null ? '<span class="dim" title="Artificial Analysis has not priced it">not priced</span>' : credits(cr)
        }</td>
        <td class="num" data-sort="${minutes ?? ""}" ${
          floor ? `title="Not timed — ${escapeHtml(EFFORT_NAMES[floor] || floor)} already takes this long"` : ""
        }>${floor ? "≥ " : ""}${minutesText(minutes)}</td>
        <td class="wait-cell" data-nosort>${
          minutes
            ? `${bar(clockX(minutes), "violet-fill")}<span class="dim feel">${feel}</span>`
            : '<span class="dim feel">not timed</span>'
        }</td>
        <td class="num dim" data-sort="${first ?? ""}">${secs(first)}</td>
        <td class="num" data-sort="${speed.tokens_per_second ?? ""}">${
          speed.tokens_per_second ? Math.round(speed.tokens_per_second) : "—"
        }</td>
        <td class="num" data-sort="${drift && drift.score !== null ? drift.score : ""}">${
          drift && drift.score !== null ? Math.round(drift.score) : "—"
        }</td>
        <td class="num" data-sort="${copilot ? copilot.output_usd : ""}">${
          copilot ? `$${copilot.input_usd} / $${copilot.output_usd}` : "—"
        }</td>
      </tr>`)
    );
  });

  // Sold by GitHub, but nobody has scored it at a named effort: its price is a fact, its
  // quality is not known. Only shown while no time filter is on — it has no time to filter.
  if (state.waitFilter === null) {
    (view.copilot_only || []).forEach((model) => {
      body.append(
        tag(`<tr class="off">
          <td data-sort="${escapeHtml(model.label)}">${escapeHtml(model.label)}
            <span class="dim" style="font-size:.75rem"> · not scored at a named effort</span></td>
          <td class="num" data-sort="">—</td><td class="num" data-sort="">—</td>
          <td class="num" data-sort="">—</td><td class="num" data-sort="">—</td><td></td>
          <td class="num" data-sort="">—</td><td class="num" data-sort="">—</td>
          <td class="num" data-sort="${model.drift ?? ""}">${model.drift ? Math.round(model.drift) : "—"}</td>
          <td class="num" data-sort="${model.output_usd ?? ""}">$${model.input_usd} / $${model.output_usd}</td>
        </tr>`)
      );
    });
  }

  const note = $("#models-note");
  if (note) {
    const timed = rows.filter((c) => loopMinutes(c) !== null && loopMinutes(c) !== undefined).length;
    note.textContent =
      `${rows.length} variants${state.waitFilter === null ? "" : ` finish a task within ${state.waitFilter} min`}; ` +
      `${timed} of them with a measured time per task. Every number comes from Artificial Analysis, run ` +
      `on their own hardware, except drift (AI Stupid Level, at each provider's default effort) and the ` +
      `Copilot price. Time per task is decode time with reasoning included; "≥" marks an effort nobody ` +
      `timed, shown at the time its slower-thinking sibling below already takes. A model with no time ` +
      `at all is not slow — nobody has timed it. Coding is Terminal-Bench 4.0, shown for comparison and ` +
      `never used to decide.`;
  }
  makeSortable("models", { index: 1, dir: -1 });
}

/* ---------- footer ---------- */

function renderMethod(view) {
  const method = $("#method");
  const thresholds = view.thresholds;
  const assumptions = view.assumptions;
  const disabled = (view.disabled_by_config || []).join(", ");
  const levels = (view.patience || [])
    .map((p) =>
      p.scout === null && p.worker === null
        ? `${p.label} (no limit)`
        : `${p.label} (scout ${ceilingText(p.scout)}, worker ${ceilingText(p.worker)})`
    )
    .join(", ");
  method.innerHTML = `
    <div>Quality, cost and time come from Artificial Analysis — Intelligence Index
      v${escapeHtml(view.benchmark_version || "?")}, the cost of one index task, and the time one task
      takes — always for the effort level named on the card, and all from the same runs.
      Drift comes from AI Stupid Level and acts as a veto rather than another number in an average: a
      model on the way down loses to a comparable model that is holding steady.</div>
    <div>Roles are filled inside the selected tier's monthly credit budget, split
      ${Math.round(assumptions.budget_shares.architect * 100)}/${Math.round(assumptions.budget_shares.worker * 100)}/${Math.round(assumptions.budget_shares.scout * 100)}:
      the architect takes the best model its share affords, the worker climbs the value ladder while
      a point costs at most $${thresholds.fair_usd_per_pp.toFixed(2)}, the scout takes bargains only
      (at most $${thresholds.bargain_usd_per_pp.toFixed(2)} a point). Then the unused credits are spent,
      architect first, up to ${Math.round(assumptions.target_utilisation * 100)}% of the tier. A lower
      role never costs more per task, or scores more, than the role above it.</div>
    <div>Patience sets the longest a loop role may take over one task — Artificial Analysis's time per
      index task, reasoning included: ${escapeHtml(levels)}. You iterate with the worker and the scout,
      so one slow loop makes the whole session slow; the architect plans once and is never on this
      clock. A variant nobody timed is not treated as slow, unless a lower effort of the same model
      already takes longer than the limit.</div>
    <div>The board is limited to models we can actually start: a model has to appear on GitHub's
      Copilot pricing page, and not be one this organisation has switched off
      (${escapeHtml(disabled || "none")}). A model Artificial Analysis has scored but not yet priced is
      shown but never planned. Anything else is collected and archived, but never recommended — the
      switch above the verdict opens the full board so the cost of that restriction stays visible.</div>
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

function renderAll({ animate = false } = {}) {
  const view = state.view;
  if (!view) return;
  renderTabs();
  const current = plan();
  renderTierTabs(view);
  renderPatienceTabs(view);
  renderFreshness(view.sources);
  renderVerdicts(view, animate);
  renderBudget(view, animate);
  renderGaps((current && current.gaps) || []);
  renderTasks(view);
  hideTip();
  renderMapTabs();
  renderMap(view);
  renderFamilyPicker(view);
  renderLadder(view);
  /* The panel quotes today's role picks, so it follows the tier switch and every refresh. */
  renderChartDetail();
  renderDrift(view.drift, view.drift_history, view.sources && view.sources.stupidlevel);
  renderWaitFilter();
  renderModels(view);
  renderMethod(view);
  showPanel(state.panel || storedPanel() || PANELS[0].id);
}

async function load({ animate = false } = {}) {
  const response = await fetch(`/api/view${state.showAll ? "?all=1" : ""}`, { cache: "no-store" });
  const view = await response.json();
  state.view = view;

  const plans = view.plans || {};
  if (!plans[state.tier]) {
    const remembered = stored(TIER_STORAGE_KEY);
    state.tier = remembered && plans[remembered] ? remembered : view.default_tier;
  }
  if (!MAPS[state.map]) {
    // A link can name the chart (?map=time), so a colleague lands on the one being discussed.
    const linked = new URLSearchParams(location.search).get("map");
    const remembered = stored("kvasir.map");
    state.map = MAPS[linked] ? linked : MAPS[remembered] ? remembered : "cost";
    if (new URLSearchParams(location.search).get("market") === "1") {
      state.market = true;
      const button = $("#toggle-market");
      button.setAttribute("aria-pressed", "true");
      button.textContent = "Only what we can start";
    }
  }
  const levels = (view.patience || []).map((p) => p.id);
  if (!levels.includes(state.patience)) {
    const remembered = stored(PATIENCE_STORAGE_KEY);
    state.patience = levels.includes(remembered) ? remembered : view.default_patience;
  }

  if (!view.ready) {
    $("#verdict-sub").textContent =
      "Collecting from the sources — this page reloads itself every 5 minutes.";
  }
  renderAll({ animate: animate && !reducedMotion() });
}

$("#toggle-all").addEventListener("click", (event) => {
  state.showAll = !state.showAll;
  event.currentTarget.setAttribute("aria-pressed", String(state.showAll));
  event.currentTarget.textContent = state.showAll
    ? "Only what we can run"
    : "Show models we cannot run";
  load();
});

/* The market is context, not choice: it draws behind the board and changes no verdict — the
   switch above the cards is the one that opens the board itself. */
$("#toggle-market").addEventListener("click", (event) => {
  state.market = !state.market;
  event.currentTarget.setAttribute("aria-pressed", String(state.market));
  event.currentTarget.textContent = state.market ? "Only what we can start" : "Show the rest of the market";
  hideTip();
  renderMap(state.view);
});

/* One switch widens the ladder to every variant; clicks on dots and rungs open the shared
   detail panel. Delegation survives the re-renders. */
$("#toggle-ladder").addEventListener("click", (event) => {
  state.everyVariant = !state.everyVariant;
  event.currentTarget.setAttribute("aria-pressed", String(state.everyVariant));
  event.currentTarget.textContent = state.everyVariant ? "Frontier only" : "Show every variant";
  renderLadder(state.view);
});

const scatter = $("#scatter");
scatter.addEventListener("click", (event) => {
  const hit = event.target.closest("[data-id]");
  if (hit) toggleVariant(hit.getAttribute("data-id"));
});
scatter.addEventListener("keydown", (event) => {
  const hit = event.target.closest("[data-id]");
  if (hit && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    toggleVariant(hit.getAttribute("data-id"));
  }
});
scatter.addEventListener("pointerover", (event) => {
  const hit = event.target.closest("circle.hit");
  if (hit) showTip(hit);
});
scatter.addEventListener("focusin", (event) => {
  const hit = event.target.closest("circle.hit");
  if (hit) showTip(hit);
});
scatter.addEventListener("pointerleave", hideTip);
scatter.addEventListener("focusout", hideTip);

/* ---------- what's new, and the changelog ----------

   The changelog is data (kvasir/changelog.py, served at /api/changelog) and its newest entry
   is the app's version. The browser remembers the last version it showed — in localStorage,
   no cookie, nothing sent anywhere — and a returning visitor who has not seen the current one
   gets "What's new since your last visit" once. A first visit is not a return: it records the
   version silently, because everything on the page is new to them anyway.

   "Returning" is read before the first render, since rendering stores the open tab. */
const SEEN_KEY = "kvasir.seen";
const RETURNING = [SEEN_KEY, TIER_STORAGE_KEY, PATIENCE_STORAGE_KEY, PANEL_STORAGE_KEY, "kvasir.map"].some(
  (key) => stored(key) !== null
);
const UNKNOWN_SINCE_DAYS = 14;

function whereLabel(where) {
  const panel = PANELS.find((p) => p.id === where.panel);
  const chart = where.panel === "map" && where.map && MAPS[where.map] ? ` — ${MAPS[where.map].tab}` : "";
  return panel ? `Open ${panel.label}${chart}` : "";
}

function newsEntry(entry, open) {
  const items = entry.items
    .map((item) => {
      const go = item.where
        ? `<button class="text-link go" type="button" data-panel="${escapeHtml(item.where.panel)}"
             data-map="${escapeHtml(item.where.map || "")}">${escapeHtml(whereLabel(item.where))}</button>`
        : "";
      return `<li>${escapeHtml(item.text)}${go ? `<br>${go}` : ""}</li>`;
    })
    .join("");
  const date = new Date(entry.date).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  return `<details class="news-entry" ${open ? "open" : ""}>
    <summary><span class="news-version">v${escapeHtml(entry.version)}</span>
      <b>${escapeHtml(entry.title)}</b><span class="dim news-date">${date}</span></summary>
    <ul>${items}</ul>
  </details>`;
}

function openNews(mode) {
  const news = state.news;
  const dialog = $("#news");
  if (!news || !dialog) return;
  const entries = news.entries;
  let shown = entries;
  let kicker = `Version ${news.version}`;
  let title = "Changelog";
  if (mode === "since") {
    const seen = stored(SEEN_KEY);
    const at = entries.findIndex((e) => e.version === seen);
    if (at > 0) {
      shown = entries.slice(0, at);
      kicker = `Since your last visit · v${seen} → v${news.version}`;
    } else {
      const newest = new Date(entries[0].date).getTime();
      shown = entries.filter((e) => newest - new Date(e.date).getTime() <= UNKNOWN_SINCE_DAYS * 86400000);
      kicker = `The last two weeks · now v${news.version}`;
    }
    title = "What's new";
  }
  $("#news-kicker").textContent = kicker;
  $("#news-title").textContent = title;
  $("#news-body").innerHTML = shown.map((entry, i) => newsEntry(entry, mode === "since" || i === 0)).join("");
  $("#news-all").hidden = mode !== "since" || shown.length === entries.length;
  $("#news-body").querySelectorAll(".go").forEach((button) => {
    button.addEventListener("click", () => {
      dialog.close();
      if (button.dataset.map && MAPS[button.dataset.map]) {
        state.map = button.dataset.map;
        store("kvasir.map", state.map);
        renderMapTabs();
        renderMap(state.view);
      }
      showPanel(button.dataset.panel, { scroll: true });
      $("#section-tabs").scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
    });
  });
  if (!dialog.open) dialog.showModal();
}

async function loadNews() {
  try {
    const response = await fetch("/api/changelog", { cache: "no-store" });
    state.news = await response.json();
  } catch {
    return; // the page works without it; the button simply stays hidden
  }
  const button = $("#version-link");
  button.textContent = `v${state.news.version} · What's new`;
  button.hidden = false;
  const seen = stored(SEEN_KEY);
  if (seen === state.news.version) return;
  if (!RETURNING) {
    store(SEEN_KEY, state.news.version);
    return;
  }
  openNews("since");
}

// Whichever way it closes — the button, Esc, the ×, a click on the backdrop — the current
// version counts as seen.
$("#news").addEventListener("close", () => {
  if (state.news) store(SEEN_KEY, state.news.version);
});
$("#news").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
$("#news-close").addEventListener("click", () => $("#news").close());
$("#news-ok").addEventListener("click", () => $("#news").close());
$("#news-all").addEventListener("click", () => openNews("all"));
$("#version-link").addEventListener("click", () => openNews("all"));
$("#changelog-link").addEventListener("click", () => openNews("all"));

// The one orchestrated moment is the first paint: the three waits run against each other.
// The five-minute refresh redraws quietly.
load({ animate: true }).then(loadNews);
setInterval(load, 5 * 60 * 1000);
