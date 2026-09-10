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
# Matches the dangerous *constructs*, not the bare words. `fs`, `os`, `net`, `http` as
# whole words rejected `page.goto('http://localhost:8080/…')` — a correct navigation, and
# exactly what the model is asked to produce. Module access always carries a dot or a call.
FORBIDDEN = re.compile(
    r"\bimport\s|\brequire\s*\(|\beval\s*\(|\bFunction\s*\(|\bchild_process\b|"
    r"\bglobalThis\b|\b__dirname\b|\b__filename\b|"
    r"\bprocess\.|\bfs\.|\bos\.|\bnet\.|\bhttp\.|\bhttps\.|\bexec\s*\(|\bspawn\s*\("
)
TESTID_CALL = re.compile(r"getByTestId\(\s*['\"]([^'\"]+)['\"]\s*\)")

# Assertions and page actions must be awaited. Locator declarations (`const row = page…`)
# must not be, so they are excluded.
NEEDS_AWAIT = re.compile(r"^(?:expect\(|page\.)")

# The anchor a server-rendered app exposes once React has attached its handlers.
HYDRATION_ANCHOR = "app-ready"

# `getByText` and `getByRole`'s name match on *substring* by default, so a label that is a
# fragment of any other visible text resolves to several elements and Playwright refuses
# the whole step in strict mode: "Confidentialité" matched its own menu button and two
# paragraphs merely containing the word. Nothing about the intent is ambiguous — the
# generator meant that exact label — so the option is added rather than the line rejected.
# Repositories without `data-testid` fall back to these locators for everything, which is
# precisely where the ambiguity bites.
TEXT_LOCATOR = re.compile(
    r"\bgetBy(?:Text|Label|Placeholder|Title)\(\s*(['\"`])(?:\\.|(?!\1)[^\\])*\1\s*(?=\))"
)
# The role and label a line asks for, to be checked against what the code declares.
ROLE_CALL = re.compile(r"""getByRole\s*\(\s*['"`](?P<role>[^'"`]+)['"`]\s*,\s*{[^}]*\bname\s*:\s*['"`](?P<name>[^'"`]+)""")

ROLE_LOCATOR = re.compile(
    r"\bgetByRole\(\s*(['\"`])[^'\"`]+\1\s*,\s*\{(?![^}]*\bexact\b)[^}]*\bname\s*:[^}]*(?=\})"
)

# A quoted path still holding a route parameter: `/projects/$projectId/analysis`,
# `/users/:id`, `/posts/{slug}`, `/files/[name]`, or an unexpanded `${…}` template.
UNRESOLVED_ROUTE_PARAMETER = re.compile(
    r"['\"`]/[^'\"`]*(?:\$\{[^}]*\}|\$\w+|:\w+|\{[^}]*\}|\[[^\]]*\])[^'\"`]*['\"`]"
)

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

# A failed sample is retried by sampling wider, never by replaying the same mode.
# First line of every generated spec. The importer keys on it to avoid registering
# the engine's own output as a pre-existing test.
GENERATED_MARKER = (
    "// Généré par AI QA Agent — ne pas éditer à la main, la régénération écrase ce fichier."
)

RETRY_TEMPERATURE = 0.7

# The canonical Gherkin keywords, not their French translations. Gherkin does localise
# them, but the step text is already French and the UI renders Given/When/Then: emitting
# "Étant donné" in the spec while the scenario screen says "Given" left the same step
# labelled two ways. English keywords with local-language steps is also what most tooling
# expects to parse.
GHERKIN_KEYWORDS = ("Given", "When", "Then")
CONTINUATION_KEYWORD = "And"


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
            steps.append((keyword if index == 0 else CONTINUATION_KEYWORD, text))
    return steps


ROUTE_PLACEHOLDER = re.compile(r"[$:{\[]|\.\.\.")
GOTO_CALL = re.compile(r"\bpage\.goto\(\s*['\"`]([^'\"`]+)['\"`]")
# `toHaveURL` asserts an address just as `goto` visits one. Unchecked, a model that could
# not find a real route asserted an invented one instead — a test that fails on a page
# which never existed, and blames the application for it.
URL_ASSERTION = re.compile(r"\btoHaveURL\(\s*['\"`]([^'\"`]+)['\"`]")

