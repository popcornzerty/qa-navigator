from pathlib import Path

from qa_engine.analyzer import extract_repository_metadata, extract_symbols
from qa_engine.features import group_symbols


def test_extracts_route_component_and_api_call(tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "Dashboard.tsx").write_text(
        """export function Dashboard() { return <Route path="/dashboard" />; }
           const result = fetch("/api/projects");
        """,
        encoding="utf-8",
    )

    summary, symbols = extract_repository_metadata(tmp_path)
    assert summary["files_scanned"] == 1
    found = {(item.kind, item.name) for item in symbols}
    assert ("component", "Dashboard") in found
    assert ("route", "/dashboard") in found
    assert ("api_call", "/api/projects") in found


def test_constants_are_not_reported_as_components():
    """Regression: screaming-snake constants used to be detected as React components."""
    source = """
    const ORDER = ["a", "b"];
    const API_MODE = "mock";
    const TONE_MAP = { a: 1 };
    export function RealComponent() { return <div className="x">hello</div>; }
    """
    names = {
        item.name for item in extract_symbols(source, "src/app.tsx") if item.kind == "component"
    }
    assert names == {"RealComponent"}


def test_component_without_jsx_is_not_reported():
    source = """
    export function BuildQuery(input) { return input.trim(); }
    export function Panel() { return <section>{null}</section>; }
    """
    names = {
        item.name for item in extract_symbols(source, "src/panel.tsx") if item.kind == "component"
    }
    assert names == {"Panel"}


def test_collects_test_ids_and_forms():
    source = """
    export function LoginForm() {
      return <form onSubmit={submit}><input data-testid="login-email" /></form>;
    }
    """
    symbols = extract_symbols(source, "src/auth/LoginForm.tsx")
    assert ("testid", "login-email") in {(item.kind, item.name) for item in symbols}
    assert any(item.kind == "form" for item in symbols)


def test_grouping_produces_functional_domains():
    symbols = [
        *extract_symbols(
            'export const CartPage = () => <Route path="/cart" />;', "src/routes/cart.tsx"
        ),
        *extract_symbols("export const CartLine = () => <li>x</li>;", "src/routes/cart.tsx"),
        *extract_symbols(
            'export const LoginPage = () => <Route path="/login" />;', "src/routes/login.tsx"
        ),
        *extract_symbols(
            "export const LoginForm = () => <form><input /></form>;", "src/routes/login.tsx"
        ),
    ]
    features = group_symbols(symbols)
    names = {feature.name for feature in features}
    assert "Panier" in names
    assert "Authentification" in names


def test_a_generated_route_manifest_does_not_absorb_every_route():
    """Regression: one file declaring many routes used to collapse them into one domain."""
    manifest = """
    const routes = [
      { path: "/cart" },
      { path: "/checkout" },
      { path: "/orders" },
    ];
    """
    features = group_symbols(extract_symbols(manifest, "src/routeTree.gen.ts"))
    names = {feature.name for feature in features}
    assert {"Panier", "Commande", "Commandes"} <= names


def test_layout_anchors_are_shared_across_features():
    """Navigation lives in a layout file that belongs to no domain; its anchors must survive."""
    from qa_engine.features import shared_test_ids

    layout = 'export const AppSidebar = () => <nav data-testid="nav-backlog" />;'
    cart = 'export const CartPage = () => <Route path="/cart" data-testid="cart-total" />;'
    symbols = [
        *extract_symbols(layout, "src/components/layout/app-sidebar.tsx"),
        *extract_symbols(cart, "src/routes/cart.tsx"),
    ]

    shared = shared_test_ids(symbols)
    assert shared == ["nav-backlog"]
    # An anchor that belongs to a real domain is not duplicated into the shared set.
    assert "cart-total" not in shared


def test_anchors_declared_as_constants_are_detected():
    """Navigation anchors usually live in a list, leaving the attribute itself dynamic."""
    source = """
    const NAV = [
      { to: "/backlog", label: "Backlog", testId: "nav-backlog" },
      { to: "/coverage", label: "Coverage", testId: "nav-coverage" },
    ];
    export const Sidebar = () => <nav>{NAV.map((i) => <a data-testid={i.testId} />)}</nav>;
    """
    found = {s.name for s in extract_symbols(source, "src/components/layout/nav.tsx") if s.kind == "testid"}
    assert found == {"nav-backlog", "nav-coverage"}


def test_anchors_forwarded_as_a_prop_are_detected():
    """A shared component receives the anchor as a prop, leaving data-testid dynamic."""
    source = """
    export const Dashboard = () => (
      <div>
        <MetricCard testId="metric-coverage" label="Coverage" value="87.9%" />
        <MetricCard testId="metric-tests" label="Tests" value="76" />
      </div>
    );
    """
    found = {s.name for s in extract_symbols(source, "src/routes/index.tsx") if s.kind == "testid"}
    assert found == {"metric-coverage", "metric-tests"}


def test_an_anchor_written_both_ways_is_reported_once():
    source = 'export const Row = () => <li data-testid="cart-line" />;'
    hits = [s for s in extract_symbols(source, "src/cart.tsx") if s.kind == "testid"]
    assert [s.name for s in hits] == ["cart-line"]


def _names(source: str, kind: str) -> set[str]:
    return {item.name for item in extract_symbols(source, "src/App.tsx") if item.kind == kind}


