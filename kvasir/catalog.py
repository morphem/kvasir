"""The task catalogue — the page's actual answer to "which agent do I start?".

Three tiers, and a list of the jobs that actually land on this desk mapped onto them. The
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
            "where documentation exists and a pattern can be followed."
        ),
        "accent": "cyan",
    },
    {
        "id": "scout",
        "name": "Scout",
        "role": "Cheap, simple, repetitive",
        "description": (
            "The cheapest agent, for mechanical work: moving files, renaming things, calling a "
            "tool another agent prepared, checking something quickly."
        ),
        "accent": "dim",
    },
]

TASKS = [
    {"id": "plan", "tier": "architect", "label": "Plan a large task: architecture, scope, breakdown",
     "note": "Where a mistake costs the most — a bad plan wastes every hour spent downstream of it."},
    {"id": "big-refactor", "tier": "architect", "label": "Refactor across many files and modules",
     "note": "The whole context has to be held at once; a worker loses the thread between dependencies."},
    {"id": "hard-bug", "tier": "architect", "label": "Hard bug with no obvious location",
     "note": "Cross-domain. The model has to connect traces from layers nobody pointed it at."},
    {"id": "greenfield", "tier": "architect", "label": "New module from scratch, no pattern in the repo",
     "note": "Nothing to copy — this needs invention rather than recall."},

    {"id": "feature", "tier": "worker", "label": "Feature that follows an existing pattern",
     "note": "There is something to lean on, so the worker reproduces it faster and cheaper."},
    {"id": "business-q", "tier": "worker", "label": "Question from the business: how does this work, can we do it",
     "note": "Read the code and the docs, then answer in two sentences."},
    {"id": "review", "tier": "worker", "label": "Code review, finding bugs in a pull request",
     "note": "Bounded scope and a checkable result — nothing here earns a premium."},
    {"id": "tests", "tier": "worker", "label": "Tests for code that already exists",
     "note": "Recall work with an unambiguous success criterion."},
    {"id": "integration", "tier": "worker", "label": "Integrate an API from its documentation",
     "note": "The documentation is in the context window; this is the worker's game."},

    {"id": "mech-refactor", "tier": "scout", "label": "Mechanical refactor: renames, moving files",
     "note": "Zero creativity, many edits. Pay for tokens, not for judgement."},
    {"id": "tool-call", "tier": "scout", "label": "Call a tool another agent prepared",
     "note": "The tool already does the thinking — the model only has to hit the arguments."},
    {"id": "chores", "tier": "scout", "label": "Commit message, changelog, pull request description",
     "note": "Short, formulaic, and verified at a glance."},
    {"id": "locate", "tier": "scout", "label": "Quick “where is this in the code”",
     "note": "Searching, not reasoning."},
]

TIER_BY_ID = {tier["id"]: tier for tier in TIERS}