# Anything that can change the address between two assertions. `goto` is included:
# navigating explicitly is as good a reason for the address to differ as a click.
ACTION_CALL = re.compile(r"""\b(?:goto|click|press|fill|selectOption|check|uncheck|setInputFiles|tap)\s*""")


def normalise_route(value: str) -> str:
    """Address of a URL, without origin, query or trailing slash.

    The fragment is kept when there is one. In an application that navigates by hash,
    `#cgu` *is* the page — dropping it collapsed every such route onto `/`, so a model was
    handed a single allowed address for a repository that had four, and invented the rest.
    """
    path = re.sub(r"^[a-zA-Z]+://[^/]+", "", value.strip())
    path = path.split("?")[0]
    path, _, fragment = path.partition("#")
    path = path.rstrip("/")
    if fragment:
        # `/#cgu` and `#cgu` name the same page; the hash alone is the stable form.
        return f"#{fragment}"
    return path or "/"


def reachable_routes(routes: list[str]) -> set[str]:
    """Routes a test may open directly: those carrying no parameter.

    ``/projects/$projectId`` cannot be opened by URL — the id is only known at runtime.
    A model asked for a concrete URL will otherwise invent one (`/projects/1`), which
    looks valid, passes every other check, and lands on a 404.
    """
    return {
        normalise_route(route)
        for route in routes
        if not ROUTE_PLACEHOLDER.search(route)
    }


def home_route(routes: set[str]) -> str:
    """Where a scenario starts when its opening step describes an initial state.

    "L'utilisateur se trouve sur la page d'accueil" has to become a concrete address, and
    with only a list of destinations to choose from the generator picked one of them —
    producing a test that opens the page it is about to navigate to, then asserts it
    arrived. It passes, and proves nothing.

    `/` is the answer whenever it exists, and it always does for a web application: an
    application reached only through fragments is still served at its root, and clearing
    the fragment returns there. A repository whose addresses are all sub-paths falls back
    to the shortest of them.
    """
    if not routes or "/" in routes:
        return "/"
    paths = sorted(
        (route for route in routes if route.startswith("/")),
        key=lambda route: (route.count("/"), len(route)),
    )
    # Fragments are parts of one page, so the page itself is the home.
    return paths[0] if paths else "/"


def validate_line(
    line: str,
    known_test_ids: set[str],
    allowed_routes: set[str] | None = None,
    controls: list[dict] | None = None,
    secrets: set[str] | None = None,
) -> tuple[str | None, str | None]:
    """Return ``(accepted_line, rejection_reason)``. Exactly one of them is set."""
    candidate = line.strip()
    if not candidate:
        return None, "ligne vide"
    if candidate.startswith("//"):
        return candidate, None

    # `process.` is banned so generated code cannot reach for whatever it likes. A test
    # that signs in still needs a credential, so the variables a project declared are
    # blanked before the ban is applied — the door opens exactly that far, and any other
    # environment access is still refused.
    inspected = candidate
    for name in sorted(secrets or ()):
        inspected = inspected.replace(f"process.env.{name}", "«secret»")

    if FORBIDDEN.search(inspected):
        return None, "instruction interdite (import, système de fichiers ou exécution)"
    if not STATEMENT.match(candidate):
        return None, "n'est pas une instruction Playwright"
    if not candidate.endswith(";"):
        candidate = f"{candidate};"

    # A URL still carrying a route parameter cannot be navigated to. Left alone it produces
    # a test that fails for the wrong reason, or worse, silently visits a 404.
    placeholder = UNRESOLVED_ROUTE_PARAMETER.search(candidate)
    if placeholder:
        return None, f"paramètre de route non résolu dans {placeholder.group(0)}"

    # Direct navigation is only possible to a route with no parameter. Anything else has
    # to be reached the way a user reaches it — open the list, click the row.
    if allowed_routes is not None:
        target = GOTO_CALL.search(candidate)
        if target:
            path = normalise_route(target.group(1))
            if path not in allowed_routes:
                return None, (
                    f"« {path} » n'est pas atteignable par URL directe "
                    "(navigue par l'interface)"
                )
        asserted = URL_ASSERTION.search(candidate)
        if asserted:
            path = normalise_route(asserted.group(1))
            if path not in allowed_routes:
                return None, f"« {path} » n'est pas une adresse connue de l'application"

    for test_id in TESTID_CALL.findall(candidate):
        if test_id not in known_test_ids:
            return None, f'data-testid "{test_id}" introuvable dans le code analysé'

    conflict = role_conflict(candidate, controls or [])
    if conflict:
        return None, conflict

    candidate = anchor_text_locators(candidate)

    # An un-awaited `expect(...)` returns a promise nobody resolves: it asserts nothing and
    # the test still reports green. The intent is unambiguous, so repair rather than reject.
    if NEEDS_AWAIT.match(candidate):
        candidate = f"await {candidate}"
    return candidate, None


