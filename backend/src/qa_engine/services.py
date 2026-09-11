"""Analysis pipeline and identifier allocation.

The pipeline is expressed as an ordered list of steps whose state is persisted on the
Analysis row, so the frontend's analysis screen reflects real backend progress instead of
a simulation. Steps that are not implemented yet stay ``pending`` with an explicit reason
rather than being reported as completed.
"""

from __future__ import annotations

import logging
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from qa_engine import execution, generation, jira, playwright_gen
from qa_engine.analyzer import extract_repository_metadata
from qa_engine.config import settings
from qa_engine.database import SessionLocal
from qa_engine.features import group_symbols, shared_test_ids
from qa_engine import discovery
from qa_engine.repositories import LocalRepositoryProvider
from qa_engine.repositories import GitCloneError, GitRepositoryProvider
from qa_engine.models import (
    AcceptanceCriterion,
    Analysis,
    Feature,
    GherkinScenario,
    PlaywrightTest,
    Project,
    TestRun,
    UserStory,
)
from qa_engine.ollama import OllamaError

logger = logging.getLogger(__name__)

STEPS: list[tuple[str, str]] = [
    ("repository", "Repository"),
    ("architecture", "Architecture"),
    ("routes", "Routes"),
    ("components", "Components"),
    ("apis", "APIs"),
    ("existing_tests", "Existing tests"),
    ("features", "Features"),
    ("stories", "User Stories"),
    ("gherkin", "Gherkin"),
]


def initial_steps() -> list[dict]:
    return [{"key": key, "label": label, "status": "pending"} for key, label in STEPS]


def next_reference(db: Session, model, prefix: str, width: int = 3) -> str:
    """Allocate the next human-readable identifier, e.g. ``US-004``.

    Readable ids matter here: they are what appears in Jira, in generated ``.spec.ts``
    file headers and in traceability reports.
    """
    count = db.scalar(select(func.count()).select_from(model)) or 0
    candidate = count + 1
    while db.get(model, f"{prefix}-{candidate:0{width}d}") is not None:
        candidate += 1
    return f"{prefix}-{candidate:0{width}d}"


def _detect_stack(repository_path: str, extensions: dict[str, int]) -> str:
    root = Path(repository_path)
    package_json = root / "package.json"
    hints: list[str] = []
    if package_json.is_file():
        try:
            content = package_json.read_text(encoding="utf-8")
        except OSError:
            content = ""
        for name, libel in (
            ('"react"', "React"),
            ('"next"', "Next.js"),
            ('"vue"', "Vue"),
            ('"@angular/core"', "Angular"),
            ('"svelte"', "Svelte"),
            ('"@tanstack/react-router"', "TanStack Router"),
            ('"vite"', "Vite"),
            ('"playwright"', "Playwright"),
        ):
            if name in content:
                hints.append(libel)
    if ".ts" in extensions or ".tsx" in extensions:
        hints.append("TypeScript")
    return " + ".join(dict.fromkeys(hints)) or "Stack non identifiée"


class _StepWriter:
    """Persists step transitions so a polling client sees progress as it happens."""

    def __init__(self, db: Session, analysis: Analysis):
        self.db = db
        self.analysis = analysis
        self.steps = initial_steps()
        self._flush()

    def _flush(self) -> None:
        completed = sum(1 for step in self.steps if step["status"] == "completed")
        self.analysis.steps = [dict(step) for step in self.steps]
        self.analysis.progress = round(completed / len(self.steps) * 100)
        self.db.commit()

    def start(self, key: str) -> None:
        for step in self.steps:
            if step["key"] == key:
                step["status"] = "running"
        self._flush()

    def complete(self, key: str, detail: str) -> None:
        for step in self.steps:
            if step["key"] == key:
                step.update(status="completed", detail=detail)
        self._flush()

    def skip(self, key: str, detail: str) -> None:
        for step in self.steps:
            if step["key"] == key:
                step.update(status="pending", detail=detail)
        self._flush()

    def fail(self, key: str, detail: str) -> None:
        for step in self.steps:
            if step["key"] == key:
                step.update(status="failed", detail=detail)
        self._flush()


def _discard_untouched_stories(db: Session, project_id: str) -> None:
    """Drop previously generated stories that nobody has reviewed yet.

    Anything a human has touched — approved, edited, pushed to Jira, or imported — is a
    deliberate artefact and survives re-analysis. Only untouched drafts are regenerated.
    """
    stale = list(
        db.scalars(
            select(UserStory).where(
                UserStory.project_id == project_id,
                UserStory.origin == "generated",
                UserStory.story_status == "draft",
            )
        )
    )
    for story in stale:
        db.execute(delete(GherkinScenario).where(GherkinScenario.user_story_id == story.id))
        db.execute(delete(AcceptanceCriterion).where(AcceptanceCriterion.user_story_id == story.id))
        db.delete(story)
    db.commit()


