"""Generation tests.

The local model is stubbed: these assert the contract around it — prompt content, parsing,
caps and failure handling — not the quality of the model's prose.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from qa_engine import generation, ollama


def _feature_row(tmp_path: Path) -> SimpleNamespace:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "Cart.tsx").write_text("export const Cart = () => <div />;", encoding="utf-8")
    return SimpleNamespace(
        name="Panier",
        description="Domaine fonctionnel détecté : 1 route(s).",
        source_files=["src/Cart.tsx"],
        evidence={
            "routes": ["/cart"],
            "components": ["Cart"],
            "api_calls": ["/api/cart"],
            "test_ids": ["cart-line"],
            "has_form": True,
        },
    )


def test_context_includes_evidence_and_excerpts(tmp_path: Path):
    context = generation.build_context(_feature_row(tmp_path), str(tmp_path))
    block = context.as_prompt_block()

    assert "Panier" in block
    assert "/cart" in block
    assert "cart-line" in block
    assert "Formulaire présent : oui" in block
    assert "export const Cart" in block  # the excerpt was read from disk


def test_missing_source_file_does_not_break_context(tmp_path: Path):
    row = _feature_row(tmp_path)
    row.source_files = ["src/Gone.tsx"]
    context = generation.build_context(row, str(tmp_path))
    assert context.excerpts == []


def test_stories_are_parsed_and_capped(tmp_path: Path, monkeypatch):
    payload = {
        "epic": "Parcours d'achat",
        "stories": [
            {
                "titre": f"Story {index}",
                "description": "En tant que client, je veux X afin de Y.",
                "criteres_acceptation": [f"Critère {n}" for n in range(10)],
            }
            for index in range(10)
        ],
    }
    monkeypatch.setattr(generation.ollama, "chat_json", lambda *a, **k: payload)

    stories = generation.generate_stories(generation.build_context(_feature_row(tmp_path), str(tmp_path)))

    assert len(stories) == generation.MAX_STORIES_PER_FEATURE
    assert all(len(s.acceptance_criteria) <= generation.MAX_CRITERIA_PER_STORY for s in stories)
    assert stories[0].epic == "Parcours d'achat"


def test_story_without_a_title_is_dropped(tmp_path: Path, monkeypatch):
    payload = {
        "epic": "",
        "stories": [
            {"titre": "   ", "description": "vide", "criteres_acceptation": ["a"]},
            {"titre": "Valide", "description": "ok", "criteres_acceptation": ["a"]},
        ],
    }
    monkeypatch.setattr(generation.ollama, "chat_json", lambda *a, **k: payload)

    stories = generation.generate_stories(generation.build_context(_feature_row(tmp_path), str(tmp_path)))

    assert [story.title for story in stories] == ["Valide"]
    assert stories[0].epic == "Panier"  # falls back to the feature name


def test_scenarios_are_parsed_and_capped(tmp_path: Path, monkeypatch):
    # Distinct steps per scenario: deduplication must not be what enforces the cap.
    payload = {
        "scenarios": [
            {
                "scenario": f"Scénario {index}",
                "etant_donne": [f"le panier contient {index} articles"],
                "quand": [f"la quantité passe à {index + 1}"],
                "alors": [f"le total affiche {index * 10} euros"],
            }
            for index in range(6)
        ]
    }
    monkeypatch.setattr(generation.ollama, "chat_json", lambda *a, **k: payload)

    story = generation.GeneratedStory(
        title="Modifier la quantité", description="", epic="Panier", acceptance_criteria=["a"]
    )
    scenarios = generation.generate_scenarios(
        generation.build_context(_feature_row(tmp_path), str(tmp_path)), story
    )

    assert len(scenarios) == generation.MAX_SCENARIOS_PER_STORY
    assert scenarios[0].given == ["le panier contient 0 articles"]
    assert scenarios[0].then == ["le total affiche 0 euros"]


def test_runtime_failure_propagates(tmp_path: Path, monkeypatch):
    def explode(*_args, **_kwargs):
        raise ollama.OllamaError("connection refused")

    monkeypatch.setattr(generation.ollama, "chat_json", explode)

    with pytest.raises(ollama.OllamaError):
        generation.generate_stories(generation.build_context(_feature_row(tmp_path), str(tmp_path)))


def test_scenarios_repeated_under_a_new_title_are_dropped(tmp_path: Path, monkeypatch):
    """Small models pad up to the requested count by restating the same scenario."""
    steps = {
        "etant_donne": ["je suis sur la page des scénarios"],
        "quand": ["je consulte un scénario validé"],
        "alors": ["un indicateur vert est visible"],
    }
    payload = {
        "scenarios": [
            {"scenario": "Voir le statut validé", **steps},
            {"scenario": "Vérifier l'état de validation", **steps},
        ]
    }
    monkeypatch.setattr(generation.ollama, "chat_json", lambda *a, **k: payload)

    story = generation.GeneratedStory(title="Voir le statut", description="", epic="", acceptance_criteria=[])
    scenarios = generation.generate_scenarios(
        generation.build_context(_feature_row(tmp_path), str(tmp_path)), story
    )

    assert [item.scenario for item in scenarios] == ["Voir le statut validé"]


def test_genuinely_different_scenarios_are_kept(tmp_path: Path, monkeypatch):
    payload = {
        "scenarios": [
            {
                "scenario": "Cas nominal",
                "etant_donne": ["le panier contient un article"],
                "quand": ["la quantité passe à 3"],
                "alors": ["le total est recalculé"],
            },
            {
                "scenario": "Stock insuffisant",
                "etant_donne": ["le stock est limité à 2"],
                "quand": ["la quantité passe à 5"],
                "alors": ["un message d'avertissement apparaît"],
            },
        ]
    }
    monkeypatch.setattr(generation.ollama, "chat_json", lambda *a, **k: payload)

    story = generation.GeneratedStory(title="Quantité", description="", epic="", acceptance_criteria=[])
    scenarios = generation.generate_scenarios(
        generation.build_context(_feature_row(tmp_path), str(tmp_path)), story
    )

    assert len(scenarios) == 2
