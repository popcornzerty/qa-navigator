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
