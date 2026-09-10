"""Groups raw symbols into functional features.

The analyzer answers "what is in the code". This module answers "what can a QA engineer
test", which is a much smaller list: a repository with 300 components typically exposes
under a dozen functional domains. Grouping is deterministic and explainable — no AI is
involved here, so a feature can always be traced back to the evidence that produced it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from qa_engine.analyzer import DiscoveredSymbol

# Directories that hold infrastructure rather than business behaviour. They never become
# a feature of their own, but their symbols can still be attached to a real feature.
INFRASTRUCTURE_SEGMENTS = {
    "ui",
    "lib",
    "libs",
    "utils",
    "util",
    "helpers",
    "hooks",
    "styles",
    "style",
    "types",
    "config",
    "constants",
    "assets",
    "public",
    "layout",
    "test",
    "tests",
    "__tests__",
    "spec",
    "mocks",
    "mock",
    "fixtures",
    "node_modules",
}

# Path segments that carry no domain meaning on their own.
NEUTRAL_SEGMENTS = {"src", "app", "pages", "routes", "components", "features", "modules", "views"}

# Directories whose name says they hold one screen per file. `panels/Login.tsx` and
# `panels/Portfolio.tsx` are two areas of a product, not two files of one.
SCREEN_SEGMENTS = {"panels", "screens", "views", "pages", "sections"}

ROUTE_PARAMETER = re.compile(r"^[$:\[{_-]|^\.\.\.")

FRENCH_DOMAIN_LABELS = {
    "home": "Accueil",
    "index": "Accueil",
    "root": "Accueil",
    "auth": "Authentification",
    "login": "Authentification",
    "signin": "Authentification",
    "signup": "Inscription",
    "account": "Compte utilisateur",
    "profile": "Profil utilisateur",
    "settings": "Paramètres",
    "admin": "Administration",
    "dashboard": "Tableau de bord",
    "cart": "Panier",
    "checkout": "Commande",
    "orders": "Commandes",
    "order": "Commandes",
    "products": "Catalogue produits",
    "product": "Catalogue produits",
    "catalog": "Catalogue produits",
    "search": "Recherche",
    "payment": "Paiement",
    "payments": "Paiement",
    "billing": "Facturation",
    "users": "Gestion des utilisateurs",
    "projects": "Projets",
    "project": "Projets",
}

MIN_SYMBOLS_FOR_FEATURE = 2


@dataclass
class DiscoveredFeature:
    """A functional area of the application, backed by traceable evidence."""

    key: str
    name: str
    description: str
    confidence: float
    source_files: list[str]
    symbols: list[DiscoveredSymbol] = field(default_factory=list)

    @property
    def routes(self) -> list[str]:
        return sorted({s.name for s in self.symbols if s.kind == "route"})

    @property
    def components(self) -> list[str]:
        return sorted({s.name for s in self.symbols if s.kind == "component"})

    @property
    def api_calls(self) -> list[str]:
        return sorted({s.name for s in self.symbols if s.kind == "api_call"})

    @property
    def controls(self) -> list[dict]:
        """Labelled controls with the role Playwright resolves them to.

        A generated test asks for a role, and asking for the wrong one finds nothing —
        the locator then waits out the full timeout before saying so. Only literal labels
        appear here: a label computed at runtime is not evidence of anything.
        """
        return self._interactive("control")

    @property
    def fields(self) -> list[dict]:
        """Labelled inputs a test has to fill, with the label `getByLabel` resolves."""
        return self._interactive("field")

    def _interactive(self, kind: str) -> list[dict]:
        # The file is carried through: it is the closest thing to a screen this analysis
        # has, and a generator handed one flat list picks a portfolio button to open a
        # login form. Grouping them by where they are declared lets it stay on one screen.
        seen: dict[tuple[str, str, str], None] = {}
        for symbol in self.symbols:
            if symbol.kind == kind and symbol.metadata.get("role"):
                seen.setdefault((symbol.source_path, symbol.metadata["role"], symbol.name), None)
        return [
            {"file": path, "role": role, "name": name} for path, role, name in sorted(seen)
        ]

    @property
    def test_ids(self) -> list[str]:
        return sorted({s.name for s in self.symbols if s.kind == "testid"})

    @property
    def has_form(self) -> bool:
        return any(s.kind == "form" for s in self.symbols)


def defines_a_domain(route: str) -> bool:
    """Whether a route is a domain of its own, or a fragment of the page declaring it.

    A path route earns its own domain: distinct URLs served by a router usually mean
    distinct areas of the product. A hash route does not. It addresses a fragment of a
    single page — the four legal pages of one application all live in its entry file —
    and treating each as a functional domain shatters the product into a domain per
    anchor. Their file decides instead, like every other symbol.
    """
    return not route.startswith("#")


def _route_domain(route: str) -> str:
    """First meaningful segment of a route path. ``/`` maps to ``home``."""
    parts = [part for part in route.strip("/").split("/") if part]
    for part in parts:
        if ROUTE_PARAMETER.match(part):
            continue
        cleaned = part.strip("-_")
        if cleaned and cleaned not in NEUTRAL_SEGMENTS:
            return cleaned.lower()
    return "home"


def _path_domain(source_path: str) -> str | None:
    """Domain inferred from a file path, ignoring neutral and infrastructure folders."""
    parts = list(PurePosixPath(source_path).parts)
    directories, filename = parts[:-1], parts[-1]

    # A directory named for screens holds one per file, so the file is the domain. Read as
    # a directory instead, every screen of the application collapses into a single domain
    # and a scenario about signing in is offered the portfolio's buttons.
    if any(part.lower() in SCREEN_SEGMENTS for part in directories):
        stem = PurePosixPath(filename).stem.lower().split(".")[0].strip("_-")
        if stem and stem not in NEUTRAL_SEGMENTS and stem not in INFRASTRUCTURE_SEGMENTS:
            return stem

    for part in directories:
        lowered = part.lower()
        if lowered in NEUTRAL_SEGMENTS:
            continue
        if lowered in INFRASTRUCTURE_SEGMENTS:
            return None
        return lowered

    stem = PurePosixPath(filename).stem.lower()
    # Flat file-based routing: `projects.$projectId.analysis.tsx` -> `projects`
    head = stem.split(".")[0].strip("_-")
    if head and head not in NEUTRAL_SEGMENTS and head not in INFRASTRUCTURE_SEGMENTS:
        return head
    return None


def _humanise(domain: str) -> str:
    if domain in FRENCH_DOMAIN_LABELS:
        return FRENCH_DOMAIN_LABELS[domain]
    words = re.split(r"[-_\s]+", domain)
    return " ".join(word.capitalize() for word in words if word) or domain


def _confidence(feature: DiscoveredFeature) -> float:
    """Evidence-weighted score. A feature backed by a route and an API call scores high."""
    score = 0.40
    if feature.routes:
        score += 0.30
    if feature.api_calls:
        score += 0.10
    if len(feature.components) >= 3:
        score += 0.10
    if feature.has_form or feature.test_ids:
        score += 0.08
    return round(min(score, 0.98), 2)


def _describe(feature: DiscoveredFeature) -> str:
    fragments: list[str] = []
    if feature.routes:
        shown = ", ".join(feature.routes[:3])
        suffix = "…" if len(feature.routes) > 3 else ""
        fragments.append(f"{len(feature.routes)} route(s) ({shown}{suffix})")
    if feature.components:
        fragments.append(f"{len(feature.components)} composant(s)")
    if feature.api_calls:
        fragments.append(f"{len(feature.api_calls)} appel(s) API")
    if feature.has_form:
        fragments.append("formulaire détecté")
    if not fragments:
        fragments.append("aucune preuve structurante")
    return f"Domaine fonctionnel détecté : {', '.join(fragments)}."


def group_symbols(symbols: list[DiscoveredSymbol]) -> list[DiscoveredFeature]:
    """Group symbols into functional features.

    Files declaring a route define their domain; every other file falls back to its
    directory. Files that belong to no identifiable domain are dropped rather than
    invented into a feature.
    """
    # A route always defines its own domain. Generated route manifests declare many
    # unrelated paths in one file, so the file cannot dictate a single domain.
    file_domains: dict[str, str] = {}
    for symbol in symbols:
        if symbol.kind == "route" and defines_a_domain(symbol.name):
            file_domains.setdefault(symbol.source_path, _route_domain(symbol.name))

    # Grouped by display label so that `home` and `index` do not produce two "Accueil".
    grouped: dict[str, list[DiscoveredSymbol]] = defaultdict(list)
    keys: dict[str, str] = {}
    for symbol in symbols:
        if symbol.kind == "route" and defines_a_domain(symbol.name):
            domain = _route_domain(symbol.name)
        else:
            domain = file_domains.get(symbol.source_path) or _path_domain(symbol.source_path)
        if not domain:
            continue
        label = _humanise(domain)
        keys.setdefault(label, domain)
        grouped[label].append(symbol)

    features: list[DiscoveredFeature] = []
    for label, domain_symbols in grouped.items():
        domain = keys[label]
        feature = DiscoveredFeature(
            key=domain,
            name=label,
            description="",
            confidence=0.0,
            source_files=sorted({symbol.source_path for symbol in domain_symbols}),
            symbols=domain_symbols,
        )
        # A route is a functional entry point on its own; anything else needs more
        # than a single isolated symbol to be worth showing to a QA engineer.
        if not feature.routes and len(domain_symbols) < MIN_SYMBOLS_FOR_FEATURE:
            continue
        feature.confidence = _confidence(feature)
        feature.description = _describe(feature)
        features.append(feature)

    return sorted(features, key=lambda item: (-item.confidence, item.name))


def shared_test_ids(symbols: list[DiscoveredSymbol]) -> list[str]:
    """Test anchors that belong to no single domain, and are therefore available everywhere.

    Navigation, the page header and the project switcher live in shared layout files, which
    grouping deliberately drops — they are not a functional domain of their own. Their
    anchors are still the ones a test needs to reach a screen, so they are offered to every
    feature instead of being lost.
    """
    file_domains: dict[str, str] = {}
    for symbol in symbols:
        if symbol.kind == "route" and defines_a_domain(symbol.name):
            file_domains.setdefault(symbol.source_path, _route_domain(symbol.name))

    shared: set[str] = set()
    for symbol in symbols:
        if symbol.kind != "testid":
            continue
        domain = file_domains.get(symbol.source_path) or _path_domain(symbol.source_path)
        if domain is None:
            shared.add(symbol.name)
    return sorted(shared)
