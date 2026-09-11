"""Spec generation tests.

The model is stubbed. What matters here is the guarantee around it: nothing dangerous or
ungrounded reaches a generated file, and a spec that cannot drive the app says so.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

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
    assert [keyword for keyword, _ in steps] == ["Given", "And", "When", "Then", "And"]


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
            {"index": 1, "code": ['await page.goto("/cart");']},
            {"index": 2, "code": ['await page.getByTestId("cart-line").click();']},
            {"index": 3, "code": ['await expect(page.getByTestId("cart-total")).toBeVisible();']},
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
            {"index": 1, "code": ['await page.goto("/cart");']},
            {"index": 2, "code": ['await page.getByTestId("inexistant").click();']},
            {"index": 3, "code": []},
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


def test_step_indices_are_one_based(tmp_path: Path, monkeypatch):
    """The prompt numbers steps from 1; an off-by-one puts assertions under "Quand"."""
    payload = {"etapes": [{"index": 1, "code": ['await page.goto("/cart");']}]}
    monkeypatch.setattr(playwright_gen.ollama, "chat_json", lambda *a, **k: payload)

    spec = playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-010",
        story_title="Story",
        scenario_id="US-010-SC-1",
        scenario_name="Scénario",
        given=["le panier est ouvert"],
        when=["rien"],
        then=["rien"],
        base_url="http://localhost:8080",
    )

    first, rest = spec.source.split('await test.step("When', 1)
    assert 'await page.goto("/cart");' in first, "step 1 code landed on the wrong step"
    assert "TODO manuel" in rest


def test_out_of_range_index_is_ignored(tmp_path: Path, monkeypatch):
    payload = {"etapes": [{"index": 99, "code": ['await page.goto("/cart");']}]}
    monkeypatch.setattr(playwright_gen.ollama, "chat_json", lambda *a, **k: payload)

    spec = playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-011",
        story_title="Story",
        scenario_id="US-011-SC-1",
        scenario_name="Scénario",
        given=["contexte"],
        when=[],
        then=[],
        base_url="http://localhost:8080",
    )
    assert not spec.is_runnable
    assert "page.goto" not in spec.source


def test_a_fully_unusable_answer_is_retried_once(tmp_path: Path, monkeypatch):
    """Generation is high variance: everything failing is usually a bad roll, not a verdict."""
    calls: list[float] = []

    def answer(_system, _prompt, _schema, *, temperature=0.2):
        calls.append(temperature)
        if len(calls) == 1:
            return {"etapes": [{"index": 1, "code": ["console.log('nope');"]}]}
        return {"etapes": [{"index": 1, "code": ['await page.goto("/cart");']}]}

    monkeypatch.setattr(playwright_gen.ollama, "chat_json", answer)

    spec = playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-020",
        story_title="Story",
        scenario_id="US-020-SC-1",
        scenario_name="Scénario",
        given=["contexte"],
        when=[],
        then=[],
        base_url="http://localhost:8080",
    )

    assert calls == [0.2, playwright_gen.RETRY_TEMPERATURE], "the retry must diverge, not replay"
    assert spec.is_runnable
    assert 'await page.goto("/cart");' in spec.source


def test_a_partly_usable_answer_is_not_retried(tmp_path: Path, monkeypatch):
    """One bad step out of three is a real limit, not noise — do not pay for a second call."""
    calls: list[float] = []

    def answer(_system, _prompt, _schema, *, temperature=0.2):
        calls.append(temperature)
        return {
            "etapes": [
                {"index": 1, "code": ['await page.goto("/cart");']},
                {"index": 2, "code": []},
                {"index": 3, "code": ['await expect(page.getByTestId("cart-total")).toBeVisible();']},
            ]
        }

    monkeypatch.setattr(playwright_gen.ollama, "chat_json", answer)

    spec = playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-021",
        story_title="Story",
        scenario_id="US-021-SC-1",
        scenario_name="Scénario",
        given=["contexte"],
        when=["action"],
        then=["résultat"],
        base_url="http://localhost:8080",
    )

    assert calls == [0.2]
    assert len(spec.unresolved) == 1


def test_missing_await_is_repaired():
    """An un-awaited expect() asserts nothing and the test still reports green."""
    line, reason = playwright_gen.validate_line(
        "expect(page.getByTestId('cart-total')).toBeVisible();", {"cart-total"}
    )
    assert reason is None
    assert line == "await expect(page.getByTestId('cart-total')).toBeVisible();"


def test_missing_await_is_repaired_on_actions():
    line, _ = playwright_gen.validate_line("page.getByTestId('cart-line').click();", {"cart-line"})
    assert line == "await page.getByTestId('cart-line').click();"


def test_an_existing_await_is_not_doubled():
    line, _ = playwright_gen.validate_line('await page.goto("/cart");', set())
    assert line == 'await page.goto("/cart");'


def test_a_locator_declaration_is_not_awaited():
    line, _ = playwright_gen.validate_line(
        "const row = page.getByTestId('cart-line');", {"cart-line"}
    )
    assert line == "const row = page.getByTestId('cart-line');"


@pytest.mark.parametrize(
    "url",
    [
        "/projects/$projectId/analysis",
        "/users/:id",
        "/posts/{slug}",
        "/files/[name]",
        "/projects/${projectId}",
    ],
)
def test_unresolved_route_parameters_are_rejected(url: str):
    """A URL still carrying a parameter cannot be navigated to."""
    line, reason = playwright_gen.validate_line(f"await page.goto('{url}');", set())
    assert line is None
    assert "paramètre de route non résolu" in reason


def test_a_concrete_url_is_accepted():
    line, reason = playwright_gen.validate_line('await page.goto("/projects");', set())
    assert reason is None
    assert line == 'await page.goto("/projects");'


def test_the_retry_tells_the_model_what_went_wrong(tmp_path: Path, monkeypatch):
    """Replaying the identical prompt would just resample the mode that already failed."""
    prompts: list[str] = []

    def answer(_system, prompt, _schema, *, temperature=0.2):
        prompts.append(prompt)
        if len(prompts) == 1:
            return {"etapes": []}
        return {"etapes": [{"index": 1, "code": ['await page.goto("/cart");']}]}

    monkeypatch.setattr(playwright_gen.ollama, "chat_json", answer)

    playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-030",
        story_title="Story",
        scenario_id="US-030-SC-1",
        scenario_name="Scénario",
        given=["contexte"],
        when=[],
        then=[],
        base_url="http://localhost:8080",
    )

    assert len(prompts) == 2
    assert prompts[1].startswith(prompts[0])
    assert "aucune instruction exploitable" in prompts[1]


def test_the_prompt_does_not_offer_an_empty_list_escape_hatch(tmp_path: Path, monkeypatch):
    """An easy way out is the way the model takes when the constraints get tight."""
    captured: list[str] = []
    monkeypatch.setattr(
        playwright_gen.ollama,
        "chat_json",
        lambda _s, prompt, _sc, **k: captured.append(prompt) or {"etapes": []},
    )

    playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-031",
        story_title="Story",
        scenario_id="US-031-SC-1",
        scenario_name="Scénario",
        given=["contexte"],
        when=[],
        then=[],
        base_url="http://localhost:8080",
    )

    assert "renvoie une liste vide" not in captured[0]
    assert "jamais une liste `etapes` vide" in captured[0]


@pytest.mark.parametrize(
    "line",
    [
        "await page.goto('http://localhost:8080/projects');",
        'await page.goto("https://staging.example.test/cart");',
        "await expect(page).toHaveURL('http://localhost:8080/projects');",
    ],
)
def test_navigation_to_a_real_url_is_not_mistaken_for_a_dangerous_call(line: str):
    """`http` as a bare word rejected the very navigation the model is asked to write."""
    accepted, reason = playwright_gen.validate_line(line, set())
    assert accepted is not None, reason
    assert reason is None


@pytest.mark.parametrize(
    "line",
    [
        'import fs from "fs";',
        "await page.evaluate(() => require('child_process'));",
        "const data = fs.readFileSync('/etc/passwd');",
        "await page.evaluate(() => eval('1+1'));",
        "const cwd = process.cwd();",
        "await http.get('http://internal/secret');",
    ],
)
def test_dangerous_constructs_are_still_rejected(line: str):
    accepted, reason = playwright_gen.validate_line(line, set())
    assert accepted is None, f"should have been refused: {line}"
    assert reason


def test_only_parameterless_routes_are_directly_reachable():
    routes = [
        "/projects",
        "/projects/",
        "/projects/$projectId",
        "/projects/$projectId/analysis",
        "/projects/new",
        "/users/:id",
        "/posts/{slug}",
    ]
    assert playwright_gen.reachable_routes(routes) == {"/projects", "/projects/new"}


@pytest.mark.parametrize(
    "url",
    [
        "/projects/1",
        "/projects/7e10d6b1-48fa",
        "http://localhost:8080/projects/1/analysis",
    ],
)
def test_navigating_to_an_invented_id_is_refused(url: str):
    """`/projects/1` looks concrete, passes every other check, and lands on a 404."""
    line, reason = playwright_gen.validate_line(
        f"await page.goto('{url}');", set(), {"/projects", "/"}
    )
    assert line is None
    assert "navigue par l'interface" in reason


@pytest.mark.parametrize("url", ["/projects", "/projects/", "http://localhost:8080/projects?a=1"])
def test_navigating_to_a_known_route_is_allowed(url: str):
    line, reason = playwright_gen.validate_line(
        f"await page.goto('{url}');", set(), {"/projects", "/"}
    )
    assert reason is None, reason
    assert line is not None


def test_route_checking_is_skipped_when_no_route_list_is_given():
    """Callers that have no analysis to lean on must not have every navigation refused."""
    line, reason = playwright_gen.validate_line("await page.goto('/anything');", set())
    assert reason is None
    assert line is not None


def test_the_prompt_lists_the_directly_reachable_routes(tmp_path: Path, monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(
        playwright_gen.ollama,
        "chat_json",
        lambda _s, prompt, _sc, **k: captured.append(prompt) or {"etapes": []},
    )

    context = _context(tmp_path)
    context.routes = ["/cart", "/cart/$itemId"]
    playwright_gen.generate_spec(
        context,
        story_id="US-040",
        story_title="Story",
        scenario_id="US-040-SC-1",
        scenario_name="Scénario",
        given=["contexte"],
        when=[],
        then=[],
        base_url="http://localhost:8080",
    )

    assert "Adresses connues de l'application : /cart" in captured[0]
    assert "/cart/$itemId" not in captured[0]
    # The prompt has to say the list is exhaustive: a model given routes but no rule
    # treats them as examples and writes a plausible-looking fifth one.
    assert "SEULES adresses valides" in captured[0]


def test_a_step_keeps_its_working_assertions_when_some_are_dropped(tmp_path: Path, monkeypatch):
    """Marking the whole test fixme would discard the assertions that do hold."""
    payload = {
        "etapes": [
            {
                "index": 1,
                "code": [
                    'await expect(page.getByTestId("cart-total")).toBeVisible();',
                    'await expect(page.getByTestId("inexistant")).toBeVisible();',
                ],
            }
        ]
    }
    monkeypatch.setattr(playwright_gen.ollama, "chat_json", lambda *a, **k: payload)

    spec = playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-050",
        story_title="Story",
        scenario_id="US-050-SC-1",
        scenario_name="Scénario",
        given=["contexte"],
        when=[],
        then=[],
        base_url="http://localhost:8080",
    )

    assert spec.is_runnable, "a step with working code must not block the test"
    assert "test.fixme()" not in spec.source
    assert 'await expect(page.getByTestId("cart-total")).toBeVisible();' in spec.source
    # The dropped line stays visible in the file so the gap is reviewable.
    assert "// TODO manuel" in spec.source


def test_a_step_with_nothing_executable_still_blocks(tmp_path: Path, monkeypatch):
    payload = {"etapes": [{"index": 1, "code": ["console.log('nope');"]}]}
    monkeypatch.setattr(playwright_gen.ollama, "chat_json", lambda *a, **k: payload)

    spec = playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-051",
        story_title="Story",
        scenario_id="US-051-SC-1",
        scenario_name="Scénario",
        given=["contexte"],
        when=[],
        then=[],
        base_url="http://localhost:8080",
    )

    assert not spec.is_runnable
    assert "test.fixme()" in spec.source


class TestHashAddresses:
    """An application navigating by hash has real addresses; dropping them invited invention."""

    def test_a_hash_is_the_address_not_a_fragment_to_discard(self):
        assert playwright_gen.normalise_route("#cgu") == "#cgu"
        assert playwright_gen.normalise_route("http://localhost:5180/#cgu") == "#cgu"

    def test_hash_routes_no_longer_collapse_onto_the_root(self):
        """All four legal pages became `/`, leaving one allowed address for four pages."""
        routes = ["#a-propos", "#cgu", "#confidentialite", "#mentions-legales"]
        assert playwright_gen.reachable_routes(routes) == set(routes)

    def test_a_plain_path_is_unaffected(self):
        assert playwright_gen.normalise_route("/projects/") == "/projects"
        assert playwright_gen.normalise_route("http://x/projects?a=1") == "/projects"


class TestUrlAssertions:
    ALLOWED = {"#cgu", "/"}

    def test_an_invented_address_is_refused(self):
        """`toHaveURL('/about')` on an app with no `/about` fails on a page never built."""
        accepted, reason = playwright_gen.validate_line(
            "await expect(page).toHaveURL('/about');", set(), self.ALLOWED
        )
        assert accepted is None
        assert "/about" in reason

    def test_a_known_address_passes(self):
        accepted, _ = playwright_gen.validate_line(
            "await expect(page).toHaveURL('#cgu');", set(), self.ALLOWED
        )
        assert accepted is not None

    def test_navigation_is_still_checked_too(self):
        accepted, _ = playwright_gen.validate_line(
            "await page.goto('/about');", set(), self.ALLOWED
        )
        assert accepted is None


class TestLocatorsAreAnchored:
    """Playwright matches text by substring, and refuses a step that hits several nodes."""

    def anchor(self, line: str) -> str:
        return playwright_gen.anchor_text_locators(line)

    def test_a_bare_text_locator_becomes_exact(self):
        assert self.anchor("page.getByText('Confidentialité').click();") == (
            "page.getByText('Confidentialité', { exact: true }).click();"
        )

    def test_an_already_exact_locator_is_left_alone(self):
        line = "page.getByText('X', { exact: true }).click();"
        assert self.anchor(line) == line

    def test_a_role_name_becomes_exact(self):
        assert self.anchor("page.getByRole('button', { name: 'Confidentialité' }).click();") == (
            "page.getByRole('button', { name: 'Confidentialité', exact: true }).click();"
        )

    def test_a_role_without_a_name_is_left_alone(self):
        line = "page.getByRole('table').click();"
        assert self.anchor(line) == line

    def test_a_testid_is_untouched(self):
        """An anchor is already unambiguous; `exact` on it would mean nothing."""
        line = "page.getByTestId('nav-cgu').click();"
        assert self.anchor(line) == line

    def test_the_repair_happens_during_validation(self):
        accepted, _ = playwright_gen.validate_line("page.getByText('CGU').click();", set(), None)
        assert "exact: true" in accepted


def test_the_hydration_rule_is_offered_only_when_the_anchor_exists(tmp_path: Path, monkeypatch):
    """Stated unconditionally, it was followed unconditionally.

    Every step then opened with a `waitFor` on an anchor the repository does not have, and
    every one of them was rejected — a spec whose manual TODOs described nothing but the
    instruction that produced them.
    """
    captured: list[str] = []

    def capture(_system, prompt, _schema, **kwargs):
        captured.append(prompt)
        return {"etapes": []}

    monkeypatch.setattr(playwright_gen.ollama, "chat_json", capture)

    without = SimpleNamespace(
        name="Frontend", description="", routes=["/"], components=[], api_calls=[],
        test_ids=["nav-home"], has_form=False, source_files=[], excerpts=[],
    )
    playwright_gen.generate_spec(
        without, story_id="US-050", story_title="T", scenario_id="US-050-SC-1",
        scenario_name="S", given=["a"], when=[], then=[], base_url="http://localhost:8080",
    )
    # An empty answer is retried, so one generation produces more than one prompt.
    assert captured and not any("app-ready" in prompt for prompt in captured)
    captured.clear()

    with_anchor = SimpleNamespace(
        name="Frontend", description="", routes=["/"], components=[], api_calls=[],
        test_ids=["nav-home", "app-ready"], has_form=False, source_files=[], excerpts=[],
    )
    playwright_gen.generate_spec(
        with_anchor, story_id="US-051", story_title="T", scenario_id="US-051-SC-1",
        scenario_name="S", given=["a"], when=[], then=[], base_url="http://localhost:8080",
    )
    assert captured and all("app-ready" in prompt for prompt in captured)


class TestRoleIsCheckedAgainstTheCode:
    CONTROLS = [
        {"role": "button", "name": "À propos"},
        {"role": "link", "name": "Ko-fi"},
    ]

    def test_a_role_the_code_contradicts_is_refused(self):
        """The failure this exists for: 30 seconds of timeout to learn it was a button."""
        accepted, reason = playwright_gen.validate_line(
            "await page.getByRole('link', { name: 'À propos' }).click();",
            set(),
            None,
            self.CONTROLS,
        )
        assert accepted is None
        assert "button" in reason

    def test_the_role_the_code_declares_passes(self):
        accepted, _ = playwright_gen.validate_line(
            "await page.getByRole('button', { name: 'À propos' }).click();",
            set(),
            None,
            self.CONTROLS,
        )
        assert accepted is not None

    def test_a_label_the_analysis_never_saw_is_refused(self):
        """This reverses an earlier decision, and the evidence is what changed it.

        Leaving unknown labels alone was meant to spare labels computed at runtime. What
        it actually spared was invention: a click on a `link` named "Connexion" to reach a
        login screen that was already open, and a `heading` named "Connexion" on a screen
        with no heading at all. Each cost a timeout and then blamed the application.

        The escape hatch it was protecting is still open, and wider than it was: a label
        the code merely *displays* counts, which is how `{occupe ? "Vérification…" :
        "Se connecter"}` stays reachable without any extractor seeing a button. What is
        refused now is a label nothing in the analysed screen accounts for.
        """
        accepted, reason = playwright_gen.validate_line(
            "await page.getByRole('link', { name: 'Inconnu' }).click();",
            set(),
            None,
            self.CONTROLS,
        )
        assert accepted is None
        assert reason is not None and "Inconnu" in reason

    def test_a_label_the_code_only_displays_is_accepted(self):
        """`<button>{occupe ? "Vérification…" : "Se connecter"}</button>`: no extractor
        reads that as a button, but the string is in the copy and the button is real."""
        accepted, _ = playwright_gen.validate_line(
            "await page.getByRole('button', { name: 'Se connecter' }).click();",
            set(),
            None,
            self.CONTROLS,
            None,
            ["Se connecter", "Vérification…"],
        )
        assert accepted is not None

    def test_nothing_is_refused_when_no_control_was_extracted(self):
        accepted, _ = playwright_gen.validate_line(
            "await page.getByRole('link', { name: 'À propos' }).click();", set(), None, []
        )
        assert accepted is not None


class TestUnsatisfiableScenarios:
    """Gherkin puts every action before every assertion, which lets a scenario covering
    several behaviours assert several addresses at once. Only the last can hold."""

    def check(self, *lines: str) -> list[str]:
        return playwright_gen.contradictory_url_assertions(list(lines))

    def test_two_addresses_asserted_in_a_row_is_impossible(self):
        problems = self.check(
            "await expect(page).toHaveURL('http://x/#a-propos');",
            "await expect(page).toHaveURL('http://x/#cgu');",
        )
        assert len(problems) == 1
        assert "#a-propos" in problems[0] and "#cgu" in problems[0]

    def test_asserting_navigating_then_asserting_again_is_ordinary(self):
        assert self.check(
            "await expect(page).toHaveURL('#a-propos');",
            "await page.getByRole('link', { name: 'CGU' }).click();",
            "await expect(page).toHaveURL('#cgu');",
        ) == []

    def test_the_same_address_twice_is_not_a_contradiction(self):
        assert self.check(
            "await expect(page).toHaveURL('http://x/#cgu');",
            "await expect(page).toHaveURL('#cgu');",
        ) == []

    def test_a_goto_counts_as_navigation(self):
        assert self.check(
            "await expect(page).toHaveURL('#a-propos');",
            "await page.goto('http://x/#cgu');",
            "await expect(page).toHaveURL('#cgu');",
        ) == []

    def test_the_four_page_scenario_is_reported(self):
        """The real case: four clicks, then four addresses that exclude one another."""
        body = ["await page.goto('http://x/#a-propos');"]
        for name in ("À propos", "CGU", "Confidentialité", "Mentions légales"):
            body.append(f"await page.getByRole('link', {{ name: '{name}' }}).click();")
        for target in ("#a-propos", "#cgu", "#confidentialite", "#mentions-legales"):
            body.append(f"await expect(page).toHaveURL('http://x/{target}');")
        assert len(self.check(*body)) == 3


class TestHomeRoute:
    """An opening step describing an initial state has to become a concrete address."""

    def test_the_root_wins_when_it_exists(self):
        assert playwright_gen.home_route({"/", "/panier"}) == "/"

    def test_an_application_reached_only_by_fragments_is_still_served_at_its_root(self):
        """Starting from `#cgu` produced a test that opened its own destination."""
        assert playwright_gen.home_route({"#a-propos", "#cgu"}) == "/"

    def test_the_shallowest_path_stands_in_when_there_is_no_root(self):
        assert playwright_gen.home_route({"/backlog/x", "/automation", "/backlog"}) == "/backlog"

    def test_a_repository_with_no_route_still_has_a_home(self):
        assert playwright_gen.home_route(set()) == "/"


def test_the_home_is_named_and_allowed(tmp_path: Path, monkeypatch):
    """Recommending an address the check below would refuse is worse than saying nothing."""
    captured: list[str] = []

    def capture(_system, prompt, _schema, **kwargs):
        captured.append(prompt)
        return {"etapes": [{"index": 1, "code": ["await page.goto('/');"]}]}

    monkeypatch.setattr(playwright_gen.ollama, "chat_json", capture)

    context = SimpleNamespace(
        name="Frontend", description="", routes=["#cgu"], components=[], api_calls=[],
        test_ids=[], controls=[], fields=[], texts=[], has_form=False, source_files=[], excerpts=[],
    )
    spec = playwright_gen.generate_spec(
        context, story_id="US-060", story_title="T", scenario_id="US-060-SC-1",
        scenario_name="S", given=["l'utilisateur est sur la page d'accueil"], when=[], then=[],
        base_url="http://localhost:5180",
    )

    assert "Adresse d'accueil : /" in captured[0]
    # And the address the prompt recommends survives validation.
    assert "await page.goto('/');" in spec.source
    assert spec.is_runnable


class TestDeclaredCredentials:
    """`process.` is banned so generated code cannot reach for whatever it likes.

    A test that signs in still needs a credential, so a project may name the variables
    holding them — and only those.
    """

    ALLOWED = {"PEATERM_E2E_USER"}

    def test_a_declared_variable_may_be_read(self):
        accepted, _ = playwright_gen.validate_line(
            "await page.getByLabel('Identifiant').fill(process.env.PEATERM_E2E_USER);",
            set(),
            None,
            None,
            self.ALLOWED,
        )
        assert accepted is not None

    def test_any_other_variable_is_still_refused(self):
        accepted, reason = playwright_gen.validate_line(
            "await page.getByLabel('X').fill(process.env.AWS_SECRET_ACCESS_KEY);",
            set(),
            None,
            None,
            self.ALLOWED,
        )
        assert accepted is None
        assert "interdite" in reason

    def test_the_ban_on_process_itself_holds(self):
        accepted, _ = playwright_gen.validate_line(
            "await page.evaluate(() => process.exit(0));", set(), None, None, self.ALLOWED
        )
        assert accepted is None

    def test_nothing_is_readable_when_a_project_declares_nothing(self):
        accepted, _ = playwright_gen.validate_line(
            "await page.getByLabel('I').fill(process.env.PEATERM_E2E_USER);", set(), None, None, set()
        )
        assert accepted is None

    def test_the_prompt_names_the_variable_and_never_its_value(self, tmp_path: Path, monkeypatch):
        captured: list[str] = []

        def capture(_system, prompt, _schema, **kwargs):
            captured.append(prompt)
            return {"etapes": []}

        monkeypatch.setattr(playwright_gen.ollama, "chat_json", capture)
        monkeypatch.setenv("PEATERM_E2E_PASSWORD", "un-mot-de-passe-reel")

        context = SimpleNamespace(
            name="F", description="", routes=["/"], components=[], api_calls=[],
            test_ids=[], controls=[], fields=[], texts=[], has_form=True, source_files=[], excerpts=[],
        )
        playwright_gen.generate_spec(
            context, story_id="US-070", story_title="T", scenario_id="US-070-SC-1",
            scenario_name="S", given=["a"], when=[], then=[], base_url="http://x",
            credentials={"mot de passe": "PEATERM_E2E_PASSWORD"},
        )
        assert "process.env.PEATERM_E2E_PASSWORD" in captured[0]
        assert "un-mot-de-passe-reel" not in captured[0], "a secret must not travel in a prompt"


class TestMalformedLines:
    """TypeScript that cannot be parsed fails the whole spec, not just its step."""

    def test_an_extra_closing_parenthesis_is_refused(self):
        line = "await expect(page.getByRole('button', { name: 'X' }))).toBeVisible();"
        accepted, reason = playwright_gen.validate_line(line, set())
        assert accepted is None
        assert "parenthésage" in reason

    def test_an_unclosed_call_is_refused(self):
        accepted, _ = playwright_gen.validate_line(
            "await expect(page.getByTestId('x').toBeVisible();", {"x"}
        )
        assert accepted is None

    def test_a_bracket_inside_a_string_does_not_count(self):
        """A locator may legitimately contain one."""
        accepted, _ = playwright_gen.validate_line(
            "await page.getByText('un )( bizarre', { exact: true }).click();", set()
        )
        assert accepted is not None

    def test_a_balanced_line_passes(self):
        accepted, _ = playwright_gen.validate_line(
            "await expect(page.getByRole('button', { name: 'X' })).toBeVisible();", set()
        )
        assert accepted is not None


class TestTextIsGrounded:
    COPY = ["Renseignez votre identifiant et votre mot de passe.", "Identifiant"]

    def test_an_invented_message_is_refused(self):
        """The application says "Renseignez votre identifiant…" and never "requis"."""
        accepted, reason = playwright_gen.validate_line(
            "await expect(page.getByText('Identifiant requis')).toBeVisible();",
            set(), None, None, None, self.COPY,
        )
        assert accepted is None
        assert "Identifiant requis" in reason

    def test_a_fragment_of_real_copy_passes(self):
        accepted, _ = playwright_gen.validate_line(
            "await expect(page.getByText('Renseignez votre identifiant')).toBeVisible();",
            set(), None, None, None, self.COPY,
        )
        assert accepted is not None

    def test_containment_runs_one_way_only(self):
        """"Identifiant requis" contains the known label "Identifiant"; read in reverse,
        every invention holding a real word would pass."""
        accepted, _ = playwright_gen.validate_line(
            "await expect(page.getByText('Identifiant obligatoire')).toBeVisible();",
            set(), None, None, None, self.COPY,
        )
        assert accepted is None

    def test_a_silent_analysis_refuses_nothing(self):
        accepted, _ = playwright_gen.validate_line(
            "await expect(page.getByText('N’importe quoi')).toBeVisible();",
            set(), None, None, None, [],
        )
        assert accepted is not None


def test_a_when_that_only_asserts_is_reported(tmp_path: Path, monkeypatch):
    """A "When" is the user acting. Code that only checks describes a state, so the
    scenario has no action and its "Then" observes nothing that happened."""
    payload = {
        "etapes": [
            {"index": 1, "code": ["await page.goto('/cart');"]},
            {"index": 2, "code": ["await expect(page.getByTestId('cart-line')).toBeVisible();"]},
            {"index": 3, "code": ["await expect(page.getByTestId('cart-total')).toBeVisible();"]},
        ]
    }
    monkeypatch.setattr(playwright_gen.ollama, "chat_json", lambda *a, **k: payload)

    spec = playwright_gen.generate_spec(
        _context(tmp_path),
        story_id="US-080", story_title="S", scenario_id="US-080-SC-1", scenario_name="S",
        given=["le panier est ouvert"], when=["la ligne est visible"], then=["le total s'affiche"],
        base_url="http://localhost:8080",
    )
    assert not spec.is_runnable
    assert any("aucune action" in item for item in spec.unresolved)


def test_a_heading_the_application_never_shows_is_refused():
    """A heading is named by its own text, so the copy index decides it.

    `getByRole('heading', { name: 'Connexion' })` on a login screen whose only words are
    "Terminal PEA" cost a five-second timeout and reported the product broken for a title
    it never had.
    """
    texts = ["Terminal PEA", "Renseignez votre identifiant et votre mot de passe."]
    line, reason = playwright_gen.validate_line(
        "await expect(page.getByRole('heading', { name: 'Connexion' })).toBeVisible();",
        set(),
        texts=texts,
    )
    assert line is None
    assert reason is not None and "Connexion" in reason


def test_a_heading_the_application_does_show_is_kept():
    texts = ["Terminal PEA", "Conditions générales d'utilisation"]
    line, reason = playwright_gen.validate_line(
        "await expect(page.getByRole('heading', "
        "{ name: \"Conditions générales d'utilisation\" })).toBeVisible();",
        set(),
        texts=texts,
    )
    assert reason is None
    assert line is not None


def test_a_button_label_the_analysis_never_saw_is_refused():
    line, reason = playwright_gen.validate_line(
        "await page.getByRole('button', { name: 'Se connecter' }).click();",
        set(),
        texts=["Terminal PEA"],
    )
    assert line is None
    assert reason is not None and "Se connecter" in reason


def test_a_silent_analysis_refuses_nothing():
    """No control and no copy is a limit of the reading, not a verdict on the screen."""
    line, reason = playwright_gen.validate_line(
        "await page.getByRole('button', { name: 'Se connecter' }).click();", set()
    )
    assert reason is None
    assert line is not None


def test_a_heading_is_held_to_the_whole_text_not_a_fragment():
    """Containment let `{ name: 'Connexion' }` through on the strength of the error
    message "Connexion impossible." Role locators are pinned with `exact: true`, so that
    locator asks for a heading whose entire text is "Connexion" — a claim the copy of the
    application does not support."""
    line, reason = playwright_gen.validate_line(
        "await expect(page.getByRole('heading', { name: 'Connexion' })).toBeVisible();",
        set(),
        texts=["Terminal PEA", "Connexion impossible."],
    )
    assert line is None
    assert reason is not None and "Connexion" in reason


def test_a_role_label_is_read_up_to_its_own_closing_quote():
    """Reading to "any quote" cut `"Conditions générales d'utilisation"` at the
    apostrophe, so the label checked was not the label written."""
    label = "Conditions générales d'utilisation"
    assert playwright_gen.role_calls(
        f'page.getByRole("heading", {{ name: "{label}" }})'
    ) == [("heading", label)]


def test_a_heading_whose_apostrophe_survives_is_accepted():
    label = "Conditions générales d'utilisation"
    line, reason = playwright_gen.validate_line(
        f'await expect(page.getByRole("heading", {{ name: "{label}" }})).toBeVisible();',
        set(),
        texts=[label, "Mentions légales"],
    )
    assert reason is None
    assert line is not None

class TestOneNavigationPerStep:
    """Asked for "the user is on the login screen", the model clicked its way through
    every link on it: À propos, CGU, Confidentialité — destinations that cannot all be
    true, in a step that had already arrived with `goto('/')`."""

    CONTROLS = [
        {"role": "link", "name": "À propos", "file": "Login.tsx"},
        {"role": "link", "name": "CGU", "file": "Login.tsx"},
        {"role": "link", "name": "Confidentialité", "file": "Login.tsx"},
        {"role": "button", "name": "Se connecter", "file": "Login.tsx"},
    ]

    def _run(self, monkeypatch, given_code):
        monkeypatch.setattr(
            playwright_gen.ollama,
            "chat_json",
            lambda *a, **k: {
                "etapes": [
                    {"index": 1, "code": given_code},
                    {
                        "index": 2,
                        "code": ["await page.getByRole('button', { name: 'Se connecter' }).click();"],
                    },
                ]
            },
        )
        context = playwright_gen.FeatureContext(
            name="Authentification",
            description="",
            routes=["/"],
            components=[],
            api_calls=[],
            test_ids=[],
            controls=self.CONTROLS,
            fields=[],
            texts=["Se connecter", "À propos", "CGU", "Confidentialité"],
            has_form=True,
            source_files=["Login.tsx"],
            excerpts=[],
        )
        spec = playwright_gen.generate_spec(
            context,
            story_id="US-008",
            story_title="S'authentifier",
            scenario_id="US-008-SC-1",
            scenario_name="Soumettre un formulaire vide",
            given=["L'utilisateur est sur l'écran de connexion"],
            when=["Il clique sur le bouton soumettre"],
            then=[],
            base_url="http://localhost:5180",
        )
        # What the browser will actually run, TODO comments excluded.
        runnable = [
            line.strip()
            for line in spec.source.splitlines()
            if line.strip().startswith("await") or line.strip().startswith("//") is False
        ]
        return spec, [line for line in runnable if line.startswith("await page.")]

    def test_the_arrival_is_kept_and_the_wandering_is_not(self, monkeypatch):
        spec, runnable = self._run(
            monkeypatch,
            [
                "await page.goto('/');",
                "await page.getByRole('link', { name: 'À propos' }).click();",
                "await page.getByRole('link', { name: 'CGU' }).click();",
                "await page.getByRole('link', { name: 'Confidentialité' }).click();",
            ],
        )
        assert "await page.goto('/');" in runnable
        assert not [line for line in runnable if "getByRole('link'" in line]
        # Each refusal is left in the file, naming itself.
        assert spec.source.count("une seconde navigation") == 3

    def test_a_step_that_navigates_once_keeps_its_navigation(self, monkeypatch):
        _spec, runnable = self._run(
            monkeypatch, ["await page.getByRole('link', { name: 'CGU' }).click();"]
        )
        assert any("name: 'CGU', exact: true }).click()" in line for line in runnable)

    def test_acting_on_the_screen_is_not_a_second_navigation(self, monkeypatch):
        """Only links and `goto` leave the screen. Pressing a button on it is the point."""
        spec, runnable = self._run(monkeypatch, ["await page.goto('/');"])
        assert "await page.goto('/');" in runnable
        assert any("name: 'Se connecter', exact: true }).click()" in line for line in runnable)
        assert "une seconde navigation" not in spec.source

def test_a_fragment_assertion_keeps_substring_matching():
    """`getByText('… mot de passe')` against "… mot de passe." differs by one full stop.
    Pinned exact it could never resolve, and the test would report the application broken
    over a period."""
    line, reason = playwright_gen.validate_line(
        "await expect(page.getByText('Renseignez votre identifiant et votre mot de passe'))"
        ".toBeVisible();",
        set(),
        texts=["Renseignez votre identifiant et votre mot de passe."],
    )
    assert reason is None
    assert "exact: true" not in line


def test_a_whole_label_is_still_pinned():
    """The ambiguity this exists for: "Confidentialité" matches its own link and every
    paragraph containing the word, and strict mode then refuses the step."""
    line, _reason = playwright_gen.validate_line(
        "await expect(page.getByText('Confidentialité')).toBeVisible();",
        set(),
        texts=["Confidentialité", "Politique de confidentialité du service"],
    )
    assert "exact: true" in line


def test_nothing_known_means_nothing_changes_about_pinning():
    line, _reason = playwright_gen.validate_line(
        "await expect(page.getByText('Confidentialité')).toBeVisible();", set()
    )
    assert "exact: true" in line

def test_a_fragment_the_model_pinned_itself_is_unpinned():
    """The model pins locators on its own, having seen the option in earlier output. The
    pinning rule then has nothing left to add, and a fragment stays bound to a sentence it
    is only part of — `'… mot de passe'` against "… mot de passe." never resolves."""
    line, reason = playwright_gen.validate_line(
        "await expect(page.getByText('Renseignez votre identifiant et votre mot de passe', "
        "{ exact: true })).toBeVisible();",
        set(),
        texts=["Renseignez votre identifiant et votre mot de passe."],
    )
    assert reason is None
    assert "exact: true" not in line


def test_a_whole_label_the_model_pinned_itself_stays_pinned():
    line, _reason = playwright_gen.validate_line(
        "await expect(page.getByText('Confidentialité', { exact: true })).toBeVisible();",
        set(),
        texts=["Confidentialité", "Politique de confidentialité"],
    )
    assert "exact: true" in line

def test_a_jest_dom_matcher_is_refused():
    """A generated spec asserted `toHaveTextContent(...)`, which throws "is not a function"
    at run time: the test reports red for a mistake in itself, and the reason is buried in
    a stack trace."""
    line, reason = playwright_gen.validate_line(
        "await expect(page.getByTestId('total')).toHaveTextContent('42');", {"total"}
    )
    assert line is None
    assert reason is not None and "jest-dom" in reason


def test_the_playwright_spelling_of_the_same_assertion_passes():
    line, reason = playwright_gen.validate_line(
        "await expect(page.getByTestId('total')).toHaveText('42');", {"total"}
    )
    assert reason is None
    assert line is not None


def test_a_playwright_matcher_with_a_similar_name_is_untouched():
    """`toBeFocused` is Playwright's; only jest-dom's `toHaveFocus` is refused."""
    line, reason = playwright_gen.validate_line(
        "await expect(page.getByTestId('champ')).toBeFocused();", {"champ"}
    )
    assert reason is None
    assert line is not None
