"""Static source metadata extraction. No AI, no code execution, no network.

The previous version matched any PascalCase identifier and reported constants such as
``ORDER`` or ``API_MODE`` as React components. Detection here is evidence-based: a symbol
is only reported when the surrounding source supports the claim (a component declaration
must actually contain JSX, a route must come from a recognised routing construct).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from qa_engine.repositories import LocalRepositoryProvider, RepositoryFile

# --- Routing -------------------------------------------------------------------------

ROUTE_PATTERNS = [
    # TanStack Router / Start
    re.compile(r"createFileRoute\(\s*(['\"])(?P<value>[^'\"]+)\1"),
    # React Router
    re.compile(r"<Route[^>]*?\bpath\s*=\s*(['\"])(?P<value>[^'\"]*)\1"),
    re.compile(r"\bpath\s*:\s*(['\"])(?P<value>/[^'\"]*)\1"),
]

# --- Components ----------------------------------------------------------------------

# Candidate component declarations. The name is validated separately and the body must
# contain JSX before the symbol is reported.
COMPONENT_DECLARATIONS = [
    re.compile(r"export\s+default\s+function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\("),
    re.compile(r"export\s+function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\("),
    re.compile(r"(?<![\w.])function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\("),
    re.compile(
        r"(?:export\s+)?const\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*"
        r"(?:React\.)?(?:memo|forwardRef)?\s*\(?\s*(?:\([^)]*\)|[\w$]+)\s*(?::[^=>\n]+)?=>"
    ),
    re.compile(
        r"(?:export\s+)?const\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*"
        r"(?:React\.)?(?:memo|forwardRef)\s*\("
    ),
]

JSX_TAG = re.compile(r"<[A-Za-z][\w.:-]*[\s/>]|<>")
HOOK_DECLARATION = re.compile(
    r"(?:export\s+)?(?:function\s+(?P<fname>use[A-Z][\w$]*)\s*\(|"
    r"const\s+(?P<cname>use[A-Z][\w$]*)\s*(?::[^=\n]+)?=)"
)

# --- Network calls -------------------------------------------------------------------

API_PATTERN = re.compile(
    r"(?P<client>fetch|axios\.(?:get|post|put|patch|delete|request)|axios|"
    r"(?:api|http|client)\.(?:get|post|put|patch|delete))\s*\(\s*"
    r"(?P<quote>['\"`])(?P<url>[^'\"`]+)(?P=quote)"
)

# --- QA-relevant anchors -------------------------------------------------------------

# Collected so Playwright generation can later target real selectors instead of guesses.
TESTID_PATTERN = re.compile(r"data-testid\s*=\s*(?:\{\s*)?(['\"])(?P<value>[^'\"]+)\1")
# Anchors are frequently declared away from the element: as an object property spread over
# a list (`{ to: "/backlog", testId: "nav-backlog" }`), or as a prop forwarded by a shared
# component (`<MetricCard testId="metric-coverage" />`). Both leave the rendered
# `data-testid` dynamic, so reading only the attribute misses them. Accepting `:` and `=`
# covers both. This also matches `data-testid=` itself, which simply dedupes.
TESTID_PROPERTY = re.compile(r"\btest[iI][dD]\s*[:=]\s*(['\"])(?P<value>[^'\"]+)\1")
FORM_PATTERN = re.compile(r"<form\b|\bonSubmit\s*=|\buseForm\s*\(")

RESERVED_NAMES = {
    "If",
    "Else",
    "For",
    "While",
    "Switch",
    "Return",
    "Function",
    "Component",
    "Fragment",
    "Suspense",
    "Provider",
    "Consumer",
}


@dataclass(frozen=True)
class DiscoveredSymbol:
    """One piece of evidence found in the source. Never an interpretation."""

    name: str
    kind: str  # route | component | hook | api_call | form | testid
    source_path: str
    line_number: int
    metadata: dict = field(default_factory=dict)


def _line_number(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def _is_component_name(name: str) -> bool:
    """PascalCase with at least one lowercase letter.

    ``Dashboard`` and ``AppShell`` qualify. ``ORDER``, ``API_MODE`` and ``TONE_MAP`` do
    not: screaming-snake constants were the main source of false positives before.
    """
    if not name or not name[0].isupper():
        return False
    if "_" in name:
        return False
    if not any(character.islower() for character in name):
        return False
    return name not in RESERVED_NAMES


DECLARATION_START = re.compile(
    r"(?:export\s+|declare\s+)?(?:function|const|let|var|class|interface|type|enum)\s"
)


def _declaration_body(text: str, start: int, limit: int = 6000) -> str:
    """Source belonging to one declaration, bounded by indentation.

    A fixed-size window leaks into the *next* declaration and reports a plain helper as a
    component only because a JSX component follows it. Brace matching is no better: the
    first brace is usually a destructured parameter (``function Card({ className })``),
    not the body. The declaration ends at the first following line that is indented no
    further than it and starts a new declaration.
    """
    line_start = text.rfind("\n", 0, start) + 1
    indent = start - line_start

    lines = text[start : start + limit].split("\n")
    body = [lines[0]]
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped and (len(line) - len(stripped)) <= indent and DECLARATION_START.match(stripped):
            break
        body.append(line)
    return "\n".join(body)


def _returns_jsx(body: str) -> bool:
    return bool(JSX_TAG.search(body))


def extract_symbols(text: str, relative_path: str) -> list[DiscoveredSymbol]:
    """Extract every supported symbol from one source file."""
    symbols: list[DiscoveredSymbol] = []
    file_has_jsx = bool(JSX_TAG.search(text))

    for pattern in ROUTE_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group("value")
            if not value.startswith("/"):
                continue
            symbols.append(
                DiscoveredSymbol(value, "route", relative_path, _line_number(text, match.start()))
            )

    if file_has_jsx:
        for pattern in COMPONENT_DECLARATIONS:
            for match in pattern.finditer(text):
                name = match.group("name")
                if not _is_component_name(name):
                    continue
                if not _returns_jsx(_declaration_body(text, match.start())):
                    continue
                symbols.append(
                    DiscoveredSymbol(
                        name, "component", relative_path, _line_number(text, match.start())
                    )
                )

    for match in HOOK_DECLARATION.finditer(text):
        name = match.group("fname") or match.group("cname")
        symbols.append(
            DiscoveredSymbol(name, "hook", relative_path, _line_number(text, match.start()))
        )

    for match in API_PATTERN.finditer(text):
        url = match.group("url")
        if not url.startswith(("/", "http", "${")):
            continue
        symbols.append(
            DiscoveredSymbol(
                url,
                "api_call",
                relative_path,
                _line_number(text, match.start()),
                {"client": match.group("client")},
            )
        )

    for pattern in (TESTID_PATTERN, TESTID_PROPERTY):
        for match in pattern.finditer(text):
            symbols.append(
                DiscoveredSymbol(
                    match.group("value"),
                    "testid",
                    relative_path,
                    _line_number(text, match.start()),
                )
            )

    form_match = FORM_PATTERN.search(text)
    if form_match:
        symbols.append(
            DiscoveredSymbol(
                Path(relative_path).stem,
                "form",
                relative_path,
                _line_number(text, form_match.start()),
            )
        )

    # Overlapping patterns can report the same declaration twice.
    unique = {(s.kind, s.name, s.source_path, s.line_number): s for s in symbols}
    return list(unique.values())


def extract_repository_metadata(
    repository_path: str | Path,
) -> tuple[dict, list[DiscoveredSymbol]]:
    """Scan a local repository and return a summary plus every discovered symbol."""
    provider = LocalRepositoryProvider(repository_path)
    files: list[RepositoryFile] = provider.source_files()
    symbols: list[DiscoveredSymbol] = []
    extension_counts = Counter(Path(item.relative_path).suffix.lower() for item in files)

    for item in files:
        try:
            text = item.absolute_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        symbols.extend(extract_symbols(text, item.relative_path))

    ordered = sorted(symbols, key=lambda item: (item.source_path, item.line_number, item.kind))
    summary = {
        "files_scanned": len(files),
        "file_extensions": dict(extension_counts),
        "symbols_detected": dict(Counter(symbol.kind for symbol in ordered)),
    }
    return summary, ordered