def _generate_backlog(db: Session, project: Project, writer: "_StepWriter") -> str | None:
    """Generate User Stories then Gherkin for every detected feature.

    Returns an error message when generation could not run, in which case the affected
    steps are marked failed and the analysis keeps the deterministic results it produced.
    """
    if not settings.generation_enabled:
        writer.skip("stories", "Génération désactivée (GENERATION_ENABLED=false)")
        writer.skip("gherkin", "Génération désactivée (GENERATION_ENABLED=false)")
        return None

    features = list(
        db.scalars(
            select(Feature)
            .where(Feature.project_id == project.id)
            .order_by(Feature.confidence.desc())
        )
    )
    total_features = len(features)
    if settings.generation_max_features > 0:
        features = features[: settings.generation_max_features]

    writer.start("stories")
    started = time.monotonic()
    _discard_untouched_stories(db, project.id)

    created: list[UserStory] = []
    contexts: dict[str, generation.FeatureContext] = {}
    try:
        for feature in features:
            context = generation.build_context(feature, project.repository_path)
            contexts[feature.id] = context
            for draft in generation.generate_stories(context):
                story = UserStory(
                    id=next_reference(db, UserStory, "US"),
                    project_id=project.id,
                    feature_id=feature.id,
                    feature_name=feature.name,
                    epic=draft.epic,
                    title=draft.title,
                    description=draft.description,
                    # Confidence is evidence-based, never asked of the model.
                    confidence=feature.confidence,
                    source_files=feature.source_files,
                    origin="generated",
                    story_status="draft",
                )
                db.add(story)
                db.flush()
                for index, text in enumerate(draft.acceptance_criteria, start=1):
                    db.add(
                        AcceptanceCriterion(
                            id=f"{story.id}-AC-{index:02d}",
                            user_story_id=story.id,
                            text=text,
                            covered=False,
                        )
                    )
                created.append(story)
            db.commit()
    except OllamaError as exc:
        db.commit()
        message = str(exc)
        logger.warning("Story generation stopped: %s", message)
        writer.fail("stories", f"Génération interrompue : {message[:160]}")
        writer.fail("gherkin", "Non exécuté : la génération des User Stories a échoué")
        return message

    scope = (
        f"{len(features)}/{total_features} domaines"
        if len(features) < total_features
        else f"{total_features} domaines"
    )
    writer.complete(
        "stories",
        f"{len(created)} User Stories sur {scope} — {generation.describe_engine()} "
        f"en {time.monotonic() - started:.0f}s",
    )

    writer.start("gherkin")
    started = time.monotonic()
    scenario_count = 0
    try:
        for story in created:
            context = contexts.get(story.feature_id or "")
            if context is None:
                continue
            draft = generation.GeneratedStory(
                title=story.title,
                description=story.description,
                epic=story.epic,
                acceptance_criteria=[item.text for item in story.acceptance_criteria],
            )
            for index, item in enumerate(generation.generate_scenarios(context, draft), start=1):
                db.add(
                    GherkinScenario(
                        id=f"{story.id}-SC-{index}",
                        user_story_id=story.id,
                        project_id=project.id,
                        feature=story.feature_name,
                        scenario=item.scenario,
                        given=item.given,
                        when=item.when,
                        then=item.then,
                        scenario_status="draft",
                    )
                )
                scenario_count += 1
            db.commit()
    except OllamaError as exc:
        db.commit()
        message = str(exc)
        logger.warning("Gherkin generation stopped: %s", message)
        writer.fail("gherkin", f"Génération interrompue : {message[:160]}")
        return message

    writer.complete(
        "gherkin", f"{scenario_count} scénarios générés en {time.monotonic() - started:.0f}s"
    )
    return None



def _sync_working_copy(project: Project) -> str | None:
    """Refresh the working copy for git projects. Returns the checked-out revision."""
    if project.provider != "github" or not project.repository_url:
        return None
    provider = GitRepositoryProvider(
        project.repository_url, project.branch, settings.clone_root
    )
    provider.sync()
    # The slug is deterministic, but a project created before a URL change would still
    # point at the old directory; keep the row aligned with what was actually cloned.
    project.repository_path = str(provider.root)
    return provider.head_revision()


def _relink_stories_to_features(db: Session, project_id: str) -> int:
    """Re-attach stories to the freshly created feature rows.

    Features are deleted and rebuilt by every analysis, so their ids change and each
    existing story is left pointing at a row that no longer exists. Nothing visible breaks
    — the feature name is denormalised on the story — but Playwright generation silently
    stops working, because it reads the selector anchors from the feature.

    Matching is on the feature name, which is derived from the domain and stable across
    analyses.
    """
    features = {
        feature.name: feature.id
        for feature in db.scalars(select(Feature).where(Feature.project_id == project_id))
    }
    relinked = 0
    for story in db.scalars(select(UserStory).where(UserStory.project_id == project_id)):
        target = features.get(story.feature_name)
        if target and story.feature_id != target:
            story.feature_id = target
            relinked += 1
    if relinked:
        db.commit()
    return relinked


