from pathlib import Path

from qa_engine import analyzer
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


class TestLabelsRenderedFromData:
    """`<button>{lien.label}</button>` is unreadable alone and exact beside its array."""

    FOOTER = """
    const LIENS_PIED: { doc: string; label: string }[] = [
      { doc: "apropos", label: "À propos" },
      { doc: "cgu", label: "CGU" },
    ];
    export function Footer() {
      return (
        <footer>
          {LIENS_PIED.map((lien) => (
            <button key={lien.doc} onClick={() => ouvrir(lien.doc)}>{lien.label}</button>
          ))}
        </footer>
      );
    }
    """

    def _controls(self, source: str) -> set[tuple[str, str]]:
        from qa_engine.analyzer import extract_controls

        return {(item.metadata["role"], item.name) for item in extract_controls(source, "src/App.tsx")}

    def test_every_entry_becomes_a_control(self):
        assert self._controls(self.FOOTER) == {("button", "À propos"), ("button", "CGU")}

    def test_an_arrow_handler_does_not_cut_the_tag(self):
        """`onClick={() => f(x)}` holds a `>`; stopping there lost the control entirely."""
        source = "<button onClick={() => ouvrir(x)}>Valider</button>"
        assert self._controls(source) == {("button", "Valider")}

    def test_a_template_literal_attribute_does_not_either(self):
        source = "<button title={`Raccourci : ${k}`}>Marché</button>"
        assert self._controls(source) == {("button", "Marché")}

    def test_an_alias_over_a_known_array_is_followed(self):
        source = """
        const VIEWS = [{ id: "a", label: "Marché" }];
        const vues = admin ? [...VIEWS] : VIEWS;
        const El = () => <nav>{vues.map((item) => (<button>{item.label}</button>))}</nav>;
        """
        assert ("button", "Marché") in self._controls(source)

    def test_a_field_the_entries_do_not_carry_yields_nothing(self):
        source = """
        const ITEMS = [{ id: "a" }];
        const El = () => <div>{ITEMS.map((item) => (<button>{item.label}</button>))}</div>;
        """
        assert self._controls(source) == set()

    def test_a_computed_array_is_left_alone(self):
        """Entries built at runtime state no label, and inventing one is the failure mode."""
        source = """
        const ITEMS = rows.map(toEntry);
        const El = () => <div>{ITEMS.map((item) => (<button>{item.label}</button>))}</div>;
        """
        assert self._controls(source) == set()


class TestFormFields:
    """Only "a form exists" was recorded, which a generator cannot act on: with no field
    to fill it invented `input[name="email"]` and ignored the credentials offered to it."""

    def _fields(self, source: str) -> set[tuple[str, str]]:
        from qa_engine.analyzer import extract_fields

        return {(item.metadata["role"], item.name) for item in extract_fields(source, "src/Login.tsx")}

    def test_a_label_wrapping_its_input_is_read(self):
        source = "<label><span>Identifiant</span><input autoComplete='username' /></label>"
        assert self._fields(source) == {("textbox", "Identifiant")}

    def test_a_password_is_reached_by_label_not_by_role(self):
        """`type=password` has no ARIA role of its own."""
        source = '<label><span>Mot de passe</span><input type="password" /></label>'
        assert self._fields(source) == {("textbox", "Mot de passe")}

    def test_a_checkbox_keeps_its_own_role(self):
        source = '<label><span>Se souvenir</span><input type="checkbox" /></label>'
        assert self._fields(source) == {("checkbox", "Se souvenir")}

    def test_a_placeholder_stands_in_when_there_is_no_label(self):
        assert self._fields('<input placeholder="Nom ou ticker" />') == {
            ("textbox", "Nom ou ticker")
        }

    def test_a_select_is_a_combobox(self):
        source = "<label><span>Devise</span><select><option>EUR</option></select></label>"
        assert ("combobox", "Devise") in self._fields(source)

    def test_a_field_with_nothing_to_aim_at_is_not_invented(self):
        assert self._fields('<input type="hidden" value="x" />') == set()


class TestScreensAreSeparateDomains:
    """A directory named for screens holds one per file."""

    def _domains(self, tmp_path: Path, *paths: str) -> set[str]:
        from qa_engine.features import group_symbols

        for relative in paths:
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                'export const Panel = () => <div><button>Agir</button>'
                '<label><span>Champ</span><input /></label></div>;',
                encoding="utf-8",
            )
        _, symbols = extract_repository_metadata(tmp_path)
        return {feature.name for feature in group_symbols(symbols)}

    def test_each_panel_is_its_own_domain(self, tmp_path: Path):
        """Read as a directory, every screen collapsed into one domain and a login
        scenario was offered the portfolio's buttons."""
        names = self._domains(
            tmp_path, "frontend/src/panels/Login.tsx", "frontend/src/panels/Portfolio.tsx"
        )
        assert "Portfolio" in names
        assert "Frontend" not in names

    def test_a_plain_component_directory_is_unaffected(self, tmp_path: Path):
        names = self._domains(tmp_path, "frontend/src/components/Chart.tsx")
        assert names == {"Frontend"}


class TestHeadings:
    """A heading is how a test says which screen it is on."""

    def _controls(self, source: str) -> set[tuple[str, str]]:
        from qa_engine.analyzer import extract_controls

        return {(item.metadata["role"], item.name) for item in extract_controls(source, "a.tsx")}

    def test_a_heading_is_evidence_like_any_other(self):
        """Absent from the evidence, one was invented — `getByRole('heading', { name:
        'Connexion' })` on a login screen that has none — and the run timed out on it."""
        assert self._controls("<h1>Mentions légales</h1>") == {("heading", "Mentions légales")}

    def test_every_level_counts(self):
        assert self._controls("<h3 className='x'>Hébergeur</h3>") == {("heading", "Hébergeur")}

    def test_a_computed_heading_states_nothing(self):
        assert self._controls("<h1>{titre}</h1>") == set()

def test_a_button_labelled_by_an_expression_is_found():
    """`<button type="submit">{occupe ? "Vérification…" : "Se connecter"}</button>`.

    The submit button of every form in the repository was missing from the evidence, so
    the prompt offered no button to press and the model pressed the wrong one. Both
    branches are kept: each is a name the button really carries, at a different moment.
    """
    source = """
      <form onSubmit={soumettre}>
        <button className="login-valider" type="submit" disabled={occupe}>
          {occupe ? <span className="rouet" aria-hidden /> : null}
          {occupe ? "Vérification…" : "Se connecter"}
        </button>
      </form>
    """
    found = {
        (symbol.metadata["role"], symbol.name)
        for symbol in analyzer.extract_controls(source, "Login.tsx")
    }
    assert ("button", "Se connecter") in found
    assert ("button", "Vérification…") in found


def test_a_translation_key_is_not_mistaken_for_a_label():
    """`{t('cart.submit')}` contributes a key nobody can see, not a label."""
    source = '<button type="submit">{t(\'cart.submit\')}</button>'
    names = {symbol.name for symbol in analyzer.extract_controls(source, "Cart.tsx")}
    assert "cart.submit" not in names


def test_a_literal_label_is_still_read_the_plain_way():
    source = "<button onClick={close}>Fermer</button>"
    found = {
        (symbol.metadata["role"], symbol.name)
        for symbol in analyzer.extract_controls(source, "Panel.tsx")
    }
    assert ("button", "Fermer") in found
