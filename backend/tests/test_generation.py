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


def test_regenerating_gherkin_replaces_scenarios_and_their_tests(tmp_path: Path, monkeypatch):
    """A Playwright test asserting a scenario that no longer exists still reports green."""
    from fastapi.testclient import TestClient

    from qa_engine import services
    from qa_engine.database import SessionLocal
    from qa_engine.main import app
    from qa_engine.models import Feature, GherkinScenario, PlaywrightTest, UserStory

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "Cart.tsx").write_text(
        'export const Cart = () => <Route path="/cart" />;', encoding="utf-8"
    )
    spec = repo / "tests" / "obsolete.spec.ts"
    spec.parent.mkdir(parents=True)
    spec.write_text("// obsolete", encoding="utf-8")

    monkeypatch.setattr(
        generation,
        "generate_scenarios",
        lambda *a, **k: [
            generation.GeneratedScenario(
                scenario="Nouveau scénario", given=["contexte"], when=["action"], then=["résultat"]
            )
        ],
    )

    with TestClient(app) as client:
        created = client.post(
            f"/api/v1/projects",
            json={"name": "Regen", "repository": str(repo), "repositorySource": "local"},
        )
        project_id = created.json()["id"]
        client.post("/api/v1/analyses", json={"project_id": project_id})

        db = SessionLocal()
        try:
            feature = db.scalar(select_feature(Feature, project_id))
            db.add(
                UserStory(
                    id="US-800",
                    project_id=project_id,
                    feature_id=feature.id,
                    feature_name=feature.name,
                    title="Story",
                )
            )
            db.flush()
            db.add(
                GherkinScenario(
                    id="US-800-SC-1",
                    user_story_id="US-800",
                    project_id=project_id,
                    feature=feature.name,
                    scenario="Ancien scénario",
                    given=[],
                    when=[],
                    then=[],
                )
            )
            db.add(
                PlaywrightTest(
                    id="pw-800",
                    project_id=project_id,
                    user_story_id="US-800",
                    gherkin_scenario_id="US-800-SC-1",
                    file="tests/obsolete.spec.ts",
                )
            )
            db.commit()
        finally:
            db.close()

        services.regenerate_gherkin_for_story("US-800")

        story = client.get("/api/v1/stories/US-800").json()
        assert [s["scenario"] for s in story["gherkinScenarios"]] == ["Nouveau scénario"]
        assert client.get("/api/v1/tests/pw-800").status_code == 404
        assert not spec.exists(), "the spec of a deleted scenario must not survive"


def select_feature(model, project_id):
    from sqlalchemy import select

    return select(model).where(model.project_id == project_id)


def test_the_scenario_prompt_forbids_batching_behaviours(monkeypatch):
    """Four clicks then four addresses is unsatisfiable, and the model has to be told.

    Gherkin puts every action before every assertion, so a scenario covering several
    behaviours asserts several mutually exclusive states and can never be entirely true.
    """
    captured: list[str] = []

    def capture(_system, prompt, _schema, **kwargs):
        captured.append(prompt)
        return {"scenarios": []}

    monkeypatch.setattr(generation.ollama, "chat_json", capture)

    context = generation.FeatureContext(
        name="Frontend",
        description="",
        routes=["/"],
        components=[],
        api_calls=[],
        test_ids=[],
        controls=[],
        has_form=False,
        source_files=[],
    )
    generation.generate_scenarios(
        context,
        generation.GeneratedStory(title="T", description="d", epic="e", acceptance_criteria=["c"]),
    )

    assert "un scénario = un comportement" in captured[0]


class TestGherkinStaysBusinessReadable:
    """A scenario is judged by whoever decides the behaviour is wanted, and pushed to Jira."""

    def test_a_route_in_a_step_is_a_leak(self):
        assert generation.technical_leak(
            "L'API /auth/login est appelée avec les identifiants entrés"
        )

    def test_a_file_name_is_a_leak(self):
        assert generation.technical_leak("Le composant Legal.tsx affiche les documents")

    def test_a_url_is_a_leak(self):
        assert generation.technical_leak("La page s'ouvre sur http://localhost:5180/#cgu")

    def test_a_test_anchor_is_a_leak(self):
        assert generation.technical_leak("Le data-testid nav-cgu est présent")

    def test_a_business_step_is_not(self):
        for step in (
            "L'utilisateur est redirigé vers la page d'administration",
            "Le formulaire de connexion est affiché",
            "Le bouton « Analyser » est visible",
        ):
            assert generation.technical_leak(step) is None, step


