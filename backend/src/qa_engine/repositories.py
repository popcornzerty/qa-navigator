"""Repository providers: a local directory, or a public git repository cloned on demand."""
from __future__ import annotations

import mimetypes
import os
import re
import shutil
import subprocess
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

try:
    import pathspec
except ImportError:  # pragma: no cover - dependency is declared, fallback keeps the service usable
    pathspec = None


SOURCE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
# Directories never worth scanning. Beyond JS build output, this covers Python virtual
# environments: in a monorepo the engine's own `.venv` sits inside the repository it
# analyses, and walking it would cost thousands of files for nothing.
EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".next",
    "coverage",
    ".cache",
    "vendor",
    ".venv",
    "venv",
    "env",
    ".tox",
    "__pycache__",
    "site-packages",
    ".output",
    ".wrangler",
    ".tanstack",
}


@dataclass(frozen=True)
class RepositoryFile:
    absolute_path: Path
    relative_path: str


class RepositoryProvider(ABC):
    @abstractmethod
    def source_files(self) -> list[RepositoryFile]:
        """Return source files suitable for static analysis."""


class LocalRepositoryProvider(RepositoryProvider):
    def __init__(self, repository_path: str | Path):
        self.root = Path(repository_path).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError("repository_path must be an existing directory")
        self._ignore_spec = self._load_gitignore()

    def _load_gitignore(self):
        gitignore = self.root / ".gitignore"
        if pathspec is None or not gitignore.is_file():
            return None
        return pathspec.PathSpec.from_lines("gitwildmatch", gitignore.read_text(encoding="utf-8").splitlines())

    def _is_ignored(self, relative: Path) -> bool:
        return bool(self._ignore_spec and self._ignore_spec.match_file(relative.as_posix()))

    @staticmethod
    def _is_binary(path: Path) -> bool:
        if mimetypes.guess_type(path.name)[0] and not mimetypes.guess_type(path.name)[0].startswith("text/"):
            return path.suffix not in SOURCE_EXTENSIONS
        try:
            return b"\0" in path.read_bytes()[:1024]
        except OSError:
            return True

    def source_files(self) -> list[RepositoryFile]:
        results: list[RepositoryFile] = []
        for current_root, dirs, files in os.walk(self.root):
            current = Path(current_root)
            dirs[:] = [
                directory
                for directory in dirs
                if directory not in EXCLUDED_DIRS
                and not self._is_ignored((current / directory).relative_to(self.root))
            ]
            for filename in files:
                absolute = current / filename
                relative = absolute.relative_to(self.root)
                if absolute.suffix.lower() not in SOURCE_EXTENSIONS or self._is_ignored(relative):
                    continue
                if not self._is_binary(absolute):
                    results.append(RepositoryFile(absolute, relative.as_posix()))
        return sorted(results, key=lambda item: item.relative_path)


class GitUrlError(ValueError):
    """Raised for a repository URL the service refuses to clone."""


class GitCloneError(RuntimeError):
    """Raised when git could not produce a usable working copy."""


# Only plain HTTP(S) is accepted. `ext::` and `file://` let a crafted URL run a command
# through git's transport layer, and ssh/git schemes would need credentials we never hold.
ALLOWED_SCHEMES = {"http", "https"}
CLONE_TIMEOUT_SECONDS = 300


SCHEME_PREFIX = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
HOSTNAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$")


def validate_git_url(url: str) -> str:
    """Normalise and vet a public repository URL.

    The scheme is checked **before** any convenience rewriting. Prepending ``https://`` to
    anything lacking ``://`` would smuggle ``ext::sh -c '…'`` past the check — and git's
    transport-helper syntax turns that into command execution.
    """
    candidate = (url or "").strip()
    if not candidate:
        raise GitUrlError("L'URL du dépôt est vide.")
    if candidate.startswith("-"):
        raise GitUrlError("L'URL ne peut pas commencer par « - ».")
    if any(character.isspace() for character in candidate):
        raise GitUrlError("L'URL ne peut pas contenir d'espace.")
    if "::" in candidate:
        raise GitUrlError(
            "Syntaxe « transport helper » (::) refusée : seules les URL http et https "
            "sont acceptées."
        )

    scheme_match = SCHEME_PREFIX.match(candidate)
    if scheme_match:
        scheme = scheme_match.group(1).lower()
        if scheme not in ALLOWED_SCHEMES:
            raise GitUrlError(
                f"Schéma « {scheme} » refusé : seuls http et https sont acceptés."
            )
    else:
        # `github.com/owner/repo` is what users actually paste.
        candidate = f"https://{candidate}"

    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise GitUrlError(
            f"Schéma « {parsed.scheme} » refusé : seuls http et https sont acceptés."
        )
    if "@" in parsed.netloc:
        raise GitUrlError(
            "L'URL contient des identifiants. Seuls les dépôts publics sont supportés."
        )
    if not parsed.hostname or not HOSTNAME.match(parsed.hostname):
        raise GitUrlError("L'URL ne contient pas de nom d'hôte valide.")
    if not parsed.path.strip("/"):
        raise GitUrlError("L'URL ne désigne aucun dépôt.")
    return candidate


