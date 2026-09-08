from pathlib import Path

from qa_engine.repositories import LocalRepositoryProvider


def test_local_provider_honours_gitignore_and_exclusions(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.ts\nignored-dir/\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.ts").write_text("export const app = 1", encoding="utf-8")
    (tmp_path / "ignored.ts").write_text("export const ignored = 1", encoding="utf-8")
    (tmp_path / "ignored-dir").mkdir()
    (tmp_path / "ignored-dir" / "feature.ts").write_text("x", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.ts").write_text("x", encoding="utf-8")
    (tmp_path / "asset.png").write_bytes(b"\x89PNG\x00")

    files = LocalRepositoryProvider(tmp_path).source_files()
    assert [item.relative_path for item in files] == ["src/app.ts"]
