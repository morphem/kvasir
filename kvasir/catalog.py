"""The task catalogue — the page's actual answer to "which agent do I start?".

Three roles, and a list of the jobs that actually land on this desk mapped onto them. The
tiers are roles, not model names: which model fills a role is decided from live data in
recommend.py and changes as the benchmarks move.

The UI is English here by the owner's decision — the page is shared with colleagues and
every source it quotes is English — which is a documented exception to the ecosystem's
"UI in Polish" rule. See CLAUDE.md.
"""

from __future__ import annotations

TIERS = [
    {
        "id": "architect",
        "name": "Architect",
        "role": "Plans and decomposes",
        "description": (
            "The orchestrator. Takes a large, under-specified problem, sets the scope, builds "
            "the outline and defines the tasks for everyone else. You are paying for thinking, "
            "not for typing."
        ),
        "accent": "violet",
    },
    {
        "id": "worker",
        "name": "Worker",
        "role": "Does the ordinary job",
        "description": (
            "The default agent. Takes a defined task or a question — including one from the "
            "business — and answers it. Faster than the architect and less inventive: strongest "
            "where documentation exists and a pattern can be followed. For mechanical work, the "
            "same model at a lower effort."
        ),
        "accent": "cyan",
    },
    {
        "id": "subagent",
        "name": "Subagent",
        "role": "Runs what the architect hands off",
        "description": (
            "The agent the architect delegates to and does not watch: search, run, fix, report "
            "back. Chosen on agentic evaluations — multi-step work across tools and a terminal — "
            "not on the Intelligence Index. The tier's spare credits are mostly its runs."
        ),
        "accent": "cyan",
    },
]

# What each role is for, printed on its card. Short on purpose: the card is read at a glance.
# The scout's work (renames, commit messages, "where is this") moved to the worker on
# 2026-11-19, at the quicker effort its card names.
TASKS = [
    {"id": "plan", "tier": "architect", "label": "planning: architecture, scope, breakdown"},
    {"id": "big-refactor", "tier": "architect", "label": "refactors across many modules"},
    {"id": "hard-bug", "tier": "architect", "label": "hard bugs with no obvious location"},
    {"id": "greenfield", "tier": "architect", "label": "new modules with no pattern to copy"},

    {"id": "feature", "tier": "worker", "label": "features that follow a pattern"},
    {"id": "business-q", "tier": "worker", "label": "questions from the business"},
    {"id": "review", "tier": "worker", "label": "code review"},
    {"id": "tests", "tier": "worker", "label": "tests for existing code"},
    {"id": "integration", "tier": "worker", "label": "API integration from docs"},
    {"id": "chores", "tier": "worker", "label": "renames, commit messages, “where is this” (quick effort)"},

    {"id": "delegated-fix", "tier": "subagent", "label": "sub-tasks from the plan: change, test, report"},
    {"id": "fan-out", "tier": "subagent", "label": "investigations in parallel"},
    {"id": "tool-call", "tier": "subagent", "label": "calling tools another agent prepared"},
]

TIER_BY_ID = {tier["id"]: tier for tier in TIERS}
