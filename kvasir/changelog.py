"""What changed, release by release — the page's own changelog.

One list, newest first, and the single source of the app's version: `VERSION` is the first
entry's, so adding an entry is what makes a deploy a new version. The page reads this list
from /api/changelog and does two things with it: a "What's new" window a returning visitor
sees once after a deploy they have not seen, and the full history behind a link beside the
name.

Written for the people who use the page, not for the people who build it: what you can do now,
and where on the page it is. `where` names the tab (and, for the map, the chart) a "show me"
button opens; the ids are the page's own panel ids and are checked by a test. Internals — a
refactor, a fixed race — belong in the commit log, not here, unless they changed what the page
says.
"""

from __future__ import annotations

CHANGELOG: list[dict] = [
    {
        "version": "2.3",
        "date": "2026-09-24",
        "title": "A light face",
        "items": [
            {
                "text": "Kvasir now has a light theme — cool paper, white panels, the same two accents "
                "darkened so cyan still means it lines up and violet still means a gap. The moon / sun "
                "button next to the BlinkNeuron name at the top left switches between them.",
            },
            {
                "text": "Until you choose, the page follows your system's light or dark setting, on a "
                "phone as on a computer. Your choice is remembered in your browser, like the tier.",
            },
        ],
    },
    {
        "version": "2.2",
        "date": "2026-09-24",
        "title": "What's new, and the changelog",
        "items": [
            {
                "text": "This window. After a deploy you have not seen, it opens once with what "
                "changed since your last visit; \"Got it\" closes it until the next one. "
                "Your browser remembers the last version it showed — nothing is sent anywhere.",
            },
            {
                "text": "The full history, every release since the first one, is behind the version "
                "button next to the name and the Changelog link at the foot of the page.",
            },
        ],
    },
    {
        "version": "2.1",
        "date": "2026-09-24",
        "title": "The map: where to use what",
        "items": [
            {
                "text": "A new first tab, Where to use what: intelligence against cost per task, "
                "against time per task, and against output tokens per task, drawn the way "
                "Artificial Analysis draws them. The top-left quadrant is the place to shop; the "
                "dotted Pareto line runs through what nothing beats. Switch charts and the dots "
                "move, so you can follow one model from cheap-but-slow to fast-but-dear.",
                "where": {"panel": "map", "map": "cost"},
            },
            {
                "text": "The time chart splits at the worker's patience limit, with the scout's as a "
                "dashed line — left of it, a model is quick enough for that role.",
                "where": {"panel": "map", "map": "time"},
            },
            {
                "text": "Show the rest of the market draws the models we cannot start behind ours, "
                "as hollow grey dots, for scale. It changes no recommendation.",
                "where": {"panel": "map", "map": "cost"},
            },
            {
                "text": "Patience now means minutes per task — the length of one loop — instead of "
                "seconds to the first answer. You iterate with the worker and the scout, so a slow "
                "loop makes the whole session slow. Fast: 3 / 1.5 minutes, Balanced: 6 / 3, Any: no "
                "limit. The bar on each card shows it.",
            },
            {
                "text": "An effort nobody has timed is shown as at least as slow as the timed effort "
                "below it (\"≥ 7.5 min\"), so it can no longer slip into a quick role unmeasured.",
            },
            {
                "text": "Links can open a chart directly: add ?map=time or ?map=tokens, and &market=1 "
                "for the rest of the market.",
            },
            {
                "text": "Artificial Analysis is read every three hours instead of twelve, so a newly "
                "priced model reaches the board the same morning. GPT-6 Luna and Sol are now priced "
                "and in the roles.",
            },
        ],
    },
    {
        "version": "2.0",
        "date": "2026-09-22",
        "title": "Scored by Artificial Analysis, and a patience switch",
        "items": [
            {
                "text": "Every model is now scored, priced and timed by Artificial Analysis — the "
                "Intelligence Index, the cost of one task and the time it takes, per effort, from "
                "the same runs. CursorBench is retired; its history stays in the archive.",
            },
            {
                "text": "Opus 5.5, GPT-6 Luna and GPT-6 Sol are on the board. GPT-6 Astra is switched "
                "off for us, like Grok and Fable.",
            },
            {
                "text": "A second switch beside the tier: how long one loop may take (Fast, Balanced, "
                "Any). The worker and the scout are chosen from models quick enough for it; the "
                "architect never is on that clock.",
            },
            {
                "text": "Each card now leads with a time bar on one scale shared by all three roles, "
                "with the patience limits marked on it.",
            },
            {
                "text": "All models: one sortable table with score, coding, credits per task, time per "
                "task, first answer, typing speed, drift and the Copilot price — and a filter by time.",
                "where": {"panel": "models"},
            },
            {
                "text": "A model Copilot sells but Artificial Analysis has not priced yet is named "
                "above the cards instead of silently missing.",
            },
        ],
    },
    {
        "version": "1.4",
        "date": "2026-09-15",
        "title": "Speed, tabs, and a tier that gets spent",
        "items": [
            {
                "text": "A fourth source, Artificial Analysis, for the clock: how fast a model types and "
                "how long it thinks before answering.",
            },
            {
                "text": "The page became tabs under the verdict instead of one long scroll; the tab you "
                "were on is remembered and can be linked.",
            },
            {
                "text": "Unused credits buy nothing, so each tier's plan now climbs until it uses most "
                "of the allowance — and says what stopped it when it does not.",
                "where": {"panel": "budget"},
            },
            {
                "text": "The drift and Copilot tables can be sorted by any column.",
                "where": {"panel": "drift"},
            },
            {
                "text": "A note appears when a benchmark re-baselines, so a board that shrank overnight "
                "does not read as a bug.",
            },
        ],
    },
    {
        "version": "1.3",
        "date": "2026-09-09",
        "title": "Only what we can start",
        "items": [
            {
                "text": "The recommendations only name models our Copilot actually sells and has not "
                "switched off. Show models we cannot run opens the full board to see what the "
                "restriction costs.",
            },
            {
                "text": "A drift veto now needs evidence — a model that is simply not measured cannot "
                "win one — and a frozen drift reading stops vetoing after two days.",
                "where": {"panel": "drift"},
            },
            {
                "text": "When AI Stupid Level went key-only, the page kept the last good scores and says "
                "which half of the drift section is frozen.",
                "where": {"panel": "drift"},
            },
        ],
    },
    {
        "version": "1.2",
        "date": "2026-08-22",
        "title": "An explorable chart, and an archived verdict",
        "items": [
            {
                "text": "The cost-against-score chart can be explored: click a dot to see every effort "
                "of that model, and draw up to three models' effort ladders to compare them.",
                "where": {"panel": "map", "map": "cost"},
            },
            {
                "text": "Every verdict the page gives is archived when it changes, so last week's "
                "answer can still be found.",
            },
        ],
    },
    {
        "version": "1.1",
        "date": "2026-08-19",
        "title": "AI-credit tiers",
        "items": [
            {
                "text": "Pick Basic, Heavy or Power and the whole page re-answers for that monthly "
                "budget: what each role can afford, what a month of ordinary work costs, and how "
                "much is left.",
                "where": {"panel": "budget"},
            },
            {
                "text": "Drift can veto a budget pick too: a model sliding on AI Stupid Level loses "
                "its role to a comparable one that holds steady.",
            },
        ],
    },
    {
        "version": "1.0",
        "date": "2026-08-19",
        "title": "Kvasir",
        "items": [
            {
                "text": "One page for one question — which agent to start for this task, today — with "
                "three roles: architect, worker, scout, each named with its effort level.",
            },
            {
                "text": "The task list maps everyday jobs to a role and a model.",
                "where": {"panel": "tasks"},
            },
            {
                "text": "Drift over time from AI Stupid Level, and every reading archived.",
                "where": {"panel": "drift"},
            },
        ],
    },
]

VERSION = CHANGELOG[0]["version"]

# The page's panel ids and map ids, which a "show me" button may open. Kept here so a test can
# hold every entry to them; the page itself defines the same ids in web/app.js.
PANELS = {"map", "tasks", "budget", "value", "models", "drift", "method"}
MAPS = {"cost", "time", "tokens"}
