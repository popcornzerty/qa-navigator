"""User Story and Gherkin generation from analysed code, using the local Ollama runtime.

Division of labour, on purpose:

* **Deterministic** — which files exist, which routes and components they declare, which
  ``data-testid`` anchors are available, and the confidence score. This comes from the
  analyzer and is never delegated to a model.
* **Generated** — only the natural-language layer: the story wording, its acceptance
  criteria and the Gherkin steps.

A story therefore always traces back to real evidence, and a hallucinated route cannot
enter the backlog: source files and confidence are copied from the feature, not invented.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from qa_engine import ollama
from qa_engine.config import settings

logger = logging.getLogger(__name__)

MAX_STORIES_PER_FEATURE = 3
MAX_CRITERIA_PER_STORY = 4
MAX_SCENARIOS_PER_STORY = 2
# A scenario title is scanned down a backlog and becomes a Jira summary: it names the
# scenario, it does not recite it.
MAX_TITLE_CHARS = 80
# Words that start a Gherkin step. In a title they mark where the name stops and the
# recitation begins.
GHERKIN_OPENINGS = (
    "quand ",
    "lorsque ",
    "si ",
    "étant donné que ",
    "étant donné ",
    "alors ",
)
# A rejected sample is retried by sampling wider, never by replaying the same mode.
SCENARIO_RETRY_TEMPERATURE = 0.7
MAX_EXCERPT_FILES = 2
MAX_EXCERPT_CHARS = 1200

SYSTEM_PROMPT = (
    "Tu es analyste QA fonctionnel. Tu écris des User Stories et des scénarios Gherkin "
    "en français, à partir de faits extraits d'un code source. "
    "Tu ne décris que des comportements réellement observables par un utilisateur. "
    "Tu n'inventes jamais de route, de champ ou d'écran qui ne figure pas dans les faits "
    "fournis. Tu restes concret, court et testable. Aucun jargon technique inutile."
)

STORY_SCHEMA = {
    "type": "object",
    "properties": {
        "epic": {"type": "string"},
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titre": {"type": "string"},
                    "description": {"type": "string"},
                    "criteres_acceptation": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["titre", "description", "criteres_acceptation"],
            },
        },
    },
    "required": ["epic", "stories"],
}

SCENARIO_SCHEMA = {
    "type": "object",
    "properties": {
        "scenarios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scenario": {"type": "string"},
                    "etant_donne": {"type": "array", "items": {"type": "string"}},
                    "quand": {"type": "array", "items": {"type": "string"}},
                    "alors": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["scenario", "etant_donne", "quand", "alors"],
            },
        }
    },
    "required": ["scenarios"],
}


# What a Gherkin step must never contain. A scenario is read by whoever decides
# whether the behaviour is the wanted one, and it is what gets pushed to Jira: a step
# naming a route, a file or a selector cannot be judged by someone who does not read
# the code, and ties the requirement to an implementation free to change beneath it.
LEAKS = [
    (re.compile(r"""\s/[a-zA-Z0-9_\-]+(?:/[a-zA-Z0-9_$\-]+)*"""), "un chemin de route"),
    (re.compile(r"""\b[a-zA-Z0-9_\.-]+\.(?:tsx|ts|jsx|js|css|json)\b"""), "un nom de fichier"),
    (re.compile(r"""\bdata-testid\b"""), "une ancre de test"),
    (re.compile(r"""\b(?:localhost|https?://)[^\s]*"""), "une URL"),
    (re.compile(r"""<[A-Za-z][\w.]*\s*/?>"""), "une balise"),
]


@dataclass
class GeneratedStory:
    title: str
    description: str
    epic: str
    acceptance_criteria: list[str] = field(default_factory=list)


@dataclass
class GeneratedScenario:
    scenario: str
    given: list[str] = field(default_factory=list)
    when: list[str] = field(default_factory=list)
    then: list[str] = field(default_factory=list)


