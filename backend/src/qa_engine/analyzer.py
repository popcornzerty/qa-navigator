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
from itertools import chain
from pathlib import Path

from qa_engine import literals
from qa_engine.repositories import LocalRepositoryProvider, RepositoryFile

# --- Routing -------------------------------------------------------------------------

ROUTE_PATTERNS = [
    # TanStack Router / Start
    re.compile(r"createFileRoute\(\s*(['\"])(?P<value>[^'\"]+)\1"),
    # React Router
    re.compile(r"<Route[^>]*?\bpath\s*=\s*(['\"])(?P<value>[^'\"]*)\1"),
    re.compile(r"\bpath\s*:\s*(['\"])(?P<value>/[^'\"]*)\1"),
]

# An application that navigates by hash has no router to read, yet its addresses are just
# as real: `#mentions-legales` can be opened directly, and a test can go straight to it.
# Only read from a file that actually reads `location.hash`, so that a CSS selector such
# as `querySelector("#total")` is never mistaken for an address.
HASH_ROUTE = re.compile(r"(['\"])(?P<value>#[A-Za-z][\w-]*)\1")
USES_LOCATION_HASH = re.compile(r"\blocation\.hash\b|['\"]hashchange['\"]")

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

# A named client, with one optional wrapper between it and the URL: `fetch(adresse("/x"))`
# is the same call as `fetch("/x")`, and a codebase that centralises URL building would
# otherwise be reported as making no network calls at all.
API_PATTERN = re.compile(
    r"(?P<client>fetch|axios\.(?:get|post|put|patch|delete|request)|axios|"
    r"(?:api|http|client)\.(?:get|post|put|patch|delete))\s*\(\s*"
    r"(?:[A-Za-z_$][\w$.]*\s*\(\s*)?"
    r"(?P<quote>['\"`])(?P<url>[^'\"`]+)(?P=quote)"
)

# A bare helper: `get<Health>("/health")`, `post("/screener/ranking/start")`. The verb on
# its own is far too common to trust, so what identifies the call is its argument — only a
# literal already shaped like an endpoint survives the URL check applied to every match.
# The lookbehind leaves `axios.get(...)` to the pattern above.
BARE_CLIENT_PATTERN = re.compile(
    r"(?<![\w.$])(?P<client>get|post|put|patch|delete|del|request|http)"
    r"\s*(?:<[^<>]*>)?\s*\(\s*"
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
# --- Interactive controls ------------------------------------------------------------

# A clickable element whose label is written literally in the source. The role is what a
# generated test must ask for: `getByRole('link', { name: 'À propos' })` finds nothing when
# the element is a `<button>`, and Playwright waits the full timeout before saying so.
# Only literal labels are read — `<button>{item.label}</button>` says nothing about the
# text a user sees, and guessing it is how a test comes to look for something imaginary.
# JSX attributes can hold a brace expression containing `>`: `onClick={() => f(x)}`.
# Stopping at the first `>` cut the tag in half and lost every control with a handler.
JSX_ATTRIBUTES = r"(?P<attrs>(?:[^>{]|\{(?:[^{}]|\{[^{}]*\})*\})*)"

LABELLED_CONTROL = re.compile(
    r"<(?P<tag>button|a)\b" + JSX_ATTRIBUTES + r">\s*(?P<label>[^<>{}]+?)\s*</(?P=tag)>",
    re.DOTALL,
)
ARIA_LABEL = re.compile(
    r"<(?P<tag>[a-z][\w-]*)\b(?P<attrs>(?:[^>{]|\{(?:[^{}]|\{[^{}]*\})*\})*?\baria-label\s*=\s*[\"']"
    r"(?P<label>[^\"']+)[\"'][^>]*)>"
)
EXPLICIT_ROLE = re.compile(r"\brole\s*=\s*[\"'](?P<value>[^\"']+)[\"']")
HREF_ATTRIBUTE = re.compile(r"\bhref\s*=")

# Tag to the ARIA role Playwright resolves it to. Deliberately short: a role guessed from
# a tag we do not understand would be worse than no answer at all.
IMPLICIT_ROLES = {
    "button": "button",
    "a": "link",
    "nav": "navigation",
    "table": "table",
    "form": "form",
}


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
    kind: str  # route | component | hook | api_call | form | testid | control
    source_path: str
    line_number: int
    metadata: dict = field(default_factory=dict)


def _line_number(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def _role_of(tag: str, attributes: str) -> str | None:
    """The ARIA role of an element, or None when it cannot be told."""
    explicit = EXPLICIT_ROLE.search(attributes)
    if explicit:
        return explicit.group("value").strip()
    if tag == "a":
        # An anchor without href is not a link; Playwright gives it no role.
        return "link" if HREF_ATTRIBUTE.search(attributes) else None
    return IMPLICIT_ROLES.get(tag)


def extract_controls(text: str, relative_path: str) -> list[DiscoveredSymbol]:
    """Clickable elements carrying a literal label, with the role Playwright will see."""
    found: list[DiscoveredSymbol] = []
    for pattern in (LABELLED_CONTROL, ARIA_LABEL):
        for match in pattern.finditer(text):
            label = " ".join(match.group("label").split())
            role = _role_of(match.group("tag"), match.group("attrs") or "")
            if not label or role is None:
                continue
            found.append(
                DiscoveredSymbol(
                    label,
                    "control",
                    relative_path,
                    _line_number(text, match.start()),
                    {"role": role},
                )
            )

    # Labels the markup never spells out, recovered from the array the element iterates.
    # A `<button>{lien.label}</button>` is unreadable on its own and perfectly readable
    # next to the four entries it renders.
    for label, opening_tag, offset in literals.mapped_labels(text):
        tag, _, attributes = opening_tag.partition(" ")
        role = _role_of(tag, attributes)
        if role is None:
            continue
        found.append(
            DiscoveredSymbol(
                " ".join(label.split()),
                "control",
                relative_path,
                _line_number(text, offset),
                {"role": role, "source": "iteration"},
            )
        )
    return found


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

    if USES_LOCATION_HASH.search(text):
        for match in HASH_ROUTE.finditer(text):
            symbols.append(
                DiscoveredSymbol(
                    match.group("value"),
                    "route",
                    relative_path,
                    _line_number(text, match.start()),
                )
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

    for match in chain(API_PATTERN.finditer(text), BARE_CLIENT_PATTERN.finditer(text)):
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

    if file_has_jsx:
        symbols.extend(extract_controls(text, relative_path))

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
