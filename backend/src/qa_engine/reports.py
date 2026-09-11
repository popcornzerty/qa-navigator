"""Reading a test report a project's own tooling produced.

The engine used to know only what it could run itself, which meant Playwright and nothing
else. A project's real suite is wider than that — 1025 pytest tests next to 130 Playwright
ones, in the repository this was built against — and re-running all of it from a web
interface would be slow, fragile, and a duplicate of what the pipeline already does.

JUnit XML is what every runner already emits: pytest, Playwright, Jest, Vitest, Go,
Maven, PHPUnit. Reading it instead of driving each framework is what makes the inventory
work on any project rather than on Playwright projects only. A report arrives from the
pipeline or from a local run; the engine reads the same file either way.

Nothing here interprets a test. A report says a name, a file and a verdict, and that is
all that is recorded — the same restraint discovery applies to a spec file.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

# `classname` is where every runner puts the thing a test lives in, but they disagree on
# what that is: pytest writes a dotted module path (`tests.test_accounts`), Playwright a
# file path (`e2e/portefeuille.spec.ts`), Jest either. Both are turned back into a path.
SPEC_SUFFIX = re.compile(r"\.(?:spec|test)\.[jt]sx?$")


class ReportError(ValueError):
    """The file is not a JUnit report, or not one this can read."""


@dataclass(frozen=True)
class ReportedTest:
    """One test as a report describes it."""

    file: str
    name: str
    status: str
    duration_ms: int
    message: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        """What identifies this test across two reports of the same suite."""
        return (self.file.casefold(), " ".join(self.name.split()).casefold())


@dataclass(frozen=True)
class Report:
    """Everything one report file says."""

    tests: list[ReportedTest]
    duration_ms: int

    @property
    def counts(self) -> dict[str, int]:
        tally = {"passed": 0, "failed": 0, "skipped": 0}
        for test in self.tests:
            tally[test.status] = tally.get(test.status, 0) + 1
        return tally


def parse(xml_text: str) -> Report:
    """Read a JUnit XML report.

    Both shapes are accepted: a `<testsuites>` wrapping several suites, and a bare
    `<testsuite>`. pytest writes the first, some runners the second, and a reader that
    handles only one of them fails on half the ecosystem for no reason.
    """
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise ReportError(f"Ce fichier n'est pas du XML valide : {exc}") from None

    if root.tag not in ("testsuites", "testsuite"):
        raise ReportError(
            f"Racine « {root.tag} » inattendue : un rapport JUnit commence par "
            "<testsuites> ou <testsuite>."
        )

    tests: list[ReportedTest] = []
    for case in root.iter("testcase"):
        reported = _read_case(case)
        if reported is not None:
            tests.append(reported)

    if not tests:
        raise ReportError("Le rapport ne contient aucun test.")

    # `<testsuites>` carries no time of its own in pytest's output; the suites inside do.
    total = _duration_ms(root.get("time")) or sum(
        _duration_ms(suite.get("time")) for suite in root.iter("testsuite")
    )
    return Report(tests=tests, duration_ms=total)


def _read_case(case: ElementTree.Element) -> ReportedTest | None:
    name = (case.get("name") or "").strip()
    if not name:
        return None

    status = "passed"
    message: str | None = None
    # A `<rerun…>` child marks a retry, not an outcome: Playwright records the attempts of
    # a test that eventually passed, and reading them as failures would report a flaky
    # suite as a broken one.
    for tag, verdict in (("failure", "failed"), ("error", "failed"), ("skipped", "skipped")):
        found = case.find(tag)
        if found is not None:
            status = verdict
            message = (found.get("message") or found.text or "").strip() or None
            break

    # The class belongs to the name, not to the path. Dropping it entirely made the five
    # `test_sans_historique`-style pairs of `test_dividends` — same module, two classes —
    # collide into one row and quietly lose half of them.
    holder = _class_of(case)
    return ReportedTest(
        file=_file_of(case),
        name=f"{holder}::{name}" if holder else name,
        status=status,
        duration_ms=_duration_ms(case.get("time")),
        message=message[:2000] if message else None,
    )


def _class_of(case: ElementTree.Element) -> str:
    """The class a test is declared in, when `classname` carries a dotted module path."""
    classname = (case.get("classname") or "").strip().replace("\\", "/")
    if not classname or "/" in classname or SPEC_SUFFIX.search(classname):
        return ""
    segments = classname.split(".")
    holders = []
    while len(segments) > 1 and segments[-1][:1].isupper():
        holders.insert(0, segments.pop())
    return ".".join(holders)


def _file_of(case: ElementTree.Element) -> str:
    """Where the report says the test lives.

    `file` is the honest answer when a runner provides it. Otherwise `classname` is turned
    back into a path: pytest's dotted `tests.test_accounts` becomes `tests/test_accounts`,
    while Playwright's `e2e/portefeuille.spec.ts` is already a path and its dots must be
    left alone.
    """
    explicit = (case.get("file") or "").strip()
    if explicit:
        return explicit.replace("\\", "/")

    # Separators are normalised first. A Windows runner writes `..\e2e-reel\x.setup.ts`,
    # which holds no forward slash, so the "is it a path" test failed and the dotted-module
    # branch shredded it into `../e2e-reel/connexion/setup/ts`.
    classname = (case.get("classname") or "").strip().replace("\\", "/")
    if not classname:
        return ""
    if "/" in classname or SPEC_SUFFIX.search(classname):
        return classname

    # `tests.test_accounts.TestLogin` — the trailing `TestLogin` is a class inside the
    # module, not a directory above it. Reading it as one turned 43 files into 196 and made
    # a grouped inventory useless. Python modules are lower case and classes capitalised,
    # which is convention rather than law, but a wrong guess here costs a row in the wrong
    # group and nothing more.
    segments = classname.split(".")
    while len(segments) > 1 and segments[-1][:1].isupper():
        segments.pop()
    return "/".join(segments)


def _duration_ms(value: str | None) -> int:
    try:
        return max(0, round(float(value or 0) * 1000))
    except (TypeError, ValueError):
        return 0


def kind_of(tests: list[ReportedTest]) -> str:
    """Whether a report describes browser tests or the rest.

    Decided from the files it names rather than asked of whoever uploads it: a person
    reading a CI artefact should not have to classify it, and the file names already say.
    A mixed report is called `e2e` only if that is what most of it is.
    """
    browser = sum(1 for test in tests if SPEC_SUFFIX.search(test.file))
    return "e2e" if browser * 2 > len(tests) else "backend"


def framework_of(tests: list[ReportedTest]) -> str:
    """A label for where the report came from, for the reader's benefit only.

    Nothing branches on this. It exists so a screen listing four hundred tests can say
    which runner produced them.
    """
    if any(SPEC_SUFFIX.search(test.file) for test in tests):
        return "playwright"
    if any(test.file.endswith(".py") or "/test_" in f"/{test.file}" for test in tests):
        return "pytest"
    return "junit"