def import_existing_tests(db: Session, project: Project) -> tuple[int, int]:
    """Register the tests the repository already ships with.

    Returns ``(tests, files)``. Existing rows are matched on file and title rather than
    replaced wholesale, so a re-analysis keeps the execution history of a test that is
    still there, and drops only the ones that genuinely disappeared.
    """
    root = Path(project.repository_path)
    try:
        candidates = LocalRepositoryProvider(root).test_files()
    except ValueError:
        return 0, 0

    generated_files = set(
        db.scalars(
            select(PlaywrightTest.file).where(
                PlaywrightTest.project_id == project.id,
                PlaywrightTest.origin == "generated",
            )
        )
    )

    existing = {
        (row.file, row.selector): row
        for row in db.scalars(
            select(PlaywrightTest).where(
                PlaywrightTest.project_id == project.id,
                PlaywrightTest.origin == "discovered",
            )
        )
    }
    seen: set[tuple[str, str | None]] = set()
    imported = 0
    files = 0

    for candidate in candidates:
        if candidate.relative_path in generated_files:
            continue
        try:
            text = candidate.absolute_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # The engine's own specs live in the analysed repository. Re-importing them would
        # list every generated test twice, once under each origin.
        if playwright_gen.GENERATED_MARKER in text:
            continue

        found = discovery.extract_tests(text, candidate.relative_path)
        if not found:
            continue

        config = discovery.find_config(root, candidate.relative_path)
        if config is None:
            # Without a config Playwright has no testDir, no webServer and no baseURL:
            # the file can be listed but not run, so it is not offered as runnable.
            logger.info("No Playwright config governs %s; skipped", candidate.relative_path)
            continue
        working_directory = config.parent.relative_to(root).as_posix()
        playwright_project = discovery.project_for(
            config.read_text(encoding="utf-8"), config.parent, candidate.absolute_path
        )

        files += 1
        for test in found:
            key = (test.file, test.full_title)
            seen.add(key)
            row = existing.get(key)
            if row is None:
                row = PlaywrightTest(
                    id=next_reference(db, PlaywrightTest, "pw"),
                    project_id=project.id,
                    origin="discovered",
                    file=test.file,
                    selector=test.full_title,
                    test_status="not_run",
                )
                db.add(row)
                db.flush()  # so the next next_reference() sees this id
            row.scenario = test.full_title
            row.line = test.line
            row.working_directory = working_directory
            row.playwright_project = playwright_project
            imported += 1

    for key, row in existing.items():
        if key not in seen:
            db.delete(row)

    db.commit()
    return imported, files


def run_analysis(analysis_id: str) -> None:
    """In-process job runner, deliberately replaceable by Celery/RQ later."""
    db = SessionLocal()
    try:
        analysis = db.get(Analysis, analysis_id)
        if not analysis:
            return
        project = db.get(Project, analysis.project_id)
        if not project:
            analysis.status, analysis.error = "failed", "Project no longer exists"
            db.commit()
            return

        analysis.status = "running"
        project.project_status = "analyzing"
        db.commit()

        writer = _StepWriter(db, analysis)

        writer.start("repository")
        try:
            revision = _sync_working_copy(project)
        except GitCloneError as exc:
            # A clone failure is about the repository, not about the engine: name the
            # failing step and the reason instead of surfacing a bare stack trace.
            writer.fail("repository", str(exc)[:200])
            analysis.status = "failed"
            analysis.error = str(exc)
            analysis.completed_at = datetime.now(timezone.utc)
            project.project_status = "error"
            db.commit()
            return
        summary, symbols = extract_repository_metadata(project.repository_path)
        detail = f"{summary['files_scanned']} fichiers analysés"
        if revision:
            detail = f"{detail} · {project.branch}@{revision}"
        writer.complete("repository", detail)

        writer.start("architecture")
        stack = _detect_stack(project.repository_path, summary["file_extensions"])
        writer.complete("architecture", stack)

        counts = Counter(symbol.kind for symbol in symbols)
        writer.start("routes")
        # Distinct addresses, not occurrences: the same `#cgu` declared in the menu and on
        # the login screen is one page, and reporting eight of them for an application
        # with four invites the reader to think the analysis found more than it did.
        addresses = {symbol.name for symbol in symbols if symbol.kind == "route"}
        writer.complete("routes", f"{len(addresses)} routes détectées")
        writer.start("components")
        writer.complete("components", f"{counts['component']} composants indexés")
        writer.start("apis")
        writer.complete("apis", f"{counts['api_call']} appels API référencés")

        writer.start("existing_tests")
        imported, test_files = import_existing_tests(db, project)
        writer.complete(
            "existing_tests",
            f"{imported} tests existants dans {test_files} fichiers"
            if imported
            else "aucun test existant détecté",
        )

        writer.start("features")
        discovered = group_symbols(symbols)
        # Layout anchors (navigation, page title, project switcher) belong to no domain
        # but are reachable from every screen, so every feature gets to use them.
        shared_anchors = shared_test_ids(symbols)
        db.execute(delete(Feature).where(Feature.project_id == project.id))
        db.add_all(
            [
                Feature(
                    project_id=project.id,
                    analysis_id=analysis.id,
                    key=feature.key,
                    name=feature.name,
                    description=feature.description,
                    confidence=feature.confidence,
                    source_files=feature.source_files,
                    evidence={
                        "routes": feature.routes,
                        "components": feature.components,
                        "api_calls": feature.api_calls,
                        "test_ids": sorted(set(feature.test_ids) | set(shared_anchors)),
                        "controls": feature.controls,
                        "fields": feature.fields,
                        "texts": feature.texts,
                        "has_form": feature.has_form,
                    },
                )
                for feature in discovered
            ]
        )
        db.commit()
        relinked = _relink_stories_to_features(db, project.id)
        detail = f"{len(discovered)} domaines fonctionnels"
        if relinked:
            detail = f"{detail} · {relinked} stories réassociées"
        writer.complete("features", detail)

        generation_error = _generate_backlog(db, project, writer)

        detached = _detach_stale_generated_tests(db, project.id)
        if detached:
            logger.info("%d generated tests no longer match their scenario", detached)
            summary["stale_generated_tests"] = detached

        summary["stack"] = stack
        summary["features_detected"] = len(discovered)
        if generation_error:
            analysis.error = generation_error
        analysis.summary = summary
        analysis.status = "completed"
        analysis.completed_at = datetime.now(timezone.utc)
        project.project_status = "ready"
        project.last_analysis = analysis.completed_at
        db.commit()
    except Exception as exc:  # Persist the failure so the UI can report it via polling.
        logger.exception("Analysis %s failed", analysis_id)
        db.rollback()
        analysis = db.get(Analysis, analysis_id)
        if analysis:
            analysis.status = "failed"
            analysis.error = str(exc)
            analysis.completed_at = datetime.now(timezone.utc)
            project = db.get(Project, analysis.project_id)
            if project:
                project.project_status = "error"
            db.commit()
    finally:
        db.close()