@dataclass
class FeatureContext:
    """Everything the model is allowed to reason about for one functional domain."""

    name: str
    description: str
    routes: list[str]
    components: list[str]
    api_calls: list[str]
    test_ids: list[str]
    # Labelled controls with their ARIA role, so a test can ask for what the element
    # actually is instead of guessing between a button and a link.
    controls: list[dict]
    has_form: bool
    source_files: list[str]
    excerpts: list[tuple[str, str]] = field(default_factory=list)

    def as_prompt_block(self) -> str:
        lines = [
            f"DOMAINE FONCTIONNEL : {self.name}",
            f"Résumé de l'analyse statique : {self.description}",
            "",
            f"Routes exposées : {', '.join(self.routes) if self.routes else 'aucune'}",
            f"Composants : {', '.join(self.components[:20]) if self.components else 'aucun'}",
            f"Appels API : {', '.join(self.api_calls) if self.api_calls else 'aucun'}",
            f"Formulaire présent : {'oui' if self.has_form else 'non'}",
        ]
        if self.test_ids:
            lines.append(f"Ancres de test (data-testid) : {', '.join(self.test_ids[:25])}")
        if self.excerpts:
            lines.append("")
            lines.append("EXTRAITS DE CODE :")
            for path, content in self.excerpts:
                lines.append(f"--- {path} ---")
                lines.append(content)
        return "\n".join(lines)


def build_context(feature_row, repository_path: str) -> FeatureContext:
    """Assemble the evidence block for one feature, including trimmed source excerpts."""
    evidence = feature_row.evidence or {}
    source_files = feature_row.source_files or []
    root = Path(repository_path)

    excerpts: list[tuple[str, str]] = []
    for relative in source_files[:MAX_EXCERPT_FILES]:
        candidate = root / relative
        try:
            content = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        excerpts.append((relative, content[:MAX_EXCERPT_CHARS]))

    return FeatureContext(
        name=feature_row.name,
        description=feature_row.description,
        routes=evidence.get("routes", []),
        components=evidence.get("components", []),
        api_calls=evidence.get("api_calls", []),
        test_ids=evidence.get("test_ids", []),
        controls=evidence.get("controls", []),
        has_form=bool(evidence.get("has_form")),
        source_files=source_files,
        excerpts=excerpts,
    )


def generate_stories(context: FeatureContext) -> list[GeneratedStory]:
    """Ask the local model for the User Stories covering one functional domain."""
    prompt = (
        f"{context.as_prompt_block()}\n\n"
        f"Rédige au maximum {MAX_STORIES_PER_FEATURE} User Stories couvrant ce domaine.\n"
        "Chaque User Story doit :\n"
        '- avoir un titre court à l\'impératif ou à l\'infinitif (ex : "Filtrer les projets par statut") ;\n'
        '- avoir une description au format "En tant que <rôle>, je veux <action> afin de <bénéfice>." ;\n'
        f"- lister entre 2 et {MAX_CRITERIA_PER_STORY} critères d'acceptation, chacun étant une "
        "affirmation vérifiable, au présent, sans « devrait ».\n"
        "Donne aussi le nom de l'epic regroupant ces stories.\n"
        "N'invente aucune fonctionnalité absente des faits ci-dessus.\n"
        "Interdits dans les critères : URL, chemin de route, sélecteur CSS, nom de "
        "composant, nom de fichier, titre d'onglet du navigateur, intervalle de "
        "rafraîchissement, et tout détail interne invisible pour l'utilisateur. Désigne "
        'les écrans par leur nom métier (« la page de détail du projet », pas '
        '« /projects/$id »).\n'
        "Rédige un français correct : les critères commencent par un groupe nominal ou un "
        "verbe conjugué (« Le bouton Analyser est visible »), jamais par un infinitif "
        "déformé."
    )
    payload = ollama.chat_json(SYSTEM_PROMPT, prompt, STORY_SCHEMA)

    epic = str(payload.get("epic") or context.name).strip()
    stories: list[GeneratedStory] = []
    for raw in payload.get("stories", [])[:MAX_STORIES_PER_FEATURE]:
        title = str(raw.get("titre", "")).strip()
        if not title:
            continue
        criteria = [
            str(item).strip()
            for item in raw.get("criteres_acceptation", [])
            if str(item).strip()
        ][:MAX_CRITERIA_PER_STORY]
        stories.append(
            GeneratedStory(
                title=title,
                description=str(raw.get("description", "")).strip(),
                epic=epic,
                acceptance_criteria=criteria,
            )
        )
    return stories