def role_conflict(line: str, controls: list[dict]) -> str | None:
    """Reason to refuse a `getByRole` the analysed code contradicts.

    Only a *contradiction* is refused: the label exists, and never under the role asked
    for. Asking for a role an element does not have finds nothing, and Playwright waits
    out the whole timeout before saying so — thirty seconds to learn that a `<button>`
    was called a `link`.

    A label the analysis never saw is not refused. Plenty of real labels are computed at
    runtime (`<button>{item.label}</button>`), and their absence here is a limit of static
    reading, not evidence that they do not exist. Refusing them would reject correct code.
    """
    if not controls:
        return None
    known: dict[str, set[str]] = {}
    for item in controls:
        known.setdefault(item["name"], set()).add(item["role"])

    for role, name in ROLE_CALL.findall(line):
        roles = known.get(name)
        if roles and role not in roles:
            expected = ", ".join(f"'{value}'" for value in sorted(roles))
            return (
                f"« {name} » n'est pas un rôle '{role}' dans le code analysé "
                f"(rôle relevé : {expected})"
            )
    return None


def anchor_text_locators(line: str) -> str:
    """Pin text-based locators to the exact label they were written for.

    Playwright matches text by substring, so a short label resolves to every element that
    merely contains it and strict mode then refuses the step. This is the failure mode of
    any repository without `data-testid`, where text is the only handle available.
    """
    line = TEXT_LOCATOR.sub(lambda match: f"{match.group(0)}, {{ exact: true }}", line)
    # The match stops before the closing brace, which carries its own spacing; trimming
    # keeps the result readable, since this is code someone will read.
    return ROLE_LOCATOR.sub(lambda match: f"{match.group(0).rstrip()}, exact: true ", line)