DEFAULT_BASE_URL = "http://localhost:8080"


def playwright_setting(project: Project, name: str, fallback: str) -> str:
    """Read one Playwright project setting.

    Settings are persisted under their field names while the API speaks camelCase, so a
    stored `test_directory` was never found by a lookup for `testDirectory` — changing it
    on the Settings screen quietly did nothing. Both spellings are accepted so existing
    rows keep working.
    """
    stored = project.playwright_config or {}
    camel = name.split("_")[0] + "".join(part.title() for part in name.split("_")[1:])
    return stored.get(name) or stored.get(camel) or fallback


def declared_credentials(project: Project) -> dict[str, str]:
    """Environment variables this project lets a generated test read.

    Only the ones actually present are offered: naming a variable the runner will not have
    produces a spec that fills a field with `undefined` and fails on the application rather
    than on the missing configuration.
    """
    declared = (project.playwright_config or {}).get("credentials") or {}
    return {label: name for label, name in declared.items() if os.environ.get(name)}


def _base_url_for(project: Project) -> str:
    """The address a generated spec should navigate to.

    A value someone actually chose wins. The stored default is not such a choice, so the
    repository's own Playwright config is preferred over it: that config names the
    application its suite targets, and a spec sent to a default port would exercise
    nothing — or, worse, something else that happens to be listening.
    """
    configured = playwright_setting(project, "base_url", "")
    if configured and configured != DEFAULT_BASE_URL:
        return configured

    config = discovery.find_repository_config(Path(project.repository_path))
    if config is not None:
        try:
            declared = discovery.base_url_of(config.read_text(encoding="utf-8"))
        except OSError:
            declared = None
        if declared:
            return declared
    return configured or DEFAULT_BASE_URL


def playwright_root(project: Project) -> Path:
    """The directory a generated spec must live under to be runnable.

    A spec written at the repository root of a monorepo cannot run: the installation and
    the config sit beside the application, and Playwright invoked from the root resolves
    `@playwright/test` from an npx download instead, dying on the import line. The
    repository's own config decides, and the root is only the fallback for a repository
    that has none.
    """
    root = Path(project.repository_path)
    config = discovery.find_repository_config(root)
    return config.parent if config else root


GENERATED_SUBDIR = "generated"


def generate_backlog_for_feature(feature_id: str) -> None:
    """Generate User Stories and Gherkin for one functional domain.

    An analysis generates for the highest-scoring domains only, because each one costs
    minutes of local inference. Splitting screens into their own domains made that cap
    bite: eighteen were detected where one used to be, and fifteen were left with nothing.
    This is the way to ask for a particular one — the login screen, say — without paying
    for the seventeen others.
    """
    db = SessionLocal()
    try:
        feature = db.get(Feature, feature_id)
        if not feature:
            return
        project = db.get(Project, feature.project_id)
        if not project:
            return

        context = generation.build_context(feature, project.repository_path)
        # Only this domain's untouched drafts: a story a human reviewed survives, and so
        # does every other domain's backlog.
        for story in db.scalars(
            select(UserStory).where(
                UserStory.feature_id == feature.id,
                UserStory.origin == "generated",
                UserStory.story_status == "draft",
            )
        ):
            db.execute(delete(GherkinScenario).where(GherkinScenario.user_story_id == story.id))
            db.execute(delete(AcceptanceCriterion).where(AcceptanceCriterion.user_story_id == story.id))
            db.delete(story)
        db.commit()

        created: list[UserStory] = []
        for draft in generation.generate_stories(context):
            story = UserStory(
                id=next_reference(db, UserStory, "US"),
                project_id=project.id,
                feature_id=feature.id,
                feature_name=feature.name,
                epic=draft.epic,
                title=draft.title,
                description=draft.description,
                confidence=feature.confidence,
                source_files=feature.source_files,
                origin="generated",
                story_status="draft",
            )
            db.add(story)
            db.flush()
            for index, text in enumerate(draft.acceptance_criteria, start=1):
                db.add(
                    AcceptanceCriterion(
                        id=f"{story.id}-AC-{index:02d}",
                        user_story_id=story.id,
                        text=text,
                        covered=False,
                    )
                )
            created.append(story)
        db.commit()

        for story in created:
            draft = generation.GeneratedStory(
                title=story.title,
                description=story.description,
                epic=story.epic,
                acceptance_criteria=[item.text for item in story.acceptance_criteria],
            )
            for index, item in enumerate(generation.generate_scenarios(context, draft), start=1):
                db.add(
                    GherkinScenario(
                        id=f"{story.id}-SC-{index}",
                        user_story_id=story.id,
                        project_id=project.id,
                        feature=story.feature_name,
                        scenario=item.scenario,
                        given=item.given,
                        when=item.when,
                        then=item.then,
                        scenario_status="draft",
                    )
                )
            db.commit()
        logger.info("Generated %d stories for feature %s", len(created), feature.name)
    except OllamaError as exc:
        db.rollback()
        logger.warning("Generation failed for feature %s: %s", feature_id, exc)
    except Exception:
        db.rollback()
        logger.exception("Generation crashed for feature %s", feature_id)
    finally:
        db.close()


