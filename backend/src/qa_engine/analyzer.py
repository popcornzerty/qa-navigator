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
# `href="#cgu"` or `href="/panier"` written directly in the markup.
HREF_LITERAL = re.compile(r"""\bhref\s*=\s*["'](?P<value>[^"']+)["']""")

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

# --- Form fields ---------------------------------------------------------------------

# A field a test has to fill. Only the label was ever recorded that a *form exists*, which
# tells a generator nothing it can act on: with no field to fill, it invented a selector
# (`input[name="email"]`) and had no reason to use the credentials offered to it.
#
# The wrapping form of `<label><span>Identifiant</span><input …></label>` is the shape
# React codebases use most, and it is exactly what `getByLabel` resolves.
WRAPPING_LABEL = re.compile(
    r"<label\b[^>]*>\s*(?:<span[^>]*>\s*)?(?P<label>[^<>{}]+?)\s*(?:</span>\s*)?"
    r"(?P<field><(?P<tag>input|textarea|select)\b[^>]*)",
    re.DOTALL,
)
# `<label htmlFor="x">Identifiant</label> … <input id="x">` — the association is by id, so
# only the label is read here; the field it points at is elsewhere in the file.
LABEL_FOR = re.compile(
    r"<label\b[^>]*\bhtmlFor\s*=\s*[\"'][^\"']+[\"'][^>]*>\s*(?P<label>[^<>{}]+?)\s*</label>",
    re.DOTALL,
)
# A field with no label at all still has something a test can aim at.
SELF_LABELLED_FIELD = re.compile(
    r"<(?P<tag>input|textarea|select)\b(?P<attrs>[^>]*?"
    r"\b(?:placeholder|aria-label)\s*=\s*[\"'](?P<label>[^\"']+)[\"'][^>]*)"
)
INPUT_TYPE = re.compile(r"\btype\s*=\s*[\"'](?P<value>[^\"']+)[\"']")

# What Playwright resolves a field to. `password` has no role of its own, which is why a
# test reaches it by label rather than by role.
FIELD_ROLES = {
    "checkbox": "checkbox",
    "radio": "radio",
    "search": "searchbox",
    "number": "spinbutton",
    "range": "slider",
    "select": "combobox",
    "textarea": "textbox",
}


def _field_role(tag: str, attributes: str) -> str:
    explicit = EXPLICIT_ROLE.search(attributes)
    if explicit:
        return explicit.group("value").strip()
    if tag in ("textarea", "select"):
        return FIELD_ROLES[tag]
    kind = INPUT_TYPE.search(attributes)
    return FIELD_ROLES.get(kind.group("value").strip().lower() if kind else "", "textbox")


# --- Visible copy --------------------------------------------------------------------

# Text a user can read. Two forms matter and both are needed: a JSX text node, and a
# string literal in the code — `setErreur("Renseignez votre identifiant…")` never appears
# in markup, yet it is exactly what a test asserts after a failed sign-in.
JSX_TEXT = re.compile(r">(?P<value>[^<>{}]*[A-Za-zÀ-ÿ][^<>{}]*)<")
CODE_STRING = re.compile(r"""(?P<quote>['"])(?P<value>[^'"\n]{6,}?)(?P=quote)""")

# What is not copy: a path, a class list, an identifier, a format string.
NOT_COPY = re.compile(r"^[\s\W\d]*$|^[a-z0-9_-]+(?:[./][a-z0-9_-]+)+$|^[A-Z_]+$|^\$")


def _is_copy(value: str) -> bool:
    """Whether a literal is something a user could read on screen."""
    cleaned = value.strip()
    if len(cleaned) < 3 or NOT_COPY.match(cleaned):
        return False
    # Copy has spaces or is a capitalised word; `flex items-center` is a class list, and
    # its words are lowercase technical tokens.
    if " " in cleaned:
        return any(word[:1].isupper() for word in cleaned.split()) or cleaned.endswith((".", "?", "!"))
    return cleaned[:1].isupper()


def extract_texts(text: str, relative_path: str) -> list[DiscoveredSymbol]:
    """Literal copy the application can display."""
    found: list[DiscoveredSymbol] = []
    seen: set[str] = set()
    for pattern in (JSX_TEXT, CODE_STRING):
        for match in pattern.finditer(text):
            value = " ".join(match.group("value").split())
            if value in seen or not _is_copy(value):
                continue
            seen.add(value)
            found.append(
                DiscoveredSymbol(value, "text", relative_path, _line_number(text, match.start()))
            )
    return found


def extract_fields(text: str, relative_path: str) -> list[DiscoveredSymbol]:
    """Labelled inputs, with the role and the label a test needs to reach them."""
    found: list[DiscoveredSymbol] = []
    seen: set[str] = set()

    for match in WRAPPING_LABEL.finditer(text):
        label = " ".join(match.group("label").split())
        if not label or label in seen:
            continue
        seen.add(label)
        found.append(
            DiscoveredSymbol(
                label,
                "field",
                relative_path,
                _line_number(text, match.start()),
                {"role": _field_role(match.group("tag"), match.group("field"))},
            )
        )

    for match in SELF_LABELLED_FIELD.finditer(text):
        label = " ".join(match.group("label").split())
        if not label or label in seen:
            continue
        seen.add(label)
        found.append(
            DiscoveredSymbol(
                label,
                "field",
                relative_path,
                _line_number(text, match.start()),
                {"role": _field_role(match.group("tag"), match.group("attrs"))},
            )
        )

    for match in LABEL_FOR.finditer(text):
        label = " ".join(match.group("label").split())
        if label and label not in seen:
            seen.add(label)
            found.append(
                DiscoveredSymbol(
                    label, "field", relative_path, _line_number(text, match.start()), {"role": "textbox"}
                )
            )
    return found


# Tag to the ARIA role Playwright resolves it to. Deliberately short: a role guessed from
# a tag we do not understand would be worse than no answer at all.
# A heading is what a test uses to say which screen it is on. Absent from the
# evidence, the model invented one — `getByRole('heading', { name: 'Connexion' })`
# on a login screen that has no heading at all — and the run spent its timeout there.
HEADING = re.compile(r"""<h[1-6]\b[^>]*>\s*(?P<label>[^<>{}]+?)\s*</h[1-6]>""", re.DOTALL)

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


def _href_addresses(text: str) -> list[tuple[str, int]]:
    """Addresses reachable through an `href`, whether written out or rendered from data."""
    found = [
        (match.group("value"), match.start())
        for match in HREF_LITERAL.finditer(text)
    ]
    found.extend(literals.mapped_attribute(text, "href"))
    return [(value, offset) for value, offset in found if value.startswith(("/", "#"))]


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
    for match in HEADING.finditer(text):
        label = " ".join(match.group("label").split())
        if label:
            found.append(
                DiscoveredSymbol(
                    label, "control", relative_path, _line_number(text, match.start()),
                    {"role": "heading"},
                )
            )

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

    # An `href` is the most direct evidence an address exists — no corroboration needed,
    # unlike a bare `#fragment` literal, which may be a CSS selector. Both the literal
    # form and the one rendered from data are read: an application that centralises its
    # addresses in a table would otherwise appear to reach nowhere.
    for value, offset in _href_addresses(text):
        symbols.append(DiscoveredSymbol(value, "route", relative_path, _line_number(text, offset)))

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
        symbols.extend(extract_fields(text, relative_path))
        symbols.extend(extract_texts(text, relative_path))

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
