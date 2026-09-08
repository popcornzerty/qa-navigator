"""Playwright ``.spec.ts`` generation from a Gherkin scenario.

The file skeleton — imports, ``test.describe``, one ``test.step`` per Gherkin step, and
the traceability header — is produced deterministically. The model only fills the body of
each step, and every line it returns is validated before being written:

* it must look like a Playwright statement (``page.…``, ``expect(…)``, ``test.…``);
* it may not import, spawn processes, touch the filesystem or evaluate strings;
* it may only reference ``data-testid`` values that the analyzer actually found.

A step whose code fails validation is emitted as a commented ``TODO`` and the test is
marked ``test.fixme()``. A generated test that cannot really drive the app is worth more
as an explicit red flag than as a green test that asserts nothing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from qa_engine import ollama
from qa_engine.generation import SYSTEM_PROMPT, FeatureContext

logger = logging.getLogger(__name__)

STATEMENT = re.compile(r"^(?:await\s+)?(?:expect\(|page\.|test\.|const\s+\w+\s*=\s*(?:await\s+)?page\.)")
FORBIDDEN = re.compile(
    r"\b(?:import|require|process|child_process|eval|Function|globalThis|__dirname|"
    r"__filename|fs|os|net|http|https|exec|spawn)\b"
)
TESTID_CALL = re.compile(r"getByTestId\(\s*['\"]([^'\"]+)['\"]\s*\)")

SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "etapes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "code": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["index", "code"],
            },
        }
    },
    "required": ["etapes"],
}

GHERKIN_KEYWORDS = ("Étant donné", "Quand", "Alors")


@dataclass
class GeneratedSpec:
    """A ``.spec.ts`` ready to be written to disk."""

    file_name: str
    source: str
    unresolved: list[str] = field(default_factory=list)

    @property
    def is_runnable(self) -> bool:
        return not self.unresolved


def _slug(value: str) -> str:
    ascii_value = (
        value.lower()
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("à", "a")
        .replace("ù", "u")
        .replace("ç", "c")
        .replace("ô", "o")
        .replace("î", "i")
        .replace("û", "u")
    )
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return cleaned[:60] or "scenario"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def flatten_steps(given: list[str], when: list[str], then: list[str]) -> list[tuple[str, str]]:
    """Gherkin steps as ``(keyword, text)``, in execution order."""
    steps: list[tuple[str, str]] = []
    for keyword, bucket in zip(GHERKIN_KEYWORDS, (given, when, then)):
        for index, text in enumerate(bucket):
            steps.append((keyword if index == 0 else "Et", text))
    return steps


def validate_line(line: str, known_test_ids: set[str]) -> tuple[str | None, str | None]:
    """Return ``(accepted_line, rejection_reason)``. Exactly one of them is set."""
    candidate = line.strip()
    if not candidate:
        return None, "ligne vide"
    if candidate.startswith("//"):
        return candidate, None
    if FORBIDDEN.search(candidate):
        return None, "instruction interdite (import, système de fichiers ou exécution)"
    if not STATEMENT.match(candidate):
        return None, "n'est pas une instruction Playwright"
    if not candidate.endswith(";"):
        candidate = f"{candidate};"

    for test_id in TESTID_CALL.findall(candidate):
        if test_id not in known_test_ids:
            return None, f'data-testid "{test_id}" introuvable dans le code analysé'
    return candidate, None


def _build_prompt(
    context: FeatureContext,
    story_title: str,
    scenario_name: str,
    steps: list[tuple[str, str]],
    base_url: str,
) -> str:
    # Numbered from 1: with a 0-based list, small models return code shifted by one step,
    # putting an assertion under a "Quand" and an action under an "Alors".
    numbered = "\n".join(
        f"{index}. {keyword} {text}" for index, (keyword, text) in enumerate(steps, start=1)
    )
    anchors = (
        ", ".join(sorted(context.test_ids)) if context.test_ids else "aucune ancre disponible"
    )
    routes = ", ".join(context.routes) if context.routes else "aucune"
    return (
        f"Application testée : {base_url}\n"
        f"Routes connues : {routes}\n"
        f"Ancres data-testid réellement présentes dans le code : {anchors}\n\n"
        f"USER STORY : {story_title}\n"
        f"SCÉNARIO : {scenario_name}\n"
        f"ÉTAPES :\n{numbered}\n\n"
        "Pour chaque étape, donne les instructions Playwright (TypeScript) qui la réalisent.\n"
        "Règles strictes :\n"
        "- une instruction par chaîne, terminée par un point-virgule ;\n"
        "- si l'ancre `app-ready` est disponible, fais suivre chaque `page.goto(...)` de "
        "`await page.getByTestId('app-ready').waitFor();` : l'application est rendue côté "
        "serveur et un clic avant l'hydratation ne déclenche rien ;\n"
        "- utilise uniquement `page.goto`, `page.getByTestId`, `page.getByRole`, "
        "`page.getByLabel`, `page.getByText`, `page.locator`, et `expect(...)` ;\n"
        "- pour les sélecteurs, n'utilise QUE les ancres data-testid listées ci-dessus. "
        "Si aucune ne convient, utilise `page.getByRole` avec le libellé visible ;\n"
        "- les étapes « Alors » ne contiennent que des `expect(...)` ;\n"
        "- n'écris aucun import, aucune déclaration de test, aucun commentaire : "
        "uniquement le corps de chaque étape ;\n"
        "- si une étape n'est pas automatisable avec ces éléments, renvoie une liste vide."
    )


def _render_steps(
    steps: list[tuple[str, str]],
    known_test_ids: set[str],
    prompt: str,
    *,
    temperature: float,
) -> tuple[list[str], list[str]]:
    """One generation round: returns the rendered step bodies and what stayed unresolved."""
    payload = ollama.chat_json(SYSTEM_PROMPT, prompt, SPEC_SCHEMA, temperature=temperature)

    # The prompt numbers steps from 1; internally they are 0-based.
    by_index: dict[int, list[str]] = {}
    for entry in payload.get("etapes", []):
        try:
            index = int(entry.get("index")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(steps):
            by_index[index] = [str(line) for line in entry.get("code", [])]

    unresolved: list[str] = []
    body: list[str] = []
    for index, (keyword, text) in enumerate(steps):
        label = _escape(f"{keyword} {text}")
        body.append(f'    await test.step("{label}", async () => {{')
        accepted: list[str] = []
        for line in by_index.get(index, []):
            valid, reason = validate_line(line, known_test_ids)
            if valid:
                accepted.append(valid)
            elif reason and reason != "ligne vide":
                accepted.append(f"// TODO manuel ({reason}) : {line.strip()}")
                unresolved.append(f"{keyword} {text} — {reason}")
        if not accepted:
            accepted.append("// TODO manuel : étape non automatisable avec les éléments détectés")
            unresolved.append(f"{keyword} {text} — aucune instruction exploitable")
        body.extend(f"      {line}" for line in accepted)
        body.append("    });")
    return body, unresolved


def generate_spec(
    context: FeatureContext,
    story_id: str,
    story_title: str,
    scenario_id: str,
    scenario_name: str,
    given: list[str],
    when: list[str],
    then: list[str],
    *,
    base_url: str,
) -> GeneratedSpec:
    """Produce one ``.spec.ts`` for a single Gherkin scenario."""
    steps = flatten_steps(given, when, then)
    known_test_ids = set(context.test_ids)

    prompt = _build_prompt(context, story_title, scenario_name, steps, base_url)

    # Generation is high variance: the same model and prompt can return nothing usable on
    # one call and a fully valid set on the next. A spec where *every* step failed is far
    # more likely to be a bad roll than a genuinely unautomatable scenario, so it is worth
    # one deterministic retry before giving up on the whole scenario.
    body, unresolved = _render_steps(steps, known_test_ids, prompt, temperature=0.2)
    if len(unresolved) >= len(steps):
        logger.info("Every step came back unusable for %s; retrying at temperature 0", scenario_id)
        retry_body, retry_unresolved = _render_steps(steps, known_test_ids, prompt, temperature=0.0)
        if len(retry_unresolved) < len(unresolved):
            body, unresolved = retry_body, retry_unresolved

    header = [
        "// Généré par AI QA Agent — ne pas éditer à la main, la régénération écrase ce fichier.",
        f"// User Story : {story_id} — {story_title}",
        f"// Scénario   : {scenario_id} — {scenario_name}",
        f"// Domaine    : {context.name}",
    ]
    if context.source_files:
        header.append(f"// Sources    : {', '.join(context.source_files[:4])}")
    header.extend(["", 'import { expect, test } from "@playwright/test";', ""])

    opening = [
        f'test.describe("{_escape(context.name)}", () => {{',
        f'  test("{_escape(scenario_name)}", async ({{ page }}) => {{',
    ]
    if unresolved:
        opening.append(
            "    // Des étapes n'ont pas pu être automatisées : le test est marqué à traiter."
        )
        opening.append("    test.fixme();")

    source = "\n".join([*header, *opening, *body, "  });", "});", ""])
    file_name = f"{story_id.lower()}-{_slug(scenario_name)}.spec.ts"
    return GeneratedSpec(file_name=file_name, source=source, unresolved=unresolved)