def _build_prompt(
    context: FeatureContext,
    story_title: str,
    scenario_name: str,
    steps: list[tuple[str, str]],
    base_url: str,
    credentials: dict[str, str] | None = None,
) -> str:
    # Numbered from 1: with a 0-based list, small models return code shifted by one step,
    # putting an assertion under a "Quand" and an action under an "Alors".
    numbered = "\n".join(
        f"{index}. {keyword} {text}" for index, (keyword, text) in enumerate(steps, start=1)
    )
    anchors = (
        ", ".join(sorted(context.test_ids)) if context.test_ids else "aucune ancre disponible"
    )

    # Named, never valued. A credential belongs in the environment the subprocess
    # inherits: passing the value here would put it in a prompt, and from there into a
    # log, a database row and a screen.
    secret_block = (
        "Identifiants disponibles à l'exécution, à écrire ainsi et jamais en clair : "
        + ", ".join(
            f"{label} = process.env.{variable}"
            for label, variable in (credentials or {}).items()
        )
        + "\n"
        if credentials
        else ""
    )

    # Written as the call the model should produce, rather than as a table it has to
    # translate. Asking for a role an element does not have finds nothing, and Playwright
    # spends the whole timeout before saying so.
    controls = getattr(context, "controls", []) or []
    control_block = (
        "Contrôles relevés dans le code, avec le rôle exact que Playwright leur donne : "
        + ", ".join(
            f"getByRole('{item['role']}', {{ name: '{item['name']}' }})"
            for item in controls[:25]
        )
        + "\n"
        if controls
        else ""
    )

    reachable = reachable_routes(context.routes)
    home = home_route(reachable)
    reachable.add(home)
    direct = sorted(reachable)
    routes = ", ".join(direct) if direct else "aucune"

    # Offered only when the anchor exists. Stated unconditionally, the rule was followed
    # unconditionally: every generated step opened with a `waitFor` on an anchor the
    # repository does not have, and every one of them was then rejected — a spec full of
    # manual TODOs that describe nothing but the instruction that produced them.
    hydration_rule = (
        "- fais suivre chaque `page.goto(...)` de "
        "`await page.getByTestId('app-ready').waitFor();` : l'application est rendue côté "
        "serveur et un clic avant l'hydratation ne déclenche rien ;\n"
        if HYDRATION_ANCHOR in context.test_ids
        else ""
    )
    return (
        f"Application testée : {base_url}\n"
        f"Adresses connues de l'application : {routes}\n"
        "Ce sont les SEULES adresses valides : n'en invente aucune autre, ni dans un "
        "`page.goto(...)`, ni dans un `toHaveURL(...)`. Toute autre page contient un "
        "paramètre dans son URL et ne s'atteint qu'en naviguant depuis l'une d'elles.\n"
        f"Adresse d'accueil : {home}\n"
        f"{secret_block}"
        "Une étape « Given » qui décrit un état de départ — « l'utilisateur est "
        f"connecté », « sur la page d'accueil » — s'ouvre sur {home}, jamais sur la page "
        "que le scénario doit atteindre : partir de la destination ferait un test qui "
        "arrive là où il était déjà, et qui ne prouve rien.\n"
        f"Ancres data-testid réellement présentes dans le code : {anchors}\n"
        f"{control_block}\n"
        f"USER STORY : {story_title}\n"
        f"SCÉNARIO : {scenario_name}\n"
        f"ÉTAPES :\n{numbered}\n\n"
        "Pour chaque étape, donne les instructions Playwright (TypeScript) qui la réalisent.\n"
        "Règles strictes :\n"
        "- une instruction par chaîne, terminée par un point-virgule ;\n"
        f"{hydration_rule}"
        "- `page.goto(...)` n'accepte qu'une URL **concrète**. Une route contenant un "
        "paramètre (`/projects/$projectId`, `/users/:id`) ne peut pas être ouverte "
        "directement : atteins la page en naviguant comme un utilisateur — ouvre la liste, "
        "puis clique sur l'élément voulu. N'écris jamais un paramètre littéral dans une URL ;\n"
        "- préfixe d'`await` toute assertion et toute action ;\n"
        "- utilise uniquement `page.goto`, `page.getByTestId`, `page.getByRole`, "
        "`page.getByLabel`, `page.getByText`, `page.locator`, et `expect(...)` ;\n"
        "- pour les sélecteurs, privilégie les ancres data-testid listées ci-dessus. "
        "Si aucune ne convient, utilise `page.getByRole('button' | 'link' | ..., "
        "{ name: 'libellé', exact: true })` : le rôle dit ce que l'élément EST, là où "
        "`getByText` attrape aussi le moindre paragraphe contenant le mot et fait échouer "
        "l'étape entière. Mets toujours `exact: true` sur un libellé ;\n"
        "- les étapes « Alors » ne contiennent que des `expect(...)` ;\n"
        "- n'écris aucun import, aucune déclaration de test, aucun commentaire : "
        "uniquement le corps de chaque étape ;\n"
        "- produis une entrée pour CHAQUE étape numérotée. Si une étape précise résiste, "
        "laisse son `code` vide et traite les autres : ne renvoie jamais une liste "
        "`etapes` vide, ce serait abandonner le scénario entier."
    )


