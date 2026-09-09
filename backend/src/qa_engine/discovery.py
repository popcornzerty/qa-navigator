"""Discovery of tests that already exist in an analysed repository.

A repository usually arrives with a test suite of its own, written by hand or by an
agent. Those tests are the most reliable coverage evidence available: they were written
against the real product, and they run. The engine therefore registers them instead of
pretending the project starts from zero.

Two things are deliberately *not* done here:

* **No interpretation.** A discovered test is recorded with the title its author gave it.
  Nothing infers a User Story from it — a test tells you what is verified, not why the
  behaviour is wanted, and inventing the "why" is exactly the hallucination this engine
  refuses elsewhere.
* **No rewriting.** The file is left untouched. Generated specs carry a header saying
  they may be overwritten; a discovered one never is.

Parsing is textual on purpose. Executing a repository's TypeScript to enumerate its tests
would mean running untrusted code from a cloned repository inside the engine.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from qa_engine.repositories import EXCLUDED_DIRS

logger = logging.getLogger(__name__)

CONFIG_NAMES = (
    "playwright.config.ts",
    "playwright.config.js",
    "playwright.config.mjs",
    "playwright.config.cjs",
)

# `test("…")`, `it("…")` and their modifiers. `test.step` is excluded on purpose: a step
# is a phase *inside* a test, not a test, and the engine's own generated specs are built
# entirely from steps — counting them would multiply every generated test by its steps.
TEST_CALL = re.compile(
    r"\b(?P<kind>test|it)"
    r"(?:\.(?P<modifier>only|skip|fixme|fail|slow))?"
    r"\s*\(\s*(?P<quote>['\"`])(?P<title>(?:\\.|(?!(?P=quote))[^\\])*)(?P=quote)"
)
DESCRIBE_CALL = re.compile(
    r"\b(?:test|describe)(?:\.describe)?"
    r"(?:\.(?:only|skip|fixme|serial|parallel))*"
    r"\s*\(\s*(?P<quote>['\"`])(?P<title>(?:\\.|(?!(?P=quote))[^\\])*)(?P=quote)"
)
DESCRIBE_START = re.compile(r"\b(?:test\.describe|describe)\b")

# Playwright builds a test's full title as `file:line › describe › test`, joined with
# U+203A. Selecting a single test out of a file means matching that string, so the
# separator has to be the one Playwright uses and not an ASCII lookalike.
TITLE_SEPARATOR = " › "

# Playwright config: `name: "bouchonne"` and `testDir: "e2e"` inside a `projects: [...]`.
PROJECT_NAME = re.compile(r"\bname\s*:\s*(['\"`])(?P<value>[^'\"`]+)\1")
PROJECT_TESTDIR = re.compile(r"\btestDir\s*:\s*(['\"`])(?P<value>[^'\"`]+)\1")
# `testMatch: ["**/connexion.setup.ts"]` narrows a project to part of its testDir, so two
# projects can share a directory and still own different files.
PROJECT_TESTMATCH = re.compile(r"\btestMatch\s*:\s*(?P<value>\[[^\]]*\]|['\"`][^'\"`]+['\"`])")
GLOB_LITERAL = re.compile(r"['\"`]([^'\"`]+)['\"`]")

# Comments and strings are stripped before brace counting so that a `{` inside a comment
# does not shift the describe stack.
LINE_COMMENT = re.compile(r"//.*$", re.MULTILINE)
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


@dataclass(frozen=True)
class DiscoveredTest:
    """One `test()` found in an existing spec file."""

    file: str  # repository-relative, POSIX
    title: str  # the test's own title
    suite: str  # enclosing describe titles, joined the way Playwright joins them
    line: int
    skipped: bool  # declared with .skip or .fixme

    @property
    def full_title(self) -> str:
        """The title as Playwright itself prints and matches it."""
        return f"{self.suite}{TITLE_SEPARATOR}{self.title}" if self.suite else self.title


def strip_comments(text: str) -> str:
    """Blank out comments, keeping every character where it was.

    Scanned rather than matched with a regular expression, because `//` is only a comment
    outside a string: `baseURL: "http://localhost:5180"` was being cut at `"http:`, and a
    test whose title mentions a URL lost half its name. A brace hidden past such a false
    comment also shifted the describe nesting.

    Comments become spaces and newlines are kept, so every line and column still holds:
    the line recorded for a test has to point at the test.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    quote: str | None = None  # the string delimiter currently open, if any

    while index < length:
        char = text[index]

        if quote is not None:
            out.append(char)
            if char == "\\" and index + 1 < length:
                # An escaped character cannot close the string, whatever it is.
                out.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue

        if char in "'\"`":
            quote = char
            out.append(char)
            index += 1
            continue

        if text.startswith("//", index):
            while index < length and text[index] != "\n":
                out.append(" ")
                index += 1
            continue

        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = length if end == -1 else end + 2
            out.append("".join("\n" if c == "\n" else " " for c in text[index:end]))
            index = end
            continue

        out.append(char)
        index += 1

    return "".join(out)


