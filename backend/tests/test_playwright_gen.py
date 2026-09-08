"""Spec generation tests.

The model is stubbed. What matters here is the guarantee around it: nothing dangerous or
ungrounded reaches a generated file, and a spec that cannot drive the app says so.
"""

from pathlib import Path
from types import SimpleNamespace

from qa_engine import generation, playwright_gen


def _context(tmp_path: Path) -> generation.FeatureContext:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "Cart.tsx").write_text("export const Cart = () => <div />;", encoding="utf-8")
    row = SimpleNamespace(
        name="Panier",
        description="Domaine fonctionnel détecté.",
        source_files=["src/Cart.tsx"],
        evidence={
            "routes": ["/cart"],
            "components": ["Cart"],
            "api_calls": [],
            "test_ids": ["cart-line", "cart-total"],
            "has_form": False,
        },
    )
    return generation.build_context(row, str(tmp_path))


def test_flatten_steps_uses_and_for_repeated_keywords():
    steps = playwright_gen.flatten_steps(["a", "b"], ["c"], ["d", "e"])
    assert [keyword for keyword, _ in steps] == ["Étant donné", "Et", "Quand", "Alors", "Et"]


def test_valid_playwright_line_is_accepted():
    line, reason = playwright_gen.validate_line(
        'await page.getByTestId("cart-line").click()', {"cart-line"}
    )
    assert reason is None
    assert line == 'await page.getByTestId("cart-line").click();'


def test_unknown_test_id_is_rejected():
    line, reason = playwright_gen.validate_line(
        'await page.getByTestId("ghost").click();', {"cart-line"}
    )
    assert line is None
    assert "ghost" in reason


def test_dangerous_lines_are_rejected():
    for dangerous in (
        'import fs from "fs";',
        "await page.evaluate(() => require('child_process'));",
        "const data = fs.readFileSync('/etc/passwd');",
    ):
        line, reason = playwright_gen.validate_line(dangerous, set())
        assert line is None, dangerous
        assert reason


def test_non_playwright_line_is_rejected():
    line, reason = playwright_gen.validate_line("console.log('hello');", set())
    assert line is None
    assert reason == "n'est pas une instruction Playwright"


def test_spec_is_runnable_when_every_step_is_grounded(tmp_path: Path, monkeypatch):
    payload = {
        "etapes": [
            {"index": 0, "code": ['await page.goto("/cart");']},
            {"index": 1, "code": ['await page.getByTestId("cart-line").click();']},
            {"index": 2, "code": ['await expect(page.getByTestId("cart-total")).toBeVisible();']},
        ]
    }
    monkeypatch.setattr(playwright_gen.ollama, "chat_json", lambda *a, **k: payload)

    spec = playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-001",
        story_title="Modifier la quantité",
        scenario_id="US-001-SC-1",
        scenario_name="Augmenter la quantité",
        given=["le panier contient un article"],
        when=["la quantité passe à 3"],
        then=["le total est recalculé"],
        base_url="http://localhost:8080",
    )

    assert spec.is_runnable
    assert spec.file_name == "us-001-augmenter-la-quantite.spec.ts"
    assert 'import { expect, test } from "@playwright/test";' in spec.source
    assert "US-001 — Modifier la quantité" in spec.source
    assert "test.fixme()" not in spec.source
    assert spec.source.count("await test.step(") == 3


def test_ungrounded_step_marks_the_test_as_fixme(tmp_path: Path, monkeypatch):
    payload = {
        "etapes": [
            {"index": 0, "code": ['await page.goto("/cart");']},
            {"index": 1, "code": ['await page.getByTestId("inexistant").click();']},
            {"index": 2, "code": []},
        ]
    }
    monkeypatch.setattr(playwright_gen.ollama, "chat_json", lambda *a, **k: payload)

    spec = playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-002",
        story_title="Story",
        scenario_id="US-002-SC-1",
        scenario_name="Scénario",
        given=["contexte"],
        when=["action"],
        then=["résultat"],
        base_url="http://localhost:8080",
    )

    assert not spec.is_runnable
    assert "test.fixme();" in spec.source
    assert "// TODO manuel" in spec.source
    assert len(spec.unresolved) == 2


def test_scenario_name_with_quotes_does_not_break_the_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(playwright_gen.ollama, "chat_json", lambda *a, **k: {"etapes": []})

    spec = playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-003",
        story_title='Story "spéciale"',
        scenario_id="US-003-SC-1",
        scenario_name='Le bouton "Analyser" est visible',
        given=["contexte"],
        when=[],
        then=[],
        base_url="http://localhost:8080",
    )

    assert '\\"Analyser\\"' in spec.source