def spec_directory(project: Project) -> Path:
    """Where generated specs are written: inside the analysed repository.

    Playwright only runs what its `testDir` covers, so a spec placed anywhere else is
    reported as "No tests found" however correct the file is. The repository's own config
    therefore decides the directory, and the specs go in a `generated/` subfolder of it —
    collected like any other test, and still plainly separate from the suite a person
    wrote. Only a repository with no config at all falls back to the configured name.

    This writes into the user's git tree. Generated files carry a header saying so, and
    regeneration overwrites them.
    """
    root = playwright_root(project)
    config = discovery.find_repository_config(Path(project.repository_path))
    collected = None
    if config is not None:
        try:
            collected = discovery.collected_dir_of(config.read_text(encoding="utf-8"))
        except OSError:
            collected = None

    if collected:
        directory = (root / collected / GENERATED_SUBDIR).resolve()
    else:
        directory = root / playwright_setting(project, "test_directory", "tests")

    directory.mkdir(parents=True, exist_ok=True)
    return directory


def generate_playwright_for_scenario(scenario_id: str) -> None:
    """Generate, validate and persist one ``.spec.ts`` for a Gherkin scenario."""
    db = SessionLocal()
    try:
        scenario = db.get(GherkinScenario, scenario_id)
        if not scenario:
            return
        story = db.get(UserStory, scenario.user_story_id)
        project = db.get(Project, scenario.project_id)
        if not story or not project:
            return

        feature = db.get(Feature, story.feature_id) if story.feature_id else None
        if feature is None:
            logger.warning("Scenario %s has no feature; cannot ground selectors", scenario_id)
            return

        context = generation.build_context(feature, project.repository_path)
        base_url = _base_url_for(project)

        spec = playwright_gen.generate_spec(
            context,
            story_id=story.id,
            story_title=story.title,
            scenario_id=scenario.id,
            scenario_name=scenario.scenario,
            given=scenario.given or [],
            when=scenario.when or [],
            then=scenario.then or [],
            base_url=base_url,
            credentials=declared_credentials(project),
        )

        directory = spec_directory(project)
        path = directory / spec.file_name
        path.write_text(spec.source, encoding="utf-8")

        existing = db.scalar(
            select(PlaywrightTest).where(PlaywrightTest.gherkin_scenario_id == scenario.id)
        )
        repository = Path(project.repository_path)
        relative = path.relative_to(repository).as_posix()
        # Where Playwright must be invoked from for this spec, recorded now rather than
        # guessed at run time — the same context an imported test carries.
        working_directory = playwright_root(project).relative_to(repository).as_posix()
        if working_directory == ".":
            working_directory = ""

        # The same reasoning as for an imported test: without the right `--project`, a
        # suite needing a live backend can be dragged into a run that never wanted one.
        config = discovery.find_repository_config(repository)
        playwright_project = (
            discovery.project_for(config.read_text(encoding="utf-8"), config.parent, path)
            if config is not None
            else None
        )
        if existing is None:
            existing = PlaywrightTest(
                id=next_reference(db, PlaywrightTest, "pw"),
                project_id=project.id,
                user_story_id=story.id,
                gherkin_scenario_id=scenario.id,
            )
            db.add(existing)
        _discard_superseded_spec(repository, existing.file, relative)
        existing.scenario = scenario.scenario
        existing.file = relative
        existing.working_directory = working_directory
        existing.playwright_project = playwright_project
        existing.source = spec.source
        existing.test_status = "not_run"
        existing.result = {
            "status": "not_run",
            "executed_at": None,
            "duration_ms": 0,
            "console_output": spec.unresolved or None,
        }
        scenario.scenario_status = "automated"
        db.commit()

        if spec.unresolved:
            logger.warning(
                "Spec %s generated with %d unresolved step(s)", spec.file_name, len(spec.unresolved)
            )
    except OllamaError as exc:
        db.rollback()
        logger.warning("Playwright generation failed for %s: %s", scenario_id, exc)
    except Exception:
        db.rollback()
        logger.exception("Playwright generation crashed for %s", scenario_id)
    finally:
        db.close()


def _abandon_run(db: Session, test_id: str) -> None:
    """Close a run whose worker crashed, so it does not stay `running` for ever.

    Called from the exception handler, where the session has just been rolled back — a
    fresh one is used rather than the poisoned one.
    """
    session = SessionLocal()
    try:
        for run in session.scalars(
            select(TestRun).where(TestRun.test_id == test_id, TestRun.run_status == "running")
        ):
            run.run_status = "not_run"
            run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            run.error_message = "L'exécution s'est interrompue sur une erreur du moteur."
        test = session.get(PlaywrightTest, test_id)
        if test and test.test_status == "running":
            test.test_status = "not_run"
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Could not close the abandoned run of %s", test_id)
    finally:
        session.close()