def extract_tests(text: str, relative_path: str) -> list[DiscoveredTest]:
    """List the tests declared in one spec file.

    Nesting is tracked by counting braces, so a test keeps the describe titles that
    actually enclose it rather than the nearest one seen above it.
    """
    cleaned = strip_comments(text)
    stack: list[tuple[str, int]] = []  # (describe title, brace depth where it opened)
    depth = 0
    results: list[DiscoveredTest] = []

    for number, line in enumerate(cleaned.splitlines(), start=1):
        # A describe and a test can only be told apart before the brace count moves.
        describe_here = DESCRIBE_START.search(line)
        test_match = TEST_CALL.search(line)

        if describe_here:
            described = DESCRIBE_CALL.search(line)
            if described:
                stack.append((described.group("title"), depth))
        elif test_match:
            results.append(
                DiscoveredTest(
                    file=relative_path,
                    title=test_match.group("title"),
                    suite=TITLE_SEPARATOR.join(title for title, _ in stack),
                    line=number,
                    skipped=test_match.group("modifier") in {"skip", "fixme"},
                )
            )

        depth += line.count("{") - line.count("}")
        while stack and depth <= stack[-1][1]:
            stack.pop()

    return results


def find_config(repository_root: Path, spec_relative: str) -> Path | None:
    """The Playwright config governing a spec: the nearest one at or above it.

    In a monorepo the config sits beside the application it tests (`frontend/`), not at
    the repository root, and Playwright must run from that directory for its `testDir`,
    `webServer` and `baseURL` to mean anything.
    """
    root = repository_root.resolve()
    directory = (root / spec_relative).parent.resolve()
    while True:
        for name in CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        if directory == root or root not in directory.parents:
            return None
        directory = directory.parent


def project_for(config_text: str, config_dir: Path, spec_absolute: Path) -> str | None:
    """The `--project` a spec belongs to, or None when it cannot be told.

    Passing the wrong project is worse than passing none: a suite that needs a live
    backend and a session would be dragged into a run that never required either, and
    report red for a test that was never at fault. So this only answers when exactly one
    project's `testDir` contains the spec.
    """
    cleaned = strip_comments(config_text)
    spec = spec_absolute.resolve()
    owning: list[str] = []

    for block in _project_blocks(cleaned):
        name = PROJECT_NAME.search(block)
        test_dir = PROJECT_TESTDIR.search(block)
        if not name or not test_dir:
            continue
        directory = (config_dir / test_dir.group("value")).resolve()
        if directory not in spec.parents:
            continue
        patterns = _test_match(block)
        if patterns and not _matches_any(spec.relative_to(directory).as_posix(), patterns):
            continue
        owning.append(name.group("value"))

    if len(owning) == 1:
        return owning[0]
    if len(owning) > 1:
        logger.info("Several Playwright projects claim %s: %s", spec, ", ".join(owning))
    return None