def technical_leak(step: str) -> str | None:
    """Name the implementation detail a Gherkin step should not contain.

    A scenario is read by whoever decides whether the behaviour is the wanted one, and it
    is the artefact pushed to Jira. "L'API /auth/login est appelée" describes a call, not
    a behaviour: it cannot be judged by someone who does not read the code, and it ties
    the requirement to an implementation that may change without the behaviour changing.

    The prompt already forbids this, and the model obeys most of the time. Most of the
    time is not a guarantee, so the rule is checked.
    """
    for pattern, label in LEAKS:
        found = pattern.search(step)
        if found:
            return f"{label} « {found.group(0).strip()} »"
    return None


def tidy_title(title: str) -> str:
    """Turn a recited scenario into a name for it.

    "Quand l'utilisateur clique sur le bouton de connexion, le formulaire de connexion
    s'affiche sur la page d'accueil." restates the steps that follow it. These titles are
    what a reader scans down a backlog and what becomes a Jira summary, where a whole
    sentence costs more than it says.

    Repaired rather than refused. Rejecting a scenario over its label would discard the
    behaviour it describes for a cosmetic fault — and did exactly that: both samples of a
    login flow opened with "Quand", every scenario was thrown away, and the regeneration
    produced nothing at all.
    """
    cleaned = " ".join(title.split()).rstrip(".")
    lowered = cleaned.lower()
    for keyword in GHERKIN_OPENINGS:
        if lowered.startswith(keyword):
            cleaned = cleaned[len(keyword):]
            # What follows the keyword is the action; the clause after the comma is its
            # result, already stated by the steps.
            cleaned = cleaned.split(",")[0].strip()
            break

    # A keyword can also appear part-way through, when a good name is followed by the
    # steps themselves: "Ouvrir le formulaire de connexion Étant donné que…". The name is
    # what precedes it.
    lowered = cleaned.lower()
    cut = min(
        (position for position in (lowered.find(f" {word}") for word in GHERKIN_OPENINGS) if position > 0),
        default=-1,
    )
    if cut > 0:
        cleaned = cleaned[:cut].rstrip(" ,;:—-")

    if len(cleaned) > MAX_TITLE_CHARS:
        cut = cleaned.rfind(" ", 0, MAX_TITLE_CHARS)
        cleaned = cleaned[: cut if cut > 0 else MAX_TITLE_CHARS].rstrip(" ,;")

    return cleaned[:1].upper() + cleaned[1:] if cleaned else title.strip()


def _clean_scenario(candidate: "GeneratedScenario") -> tuple[bool, str | None]:
    """Whether a scenario is fit to publish, and what disqualified it.

    Only substance disqualifies. A clumsy title is repaired by the caller.
    """
    for bucket in (candidate.given, candidate.when, candidate.then):
        for step in bucket:
            leak = technical_leak(step)
            if leak:
                return False, leak
    return True, None