class _LogWriter:
    """Collects Playwright's output and persists it while the run is still going.

    Committing every line would mean one write per line for no benefit — nothing reads
    faster than the UI polls. Committing only at the end would defeat the purpose: the
    log exists so a run can be watched, not so it can be read afterwards. Flushing on a
    short interval gives both.
    """

    FLUSH_SECONDS = 0.4

    def __init__(self, db: Session, run: "TestRun") -> None:
        self._db = db
        self._run = run
        self._lines: list[str] = []
        self._flushed = 0
        self._last = 0.0

    def __call__(self, line: str) -> None:
        self._lines.append(line)
        if time.monotonic() - self._last >= self.FLUSH_SECONDS:
            self.flush()

    def flush(self) -> None:
        if self._flushed == len(self._lines):
            return
        self._run.log = self.text
        self._db.commit()
        self._flushed = len(self._lines)
        self._last = time.monotonic()

    @property
    def text(self) -> str:
        return "\n".join(self._lines)


def queue_run(db: Session, test: PlaywrightTest) -> TestRun:
    """Open a run before the worker starts.

    The row is created here, not in the worker, so the response to "run this test" can
    name the run the caller should watch. Created in the worker, it would not exist yet
    when the client asks for it.
    """
    run = TestRun(
        test_id=test.id,
        project_id=test.project_id,
        scenario=test.scenario,
        file=test.file,
        origin=test.origin,
        run_status="running",
    )
    db.add(run)
    test.test_status = "running"
    test.result = {**(test.result or {}), "status": "running"}
    db.commit()
    db.refresh(run)
    return run


def link_test_to_story(db: Session, test: PlaywrightTest, story_id: str | None) -> None:
    """Attach a test to the requirement it covers, or detach it.

    A test imported from a repository proves a behaviour without tracing to anything, so
    it counts as automation and never as coverage. That is honest but stops short: someone
    who knows the product can say which requirement a given test verifies, and the link is
    that statement. It is deliberately a person's to make — inferring it from a title would
    put a guess where a claim belongs.

    Both the old and the new requirement are recomputed, since moving a test changes what
    each of them can claim.
    """
    previous = test.user_story_id
    test.user_story_id = story_id
    db.commit()

    for affected in {previous, story_id} - {None}:
        _refresh_story_coverage(db, affected)
    db.commit()


def _discard_superseded_spec(repository: Path, previous: str | None, current: str) -> None:
    """Remove the file a regeneration has just replaced under a different name.

    The file name is derived from the scenario title, so renaming a scenario makes the
    engine write a new file and abandon the old one. The abandoned copy keeps running and
    keeps failing — "Ouvrir le formulaire de connexion" stayed red long after the scenario
    it came from had been renamed, and reading the suite gave no way to tell it apart from
    a real regression.

    Only a file this engine wrote is removed, and the marker in its first line is what
    proves it: a file someone wrote by hand, or moved into place, is left alone even if the
    database points at it.
    """
    if not previous or previous == current:
        return
    abandoned = repository / previous
    try:
        if not abandoned.is_file():
            return
        with abandoned.open(encoding="utf-8") as handle:
            if playwright_gen.GENERATED_MARKER not in handle.readline():
                logger.info("Leaving %s alone: it is not this engine's output", previous)
                return
        abandoned.unlink()
        logger.info("Removed %s, superseded by %s", previous, current)
    except OSError:
        logger.warning("Could not remove the superseded spec %s", previous, exc_info=True)


def _detach_stale_generated_tests(db: Session, project_id: str) -> int:
    """Stop a generated test from claiming a requirement that is no longer the one it was
    written for.

    Story ids are handed out in order at each analysis, so a backlog that changes shape
    renumbers it. A spec generated from "US-006-SC-1 — Ouvrir le formulaire de connexion"
    kept that id after the next analysis gave it to "Accéder à la page des conditions
    générales d'utilisation": the file tested one thing and reported against another. The
    coverage of a requirement nobody had verified was being decided by a test belonging to
    a requirement that no longer existed.

    A generated test records the scenario title it was written from, so the mismatch is
    readable: the id is gone, or it now names something else. Either way the link is
    false and is removed. The file is left on disk — it is still a test someone can read
    and rerun — but it claims nothing until it is regenerated or linked by hand.
    """
    stale: list[PlaywrightTest] = []
    tests = db.scalars(
        select(PlaywrightTest).where(
            PlaywrightTest.project_id == project_id,
            PlaywrightTest.origin != "discovered",
            PlaywrightTest.gherkin_scenario_id.is_not(None),
        )
    )
    for test in tests:
        scenario = db.get(GherkinScenario, test.gherkin_scenario_id)
        if scenario is None or scenario.scenario.strip() != test.scenario.strip():
            stale.append(test)

    affected = {test.user_story_id for test in stale if test.user_story_id}
    for test in stale:
        test.user_story_id = None
        test.gherkin_scenario_id = None
    db.commit()

    for story_id in affected:
        _refresh_story_coverage(db, story_id)
    db.commit()
    return len(stale)


def _refresh_story_coverage(db: Session, story_id: str) -> None:
    """Mark a story's criteria covered only when every scenario of it passes.

    One passing test used to mark them all: US-004 read 4/4 on the strength of a single
    scenario about one of its four pages. The numerator lied as much as the denominator
    did, and in the same direction.

    A criterion is still not individually traced — nothing links one to a scenario — so
    what this states is weaker and true: every scenario derived from this story runs
    green. A story with no scenario, or one still to run, covers nothing.
    """
    story = db.get(UserStory, story_id)
    if not story:
        return

    tests = list(db.scalars(select(PlaywrightTest).where(PlaywrightTest.user_story_id == story_id)))
    scenario_ids = {scenario.id for scenario in story.gherkin_scenarios}
    tested = {test.gherkin_scenario_id for test in tests if test.gherkin_scenario_id}

    # Every test attached to the story must pass — a test someone linked by hand counts
    # exactly as much as one generated from a scenario, because the link is the claim that
    # it covers this requirement. And a story that has scenarios is only verified once
    # each of them is actually exercised.
    verified = (
        bool(tests)
        and all(test.test_status == "passed" for test in tests)
        and (not scenario_ids or scenario_ids <= tested)
    )
    for criterion in story.acceptance_criteria:
        criterion.covered = verified