def _test_match(block: str) -> list[str]:
    found = PROJECT_TESTMATCH.search(block)
    return GLOB_LITERAL.findall(found.group("value")) if found else []


def _matches_any(relative_path: str, patterns: list[str]) -> bool:
    candidate = PurePosixPath(relative_path)
    for pattern in patterns:
        # `**/` matches zero or more directories, which `full_match` reads as one or more.
        variants = {pattern}
        if pattern.startswith("**/"):
            variants.add(pattern[3:])
        if any(candidate.full_match(variant) for variant in variants):
            return True
    return False


def _project_blocks(config_text: str) -> list[str]:
    """The text of each entry in the config's `projects: [...]` array."""
    start = config_text.find("projects")
    if start == -1:
        return []
    opening = config_text.find("[", start)
    if opening == -1:
        return []

    depth = 0
    blocks: list[str] = []
    current: list[str] = []
    for character in config_text[opening:]:
        if character == "[":
            depth += 1
            if depth == 1:
                continue
        elif character == "]":
            depth -= 1
            if depth == 0:
                break
        if depth == 1 and character == "," and current.count("{") == current.count("}"):
            blocks.append("".join(current))
            current = []
            continue
        current.append(character)
    blocks.append("".join(current))
    return [block for block in blocks if block.strip()]


def relative_to_config(config_dir: Path, spec_absolute: Path) -> str:
    """The spec path as Playwright expects it: relative to the directory it runs from."""
    try:
        return spec_absolute.resolve().relative_to(config_dir.resolve()).as_posix()
    except ValueError:
        return PurePosixPath(spec_absolute.as_posix()).name

def find_repository_config(repository_root: Path) -> Path | None:
    """The Playwright config a generated spec should be written under.

    A generated spec has no config of its own to be found from, so one has to be chosen
    for it — and choosing badly writes the file somewhere it cannot run. In a monorepo the
    installation lives beside the application (`frontend/`), not at the repository root:
    a spec written to the root is executed by an `npx`-downloaded Playwright that cannot
    resolve `@playwright/test`, and the run dies on the import line.

    Preference therefore goes to a config whose directory actually holds an installation,
    then to the shallowest one, so a repository with several picks its primary suite.
    """
    candidates: list[Path] = []
    for current_root, dirs, files in os.walk(repository_root):
        current = Path(current_root)
        dirs[:] = [item for item in dirs if item not in EXCLUDED_DIRS]
        candidates.extend(current / name for name in files if name in CONFIG_NAMES)

    if not candidates:
        return None

    def rank(config: Path) -> tuple[int, int]:
        installed = 0 if (config.parent / "node_modules").is_dir() else 1
        return (installed, len(config.parent.relative_to(repository_root).parts))

    return sorted(candidates, key=rank)[0]


BASE_URL = re.compile(r"""\bbaseURL\s*:\s*(['"`])(?P<value>[^'"`]+)\1""")


def base_url_of(config_text: str) -> str | None:
    """The `baseURL` a repository's config declares, if any.

    A generated spec navigates to absolute URLs, so it has to agree with the application
    the repository's own suite targets — pointing it at a default port would exercise
    nothing, or worse, something else.
    """
    found = BASE_URL.search(strip_comments(config_text))
    return found.group("value") if found else None

def collected_dir_of(config_text: str) -> str | None:
    """A directory the config actually collects tests from.

    Playwright only runs what its `testDir` covers. A spec written outside it is reported
    as "No tests found" however correct the file is, so a generated spec has to land
    somewhere the repository's own config already looks. The top-level `testDir` is
    preferred; failing that, the first one a project declares.
    """
    cleaned = strip_comments(config_text)
    blocks = _project_blocks(cleaned)
    project_span = "".join(blocks)

    for match in PROJECT_TESTDIR.finditer(cleaned):
        # A `testDir` inside the projects array belongs to a project, not to the config.
        if match.group("value") not in project_span or not blocks:
            return match.group("value")

    for block in blocks:
        found = PROJECT_TESTDIR.search(block)
        if found:
            return found.group("value")
    return None