def repository_slug(url: str) -> str:
    """Stable directory name for a clone, e.g. ``github.com-popcornzerty-qa-navigator``."""
    parsed = urllib.parse.urlparse(validate_git_url(url))
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    raw = f"{parsed.netloc}-{path}".lower()
    return re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-")[:120]


def _run_git(arguments: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    git = shutil.which("git")
    if not git:
        raise GitCloneError("git introuvable : il doit être installé et présent dans le PATH.")
    try:
        return subprocess.run(
            [git, *arguments],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLONE_TIMEOUT_SECONDS,
            check=False,
            # Never block waiting for credentials on a repository that is not public.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
        )
    except subprocess.TimeoutExpired as exc:
        raise GitCloneError(
            f"L'opération git a dépassé {CLONE_TIMEOUT_SECONDS}s et a été interrompue."
        ) from exc
    except OSError as exc:
        raise GitCloneError(f"Impossible de lancer git : {exc}") from exc


class GitRepositoryProvider(RepositoryProvider):
    """A public git repository, materialised as a shallow local clone.

    The clone is shallow and single-branch: the engine only ever reads the current state
    of one branch, so fetching history would cost time and disk for nothing.
    """

    def __init__(self, url: str, branch: str, workspace: Path):
        self.url = validate_git_url(url)
        self.branch = (branch or "").strip() or "main"
        self.root = Path(workspace) / repository_slug(self.url)

    def sync(self) -> Path:
        """Clone the repository, or refresh an existing clone. Returns the working copy."""
        if (self.root / ".git").is_dir():
            self._refresh()
        else:
            self._clone()
        return self.root

    def _clone(self) -> None:
        self.root.parent.mkdir(parents=True, exist_ok=True)
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        result = _run_git(
            [
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                self.branch,
                "--",  # everything after this is a positional argument, never an option
                self.url,
                str(self.root),
            ]
        )
        if result.returncode != 0:
            raise GitCloneError(_clone_failure_message(result.stderr, self.branch))

    def _refresh(self) -> None:
        fetch = _run_git(["fetch", "--depth", "1", "origin", self.branch], cwd=self.root)
        if fetch.returncode != 0:
            raise GitCloneError(_clone_failure_message(fetch.stderr, self.branch))
        reset = _run_git(["reset", "--hard", f"origin/{self.branch}"], cwd=self.root)
        if reset.returncode != 0:
            raise GitCloneError(reset.stderr.strip()[:400] or "git reset a échoué.")
        _run_git(["clean", "-fd"], cwd=self.root)

    def head_revision(self) -> str | None:
        result = _run_git(["rev-parse", "--short", "HEAD"], cwd=self.root)
        return result.stdout.strip() if result.returncode == 0 else None

    def source_files(self) -> list[RepositoryFile]:
        return LocalRepositoryProvider(self.root).source_files()


def _clone_failure_message(stderr: str, branch: str) -> str:
    detail = (stderr or "").strip()
    lowered = detail.lower()
    if "authentication" in lowered or "could not read username" in lowered:
        return "Dépôt inaccessible : seuls les dépôts publics sont supportés."
    if "not found" in lowered or "repository not found" in lowered:
        return "Dépôt introuvable à cette URL."
    if "remote branch" in lowered and "not found" in lowered:
        return f"La branche « {branch} » n'existe pas sur ce dépôt."
    return detail[:400] or "git clone a échoué."