def run_playwright_test(run_id: str) -> None:
    """Execute the test behind one run, streaming its output into it."""
    db = SessionLocal()
    test_id = ""
    try:
        run = db.get(TestRun, run_id)
        if not run:
            return
        test_id = run.test_id
        test = db.get(PlaywrightTest, run.test_id)
        if not test:
            return
        project = db.get(Project, test.project_id)
        if not project:
            return

        writer = _LogWriter(db, run)

        # A generated spec reads PLAYWRIGHT_BASE_URL, so the engine supplies it. A
        # discovered one obeys its own repository's config, and overriding its base URL
        # would aim a working suite at the wrong application.
        base_url = (
            None
            if test.origin == "discovered"
            else _base_url_for(project)
        )
        try:
            outcome = execution.run_spec(
                project.repository_path,
                test.file,
                base_url=base_url,
                working_directory=test.working_directory or "",
                playwright_project=test.playwright_project,
                grep=execution.grep_for(test.selector) if test.selector else None,
                on_output=writer,
            )
        except execution.ExecutionError as exc:
            # The runner never started: that is a failure of the run, not of the test, so
            # the test keeps whatever verdict it already had.
            logger.warning("Execution of %s could not start: %s", test_id, exc)
            writer.flush()
            run.run_status = "not_run"
            run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            run.error_message = str(exc)
            test.test_status = "not_run" if test.test_status == "running" else test.test_status
            test.result = {
                "status": test.test_status,
                "executed_at": None,
                "duration_ms": 0,
                "error_message": str(exc),
                "console_output": None,
            }
            db.commit()
            return

        # Naive UTC, matching the other timestamp columns. Mixing an aware ISO string
        # in `result` with a naive column made the same run show two different times.
        executed_at = datetime.now(timezone.utc).replace(tzinfo=None)

        writer.flush()
        run.run_status = outcome.status
        run.finished_at = executed_at
        run.duration_ms = outcome.duration_ms
        run.error_message = outcome.error_message
        run.screenshot = outcome.screenshot
        run.trace = outcome.trace
        run.log = writer.text
        run.total, run.passed, run.failed, run.skipped = (
            outcome.total,
            outcome.passed,
            outcome.failed,
            outcome.skipped,
        )

        test.test_status = outcome.status
        test.last_run = executed_at
        test.duration_ms = outcome.duration_ms
        test.result = {
            "status": outcome.status,
            "executed_at": executed_at.isoformat(),
            "duration_ms": outcome.duration_ms,
            "error_message": outcome.error_message,
            "screenshot": outcome.screenshot,
            "trace": outcome.trace,
            "console_output": outcome.console_output or None,
        }

        # A passing scenario is covered: reflect it on its acceptance criteria. A
        # discovered test has no story, so it proves nothing about a stated requirement —
        # counting it as coverage would inflate the figure this product exists to keep honest.
        if test.user_story_id:
            _refresh_story_coverage(db, test.user_story_id)
        db.commit()
        logger.info("Test %s finished: %s in %dms", test_id, outcome.status, outcome.duration_ms)
    except Exception:
        db.rollback()
        logger.exception("Execution crashed for %s", test_id)
        _abandon_run(db, test_id)
    finally:
        db.close()


def default_jira_jql(project: Project) -> str:
    if not project.jira_project:
        raise ValueError(
            "Aucune clé de projet Jira n'est configurée. Renseignez-la dans les "
            "paramètres du projet, ou fournissez une requête JQL explicite."
        )
    return f'project = "{project.jira_project}" AND issuetype = Story ORDER BY created DESC'


def import_jira_stories(
    db: Session, project: Project, jql: str, max_results: int
) -> tuple[list[str], list[str]]:
    """Import Jira issues as User Stories. Returns ``(created_ids, updated_ids)``.

    Re-importing is non-destructive: an existing story is refreshed, and criteria are
    added rather than replaced, so local edits are never silently discarded.
    """
    issues = jira.search_issues(jql, max_results=max_results)
    created: list[str] = []
    updated: list[str] = []

    for issue in issues:
        if not issue.key or not issue.summary:
            continue
        story = db.scalar(
            select(UserStory).where(
                UserStory.project_id == project.id, UserStory.jira_key == issue.key
            )
        )
        if story is None:
            story = UserStory(
                id=next_reference(db, UserStory, "US"),
                project_id=project.id,
                jira_key=issue.key,
                origin="jira",
                # An imported story is a fact, not an inference: full confidence.
                confidence=1.0,
                source_files=[],
                story_status="created",
            )
            db.add(story)
            created.append(story.id)
        else:
            updated.append(story.id)

        story.title = issue.summary
        story.description = issue.description
        story.epic = issue.epic or story.epic
        story.feature_name = story.feature_name or "Import Jira"
        db.flush()

        existing = {item.text.strip().lower() for item in story.acceptance_criteria}
        position = len(story.acceptance_criteria)
        for text in issue.acceptance_criteria:
            if text.strip().lower() in existing:
                continue
            position += 1
            db.add(
                AcceptanceCriterion(
                    id=f"{story.id}-AC-{position:02d}",
                    user_story_id=story.id,
                    text=text,
                    covered=False,
                )
            )
            existing.add(text.strip().lower())

    db.commit()
    return created, updated


