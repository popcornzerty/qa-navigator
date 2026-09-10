"""Recovering labels that JSX renders from data rather than writing out.

A control whose label is spelled in the markup is easy to read. A great many are not:

    const LIENS_PIED = [
      { doc: "apropos", label: "À propos" },
      { doc: "cgu", label: "CGU" },
    ];
    ...
    {LIENS_PIED.map((lien) => (
      <button onClick={() => ouvrirPage(lien.doc)}>{lien.label}</button>
    ))}

Read one element at a time, that button has no label at all — `{lien.label}` says
nothing a test could click on. Read together with the array it iterates, it is four
buttons whose labels are known exactly. Those four are the difference between a generated
test that clicks something and one that waits out a timeout looking for a link.

This stays deliberately narrow. Only literal arrays of object literals with literal string
values are read, and only one level of indirection is followed. Anything computed — a
label built by a function, entries pushed at runtime, a value read from an API — is left
alone. The engine's rule everywhere else applies here too: report what the source states,
never what it might amount to.
"""

from __future__ import annotations

import re

# `const VIEWS: {...}[] = [` — the type annotation is skipped, only the name is wanted.
ARRAY_DECLARATION = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::[^=]*?)?=\s*(?=\[)"
)
# `const vues = admin ? [...VIEWS, VUE_ADMIN] : VIEWS;` — an alias over known arrays.
ALIAS_DECLARATION = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*(?::[^=]*?)?=\s*(?P<body>[^;\n]*(?:\n[^;]*?)?);"
)
# `{ id: "marche", label: "Marché" }` — string-valued properties of one entry.
STRING_PROPERTY = re.compile(r"\b(?P<key>[A-Za-z_$][\w$]*)\s*:\s*(?P<quote>['\"])(?P<value>(?:\\.|(?!(?P=quote))[^\\])*)(?P=quote)")

# `LIENS_PIED.map((lien) => (` or `.map(lien =>` — the collection and its element name.
MAP_CALL = re.compile(
    r"\b(?P<source>[A-Za-z_$][\w$.]*)\s*\.\s*map\s*(?P<open>\()\s*"
    r"(?:\(\s*(?P<param_paren>[A-Za-z_$][\w$]*)[^)]*\)|(?P<param_bare>[A-Za-z_$][\w$]*))"
    r"\s*(?::[^=>]*)?=>"
)

IDENTIFIER = re.compile(r"\b[A-Z][A-Z0-9_]*\b|\b[A-Za-z_$][\w$]*\b")


def _matching(text: str, start: int, opening: str, closing: str) -> int:
    """Index just past the bracket matching the one at `start`, or len(text).

    Quotes are tracked so a bracket inside a string never closes a real one.
    """
    depth = 0
    index = start
    quote: str | None = None
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def _entries(block: str) -> list[dict[str, str]]:
    """The object literals of an array body, as plain dictionaries of string properties."""
    found: list[dict[str, str]] = []
    index = 0
    while index < len(block):
        opening = block.find("{", index)
        if opening == -1:
            break
        end = _matching(block, opening, "{", "}")
        entry = {
            match.group("key"): match.group("value")
            for match in STRING_PROPERTY.finditer(block[opening:end])
        }
        if entry:
            found.append(entry)
        index = end
    return found


def literal_arrays(text: str) -> dict[str, list[dict[str, str]]]:
    """Every `const NAME = [ {...}, ... ]` whose entries carry literal string values."""
    arrays: dict[str, list[dict[str, str]]] = {}
    for match in ARRAY_DECLARATION.finditer(text):
        opening = text.index("[", match.end() - 1)
        body = text[opening : _matching(text, opening, "[", "]")]
        entries = _entries(body)
        if entries:
            arrays[match.group("name")] = entries
    return arrays


def resolve(name: str, arrays: dict[str, list[dict[str, str]]], text: str) -> list[dict[str, str]]:
    """The entries behind an identifier, following one level of aliasing.

    `const vues = admin ? [...VIEWS, VUE_ADMIN] : VIEWS` is not an array literal, but every
    entry it can hold comes from arrays that are. Taking the union is deliberate: a test
    should know about a control that appears only for an administrator, and a label that
    turns out never to render costs nothing — it is simply never asked for.
    """
    direct = arrays.get(name)
    if direct is not None:
        return direct

    for match in ALIAS_DECLARATION.finditer(text):
        if match.group("name") != name:
            continue
        collected: list[dict[str, str]] = []
        for token in IDENTIFIER.findall(match.group("body")):
            if token != name and token in arrays:
                collected.extend(arrays[token])
        if collected:
            return collected
    return []


def mapped_labels(text: str) -> list[tuple[str, str, int]]:
    """Labels rendered by iterating a literal array, as ``(label, tag, offset)``.

    The offset is that of the `.map(` call: the control exists as many times as the array
    has entries, and pointing at the single place they are all written is more useful than
    pointing at a line that renders four different things.
    """
    arrays = literal_arrays(text)
    if not arrays:
        return []

    results: list[tuple[str, str, int]] = []
    for call in MAP_CALL.finditer(text):
        parameter = call.group("param_paren") or call.group("param_bare")
        entries = resolve(call.group("source").split(".")[0], arrays, text)
        if not entries or not parameter:
            continue

        # The paren of `.map(`, not the one wrapping its parameter: closing the latter
        # gives an empty body and the element is never seen.
        opening = call.start("open")
        body = text[call.end() : _matching(text, opening, "(", ")")]

        # `<button …>{lien.label}</button>` — the element and the field it renders.
        pattern = re.compile(
            r"<(?P<tag>button|a)\b(?P<attrs>(?:[^>{]|\{(?:[^{}]|\{[^{}]*\})*\})*)>\s*\{\s*"
            + re.escape(parameter)
            + r"\s*\.\s*(?P<field>[A-Za-z_$][\w$]*)\s*\}\s*</(?P=tag)>",
            re.DOTALL,
        )
        for element in pattern.finditer(body):
            field = element.group("field")
            for entry in entries:
                label = entry.get(field)
                if label:
                    results.append((label, element.group("tag") + element.group("attrs"), call.start()))
    return results
