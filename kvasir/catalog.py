"""The task catalogue — the page's actual answer to "which agent do I start?".

Three tiers, and a list of the jobs that actually land on this desk mapped onto them. The
tiers are roles, not model names: which model fills a role is decided from live data in
recommend.py and changes as the benchmarks move.

UI strings are Polish by house rule; keys and code stay English.
"""

from __future__ import annotations

TIERS = [
    {
        "id": "architect",
        "name": "Architekt",
        "role": "Planuje i rozkłada zadanie",
        "description": (
            "Orkiestrator. Bierze duży, nieokreślony problem, ustala zakres, tworzy szablon "
            "i definiuje zadania dla pozostałych. Płacisz za myślenie, nie za klepanie."
        ),
        "accent": "violet",
    },
    {
        "id": "worker",
        "name": "Worker",
        "role": "Robi typową robotę",
        "description": (
            "Domyślny agent. Dostaje konkretne zadanie albo pytanie (również od biznesu) "
            "i je wykonuje. Szybszy od architekta, mniej twórczy — mocny tam, gdzie jest "
            "dokumentacja i wzorzec do naśladowania."
        ),
        "accent": "cyan",
    },
    {
        "id": "scout",
        "name": "Zwiadowca",
        "role": "Tanie, proste, powtarzalne",
        "description": (
            "Najtańszy agent do rzeczy mechanicznych: przeniesienie plików, zmiana nazw, "
            "wywołanie narzędzia przygotowanego przez innego agenta, szybkie sprawdzenie."
        ),
        "accent": "dim",
    },
]

TASKS = [
    {"id": "plan", "tier": "architect", "label": "Plan dużego zadania, architektura, rozbicie na kroki",
     "note": "Tu błąd kosztuje najwięcej — zły plan psuje całą resztę pracy."},
    {"id": "big-refactor", "tier": "architect", "label": "Refaktor przez wiele plików i modułów",
     "note": "Wymaga trzymania całego kontekstu naraz; worker gubi się w zależnościach."},
    {"id": "hard-bug", "tier": "architect", "label": "Trudny bug — nie wiadomo, gdzie leży",
     "note": "Cross-domain. Model musi łączyć ślady z warstw, których nikt nie wskazał."},
    {"id": "greenfield", "tier": "architect", "label": "Nowy moduł od zera, bez wzorca w repo",
     "note": "Nie ma czego skopiować — potrzebna kreatywność, nie odtwarzanie."},

    {"id": "feature", "tier": "worker", "label": "Feature według istniejącego wzorca w repo",
     "note": "Jest się czym podeprzeć: worker odtworzy wzorzec taniej i szybciej."},
    {"id": "business-q", "tier": "worker", "label": "Pytanie od biznesu: jak to działa, czy da się",
     "note": "Czytanie kodu i dokumentacji plus zwięzła odpowiedź."},
    {"id": "review", "tier": "worker", "label": "Code review, szukanie błędów w PR",
     "note": "Zakres znany, wynik weryfikowalny — nie ma za co dopłacać."},
    {"id": "tests", "tier": "worker", "label": "Testy do istniejącego kodu",
     "note": "Praca odtwórcza z jasnym kryterium sukcesu."},
    {"id": "integration", "tier": "worker", "label": "Integracja z API według dokumentacji",
     "note": "Dokumentacja jest w kontekście — to gra dla workera."},

    {"id": "mech-refactor", "tier": "scout", "label": "Mechaniczny refaktor: nazwy, przenoszenie plików",
     "note": "Zero kreatywności, dużo edycji. Płać za tokeny, nie za rozum."},
    {"id": "tool-call", "tier": "scout", "label": "Wywołanie narzędzia przygotowanego przez innego agenta",
     "note": "Narzędzie już myśli za agenta — wystarczy, żeby trafił w argumenty."},
    {"id": "chores", "tier": "scout", "label": "Commit message, changelog, opis PR",
     "note": "Krótkie, schematyczne, sprawdzane wzrokiem w sekundę."},
    {"id": "locate", "tier": "scout", "label": "Szybkie „gdzie to jest w kodzie”",
     "note": "Wyszukiwanie, nie rozumowanie."},
]

TIER_BY_ID = {tier["id"]: tier for tier in TIERS}