def generate_scenarios(context: FeatureContext, story: GeneratedStory) -> list[GeneratedScenario]:
    """Turn one story and its criteria into Gherkin scenarios."""
    criteria = "\n".join(f"- {item}" for item in story.acceptance_criteria) or "- (aucun)"
    anchors = (
        f"Ancres de test disponibles : {', '.join(context.test_ids[:25])}\n"
        if context.test_ids
        else ""
    )
    prompt = (
        f"{context.as_prompt_block()}\n\n"
        f"USER STORY : {story.title}\n"
        f"{story.description}\n\n"
        f"CRITÈRES D'ACCEPTATION :\n{criteria}\n\n"
        f"{anchors}"
        f"Écris 1 à {MAX_SCENARIOS_PER_STORY} scénarios Gherkin couvrant ces critères.\n"
        "Contraintes :\n"
        "- **un seul scénario suffit** si la story n'a qu'un seul chemin. N'ajoute un "
        "deuxième scénario que s'il teste un cas réellement différent (erreur, cas limite, "
        "donnée absente). Ne duplique jamais un scénario en changeant seulement son titre ;\n"
        "- « étant donné » = état initial, « quand » = **uniquement l'action de "
        "l'utilisateur**, « alors » = **uniquement le résultat observé**. Ne mets jamais un "
        "résultat dans « quand » ;\n"
        "- **un scénario = un comportement.** Toutes les actions précèdent toutes les "
        "assertions : si tu enchaînes quatre clics puis quatre résultats, seul le dernier "
        "peut être vrai et le scénario devient impossible à satisfaire. Quatre pages à "
        "vérifier, ce sont quatre scénarios — ou un seul, sur une page représentative ;\n"
        "- un « alors » décrit l'état **après toutes** les actions, jamais un état "
        "intermédiaire. « Le formulaire est affiché » placé après l'envoi du formulaire "
        "est faux : à ce moment-là le formulaire a disparu. Si tu as besoin d'observer "
        "une étape intermédiaire, coupe le scénario en deux ;\n"
        "- le **titre** nomme le scénario en quelques mots (« Ouvrir le formulaire de "
        "connexion »). Il ne le récite pas : ne commence jamais un titre par « Quand », "
        "« Lorsque » ou « Alors », et ne répète pas les étapes qui suivent ;\n"
        "- chaque étape est une phrase courte à l'infinitif ou au présent, sans « je » ;\n"
        "- interdits : URL, chemin de route, sélecteur CSS, nom de composant, nom de "
        "fichier, titre d'onglet du navigateur. Désigne les écrans par leur nom métier "
        '(« la page de détail du projet », pas « /projects/$id »).'
    )
    scenarios, leak = _collect_scenarios(prompt)
    if leak:
        # Dropping the scenario would lose a legitimate flow over one badly worded step.
        # Sampled again, with the offence named, the model usually rewrites it in business
        # terms — the same treatment a wholly unusable spec already gets.
        logger.info("Regenerating scenarios: %s", leak)
        scenarios, _ = _collect_scenarios(
            f"{prompt}\n\nTa réponse précédente contenait {leak}, ce qui est interdit. "
            "Récris les scénarios en ne décrivant que ce qu'un utilisateur voit à l'écran.",
            temperature=SCENARIO_RETRY_TEMPERATURE,
        )
    return scenarios


def _collect_scenarios(
    prompt: str, temperature: float = 0.2
) -> tuple[list[GeneratedScenario], str | None]:
    """One sampling round: the usable scenarios, and the first leak that spoiled one."""
    payload = ollama.chat_json(SYSTEM_PROMPT, prompt, SCENARIO_SCHEMA, temperature=temperature)

    rejected: str | None = None
    scenarios: list[GeneratedScenario] = []
    seen: set[tuple[str, ...]] = set()
    for raw in payload.get("scenarios", [])[:MAX_SCENARIOS_PER_STORY]:
        name = str(raw.get("scenario", "")).strip()
        if not name:
            continue
        candidate = GeneratedScenario(
            scenario=tidy_title(name),
            given=[str(x).strip() for x in raw.get("etant_donne", []) if str(x).strip()],
            when=[str(x).strip() for x in raw.get("quand", []) if str(x).strip()],
            then=[str(x).strip() for x in raw.get("alors", []) if str(x).strip()],
        )
        # Small models pad up to the requested count by restating the same scenario under
        # a new title. Identical steps mean one scenario, whatever the title says.
        fingerprint = _fingerprint(candidate)
        if fingerprint in seen:
            logger.info("Dropping duplicate scenario %r", name)
            continue
        acceptable, leak = _clean_scenario(candidate)
        if not acceptable:
            logger.info("Dropping scenario %r: %s", name, leak)
            rejected = rejected or leak
            continue

        seen.add(fingerprint)
        scenarios.append(candidate)
    return scenarios, rejected


def _fingerprint(scenario: GeneratedScenario) -> tuple[str, ...]:
    """Title-independent identity of a scenario: its normalised steps."""

    def normalise(step: str) -> str:
        return " ".join(step.lower().replace("'", " ").split()).rstrip(".")

    return tuple(normalise(step) for step in (*scenario.given, *scenario.when, *scenario.then))


def describe_engine() -> str:
    return f"{settings.ollama_model} ({settings.generation_language})"