def test_a_leaking_scenario_is_regenerated_rather_than_dropped(monkeypatch):
    """Dropping it would lose a legitimate flow over one badly worded step."""
    calls: list[float] = []

    def answer(_system, prompt, _schema, *, temperature=0.2):
        calls.append(temperature)
        if len(calls) == 1:
            return {
                "scenarios": [
                    {
                        "scenario": "Connexion",
                        "etant_donne": ["l'utilisateur est sur la page d'accueil"],
                        "quand": ["il valide le formulaire"],
                        "alors": ["L'API /auth/login est appelée"],
                    }
                ]
            }
        assert "interdit" in prompt, "the retry must name the offence, not replay blindly"
        return {
            "scenarios": [
                {
                    "scenario": "Connexion",
                    "etant_donne": ["l'utilisateur est sur la page d'accueil"],
                    "quand": ["il valide le formulaire"],
                    "alors": ["Le tableau de bord est affiché"],
                }
            ]
        }

    monkeypatch.setattr(generation.ollama, "chat_json", answer)

    context = generation.FeatureContext(
        name="F", description="", routes=["/"], components=[], api_calls=[],
        test_ids=[], controls=[], has_form=False, source_files=[],
    )
    scenarios = generation.generate_scenarios(
        context,
        generation.GeneratedStory(title="T", description="d", epic="e", acceptance_criteria=["c"]),
    )

    assert calls == [0.2, generation.SCENARIO_RETRY_TEMPERATURE]
    assert [s.then for s in scenarios] == [["Le tableau de bord est affiché"]]


def test_the_prompt_forbids_asserting_an_intermediate_state(monkeypatch):
    """"Le formulaire est affiché" after submitting it is false: the form is gone."""
    captured: list[str] = []

    def capture(_system, prompt, _schema, **kwargs):
        captured.append(prompt)
        return {"scenarios": []}

    monkeypatch.setattr(generation.ollama, "chat_json", capture)

    context = generation.FeatureContext(
        name="F", description="", routes=["/"], components=[], api_calls=[],
        test_ids=[], controls=[], has_form=False, source_files=[],
    )
    generation.generate_scenarios(
        context,
        generation.GeneratedStory(title="T", description="d", epic="e", acceptance_criteria=["c"]),
    )
    assert "après toutes" in captured[0]


class TestScenarioTitles:
    """A title is scanned down a backlog and becomes a Jira summary."""

    def test_a_recited_title_is_reduced_to_the_action(self):
        assert generation.tidy_title(
            "Quand l'utilisateur clique sur le bouton de connexion, le formulaire s'affiche."
        ) == "L'utilisateur clique sur le bouton de connexion"

    def test_other_gherkin_openings_too(self):
        assert generation.tidy_title("Lorsque le panier est vide, un message le signale") == (
            "Le panier est vide"
        )

    def test_a_long_title_is_cut_on_a_word(self):
        tidied = generation.tidy_title("Un titre " + "interminable " * 12)
        assert len(tidied) <= generation.MAX_TITLE_CHARS
        assert not tidied.endswith("interminabl")

    def test_a_name_is_left_exactly_as_it_is(self):
        for title in (
            "Ouvrir le formulaire de connexion",
            "Accéder à la page 'CGU' depuis le menu principal",
        ):
            assert generation.tidy_title(title) == title

    def test_a_clumsy_title_never_costs_the_scenario(self, monkeypatch):
        """Refusing one discarded a whole login flow and regenerated nothing at all."""
        calls: list[float] = []

        def answer(_system, _prompt, _schema, *, temperature=0.2):
            calls.append(temperature)
            return {
                "scenarios": [
                    {
                        "scenario": "Quand il clique, le formulaire s'affiche",
                        "etant_donne": ["il est sur l'accueil"],
                        "quand": ["il clique"],
                        "alors": ["le formulaire est affiché"],
                    }
                ]
            }

        monkeypatch.setattr(generation.ollama, "chat_json", answer)
        context = generation.FeatureContext(
            name="F", description="", routes=["/"], components=[], api_calls=[],
            test_ids=[], controls=[], has_form=False, source_files=[],
        )
        scenarios = generation.generate_scenarios(
            context,
            generation.GeneratedStory(title="T", description="d", epic="e", acceptance_criteria=["c"]),
        )
        assert calls == [0.2], "a title is repaired, never retried"
        assert [s.scenario for s in scenarios] == ["Il clique"]


def test_a_name_followed_by_its_steps_keeps_only_the_name():
    """The model produced a good name and then recited the scenario after it.

    Cutting on length alone left "Ouvrir le formulaire de connexion Étant donné que
    l'utilisateur est sur la page" — a name spoiled by half a step.
    """
    assert generation.tidy_title(
        "Ouvrir le formulaire de connexion Étant donné que l'utilisateur est sur la page d'accueil"
    ) == "Ouvrir le formulaire de connexion"
    assert generation.tidy_title(
        "Se connecter avec des identifiants valides Étant donné que le formulaire est affiché"
    ) == "Se connecter avec des identifiants valides"


def test_a_keyword_inside_an_ordinary_word_is_not_a_cut():
    """"Alors" as a word, not "alorsque" or a name containing it."""
    assert generation.tidy_title("Consulter les alertes") == "Consulter les alertes"