def contradictory_url_assertions(lines: list[str]) -> list[str]:
    """Report assertions that cannot all hold, because a page has one address at a time.

    Gherkin puts every action before every assertion, so a scenario covering four
    behaviours at once produces four clicks followed by four `toHaveURL`, each naming a
    different page. Only the last can be true; the test is unsatisfiable whatever the
    application does, and reports the product broken for a fault in the scenario.

    Two different addresses asserted with no navigation between them is the contradiction.
    Asserting, navigating, then asserting again is perfectly ordinary and is left alone.
    """
    problems: list[str] = []
    previous: str | None = None
    for line in lines:
        if ACTION_CALL.search(line):
            previous = None
            continue
        asserted = URL_ASSERTION.search(line)
        if not asserted:
            continue
        target = normalise_route(asserted.group(1))
        if previous is not None and target != previous:
            problems.append(
                f"« {previous} » et « {target} » sont affirmées sans navigation entre "
                "elles : le scénario réunit plusieurs comportements et ne peut pas être "
                "vrai en entier. Découpez-le en un scénario par page."
            )
        previous = target
    return problems


def _render_steps(
    steps: list[tuple[str, str]],
    known_test_ids: set[str],
    allowed_routes: set[str],
    controls: list[dict],
    secrets: set[str],
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
        executable = 0
        for line in by_index.get(index, []):
            valid, reason = validate_line(
                line, known_test_ids, allowed_routes, controls, secrets
            )
            if valid:
                accepted.append(valid)
                executable += 1
            elif reason and reason != "ligne vide":
                # Kept as a comment so the gap is visible in the file and in review.
                accepted.append(f"// TODO manuel ({reason}) : {line.strip()}")

        # Only a step left with nothing to run blocks the test. Dropping some extra
        # assertions from an otherwise working step is a gap worth showing, not a reason to
        # discard the assertions that do hold — marking the whole test fixme would throw
        # them away too.
        if executable == 0:
            if not accepted:
                accepted.append(
                    "// TODO manuel : étape non automatisable avec les éléments détectés"
                )
            unresolved.append(f"{keyword} {text} — aucune instruction exploitable")

        body.extend(f"      {line}" for line in accepted)
        body.append("    });")

    unresolved.extend(contradictory_url_assertions(body))
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
    credentials: dict[str, str] | None = None,
) -> GeneratedSpec:
    """Produce one ``.spec.ts`` for a single Gherkin scenario."""
    steps = flatten_steps(given, when, then)
    known_test_ids = set(context.test_ids)
    credentials = credentials or {}
    # Only the names. The values stay in the environment the subprocess inherits.
    secrets = set(credentials.values())

    prompt = _build_prompt(context, story_title, scenario_name, steps, base_url, credentials)

    # Generation is high variance: the same model and prompt can return nothing usable on
    # one call and a fully valid set on the next. A spec where *every* step failed is far
    # more likely to be a bad roll than a genuinely unautomatable scenario, so it is worth
    # a second attempt.
    #
    # That attempt must *diverge*, not converge: retrying at temperature 0 would replay the
    # most likely answer, which is exactly the one that just failed. It samples higher
    # instead, and says plainly what was wrong with the previous reply.
    allowed_routes = reachable_routes(context.routes)
    # The home is navigable whether or not a router declared it, so it belongs among the
    # addresses a test may open — otherwise the very address the prompt recommends for an
    # opening step would be refused by the check below it.
    allowed_routes.add(home_route(allowed_routes))
    controls = getattr(context, "controls", []) or []
    body, unresolved = _render_steps(
        steps, known_test_ids, allowed_routes, controls, secrets, prompt, temperature=0.2
    )
    if len(unresolved) >= len(steps):
        logger.info("Every step came back unusable for %s; retrying", scenario_id)
        retry_prompt = (
            f"{prompt}\n\n"
            "Ta réponse précédente ne contenait aucune instruction exploitable. Reprends : "
            "une entrée par étape numérotée, avec au moins une instruction Playwright "
            "valide pour les étapes que les ancres permettent d'atteindre."
        )
        retry_body, retry_unresolved = _render_steps(
            steps,
            known_test_ids,
            allowed_routes,
            controls,
            secrets,
            retry_prompt,
            temperature=RETRY_TEMPERATURE,
        )
        if len(retry_unresolved) < len(unresolved):
            body, unresolved = retry_body, retry_unresolved

    header = [
        GENERATED_MARKER,
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