def regenerate_gherkin_for_story(story_id: str) -> None:
    """Rebuild one story's Gherkin from the current analysis and prompts.

    Scenarios are replaced, not merged: a story whose wording or criteria changed needs a
    coherent set, and keeping stale scenarios alongside fresh ones would leave the backlog
    describing two different behaviours.

    Playwright tests derived from the replaced scenarios are removed with them — including
    their spec files. A test asserting a scenario that no longer exists is worse than no
    test: it still runs, and still reports green.
    """
    db = SessionLocal()
    try:
        story = db.get(UserStory, story_id)
        if not story:
            return
        project = db.get(Project, story.project_id)
        feature = db.get(Feature, story.feature_id) if story.feature_id else None
        if not project or feature is None:
            logger.warning("Story %s has no analysed feature; re-run an analysis first", story_id)
            return

        context = generation.build_context(feature, project.repository_path)
        draft = generation.GeneratedStory(
            title=story.title,
            description=story.description,
            epic=story.epic,
            acceptance_criteria=[item.text for item in story.acceptance_criteria],
        )
        scenarios = generation.generate_scenarios(context, draft)
        if not scenarios:
            logger.warning("No scenario generated for %s; keeping the existing ones", story_id)
            return

        obsolete = list(
            db.scalars(select(PlaywrightTest).where(PlaywrightTest.user_story_id == story.id))
        )
        for test in obsolete:
            spec = Path(project.repository_path) / test.file
            try:
                spec.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove the obsolete spec %s", spec)
            db.delete(test)
        db.execute(delete(GherkinScenario).where(GherkinScenario.user_story_id == story.id))
        db.flush()

        for index, item in enumerate(scenarios, start=1):
            db.add(
                GherkinScenario(
                    id=f"{story.id}-SC-{index}",
                    user_story_id=story.id,
                    project_id=project.id,
                    feature=story.feature_name,
                    scenario=item.scenario,
                    given=item.given,
                    when=item.when,
                    then=item.then,
                    scenario_status="draft",
                )
            )
        db.commit()
        logger.info(
            "Regenerated %d scenarios for %s (%d obsolete tests removed)",
            len(scenarios),
            story_id,
            len(obsolete),
        )
    except OllamaError as exc:
        db.rollback()
        logger.warning("Gherkin regeneration failed for %s: %s", story_id, exc)
    except Exception:
        db.rollback()
        logger.exception("Gherkin regeneration crashed for %s", story_id)
    finally:
        db.close()


def recover_interrupted_analyses(db: Session) -> int:
    """Fail analyses that were still in flight when the engine stopped.

    Analyses run in-process, so a restart — a crash, a deploy, or someone stopping the
    service — kills the job without touching its row. Left alone the analysis stays
    `running` forever, the project stays `analyzing`, and nothing will ever resume it: the
    UI shows a spinner that never ends.

    Called at startup, before the service accepts requests.
    """
    stranded = list(
        db.scalars(select(Analysis).where(Analysis.status.in_(["queued", "running"])))
    )
    for analysis in stranded:
        analysis.status = "failed"
        analysis.error = (
            "Analyse interrompue par un arrêt du moteur. Les résultats déjà produits sont "
            "conservés ; relancez une analyse pour reprendre."
        )
        analysis.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        # New dicts, not in-place edits: mutating the loaded objects and reassigning the
        # same list leaves old and new identical, so SQLAlchemy sees no change and never
        # issues the UPDATE.
        analysis.steps = [
            {**step, "status": "failed", "detail": "Interrompu par un arrêt du moteur"}
            if step.get("status") == "running"
            else dict(step)
            for step in (analysis.steps or [])
        ]

        project = db.get(Project, analysis.project_id)
        if project and project.project_status == "analyzing":
            project.project_status = "ready" if project.last_analysis else "never_analyzed"

    if stranded:
        db.commit()
        logger.warning("Recovered %d analysis(es) interrupted by a restart", len(stranded))
    return len(stranded)


def recover_interrupted_runs(db: Session) -> int:
    """Release tests left `running` by an engine that stopped mid-execution.

    Same failure as an interrupted analysis, one level down: the Playwright subprocess
    dies with the service, and the row keeps saying the run is in flight. The UI would
    then poll a test that nothing is executing, for ever.

    The previous verdict is not restored — it is no longer known to hold — so the test
    goes back to `not_run` and says why.
    """
    message = "Exécution interrompue par un arrêt du moteur. Relancez le test."

    # The history first: a run left `running` would otherwise be watched for ever by a UI
    # polling a subprocess that died with the previous process.
    for run in db.scalars(select(TestRun).where(TestRun.run_status == "running")):
        run.run_status = "not_run"
        run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        run.error_message = message

    stranded = list(db.scalars(select(PlaywrightTest).where(PlaywrightTest.test_status == "running")))
    for test in stranded:
        test.test_status = "not_run"
        test.result = {**(test.result or {}), "status": "not_run", "error_message": message}
    db.commit()
    if stranded:
        logger.warning("Released %d test run(s) interrupted by a restart", len(stranded))
    return len(stranded)