class TestNetworkCalls:
    def test_a_url_builder_between_the_client_and_the_literal(self):
        """`fetch(adresse("/auth/login"))` is the same call as `fetch("/auth/login")`.

        A codebase that centralises URL building was reported as making no network calls
        at all, which read as "this application talks to nothing".
        """
        assert "/auth/login" in _names('await fetch(adresse("/auth/login"), { method: "POST" });', "api_call")

    def test_a_bare_helper_with_a_generic(self):
        source = 'return get<{ quotes: Quote[]; errors: string[] }>("/market/quotes");'
        assert "/market/quotes" in _names(source, "api_call")

    def test_a_bare_helper_needs_a_url_shaped_argument(self):
        """`get` alone is far too common a name to treat as a network client."""
        assert _names('const value = get("firstName");', "api_call") == set()
        assert _names('const item = request("retry");', "api_call") == set()

    def test_a_template_literal_endpoint(self):
        assert "/tests?${params}" in _names("return http<Test[]>(`/tests?${params}`);", "api_call")

    def test_a_dotted_client_is_still_read(self):
        assert "/x" in _names('axios.get("/x");', "api_call")


class TestHashRoutes:
    HASH_APP = """
    const ADRESSES = { "#a-propos": "apropos", "#cgu": "cgu" };
    window.addEventListener("hashchange", () => setPage(window.location.hash));
    """

    def test_an_app_navigating_by_hash_still_has_addresses(self):
        """No router to read, yet `#cgu` opens directly and a test can go straight to it."""
        assert _names(self.HASH_APP, "route") == {"#a-propos", "#cgu"}

    def test_a_css_selector_is_not_an_address(self):
        """Without corroboration, every `querySelector("#id")` would become a route."""
        source = 'const total = document.querySelector("#total");'
        assert _names(source, "route") == set()

    def test_path_routes_are_unaffected(self):
        assert _names('<Route path="/cart" />', "route") == {"/cart"}


class TestHashRoutesDoNotFragmentDomains:
    """Four legal pages addressed by hash are fragments of one screen, not four domains."""

    APP = """
    const ADRESSES = {
      "#a-propos": "apropos",
      "#cgu": "cgu",
      "#mentions-legales": "mentions",
      "#confidentialite": "confidentialite",
    };
    window.addEventListener("hashchange", suivre);
    export function App() { return <main>{window.location.hash}</main>; }
    """

    def _features(self, tmp_path: Path):
        source = tmp_path / "src" / "screens"
        source.mkdir(parents=True)
        (source / "App.tsx").write_text(self.APP, encoding="utf-8")
        (source / "Portfolio.tsx").write_text(
            'export function Portfolio() { return <table />; }\n'
            'const rows = get<Rows>("/portfolio/positions");\n',
            encoding="utf-8",
        )
        _, symbols = extract_repository_metadata(tmp_path)
        return group_symbols(symbols)

    def test_the_anchors_do_not_each_become_a_domain(self, tmp_path: Path):
        names = {feature.name for feature in self._features(tmp_path)}
        assert not any(name.startswith("#") for name in names), names

    def test_the_anchors_are_still_reported_as_routes(self, tmp_path: Path):
        """They remain real addresses a test can open — just not domains of their own."""
        routes = {route for feature in self._features(tmp_path) for route in feature.routes}
        assert "#cgu" in routes and "#mentions-legales" in routes

    def test_a_path_route_still_defines_its_own_domain(self, tmp_path: Path):
        source = tmp_path / "src" / "routes"
        source.mkdir(parents=True)
        (source / "cart.tsx").write_text(
            'export function Cart() { return <Route path="/cart" />; }', encoding="utf-8"
        )
        _, symbols = extract_repository_metadata(tmp_path)
        assert {feature.name for feature in group_symbols(symbols)} == {"Panier"}


class TestControlRoles:
    """A test asks for a role; asking for the wrong one waits out the whole timeout."""

    def _controls(self, source: str) -> dict[str, str]:
        from qa_engine.analyzer import extract_controls

        return {
            item.name: item.metadata["role"]
            for item in extract_controls(source, "src/App.tsx")
        }

    def test_a_button_is_a_button_and_an_anchor_a_link(self):
        source = (
            '<div><button onClick={go}>À propos</button>'
            '<a href="#cgu">CGU</a></div>'
        )
        assert self._controls(source) == {"À propos": "button", "CGU": "link"}

    def test_an_anchor_without_href_has_no_role(self):
        """Playwright gives it none either, so claiming `link` would mislead."""
        assert self._controls("<a onClick={go}>Ouvrir</a>") == {}

    def test_an_explicit_role_wins_over_the_tag(self):
        assert self._controls('<a href="/x" role="button">Valider</a>') == {"Valider": "button"}

    def test_a_computed_label_is_not_recorded(self):
        """`{item.label}` says nothing about the text a user sees; guessing it invents one."""
        assert self._controls("<button>{lien.label}</button>") == {}

    def test_an_aria_label_is_read(self):
        assert self._controls('<button aria-label="Fermer"><Icon /></button>') == {
            "Fermer": "button"
        }

    def test_whitespace_around_a_label_is_normalised(self):
        assert self._controls("<button>\n  Mentions légales\n</button>") == {
            "Mentions légales": "button"
        }
