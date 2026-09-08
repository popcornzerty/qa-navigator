"""Git repository provider tests — offline.

URL vetting is the security boundary here: git's transport layer can execute a command
when handed an `ext::` URL, so anything but plain HTTP(S) must be refused before it ever
reaches a subprocess.
"""

import pytest

from qa_engine.repositories import GitUrlError, repository_slug, validate_git_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://github.com/owner/repo", "https://github.com/owner/repo"),
        ("http://gitlab.example/owner/repo.git", "http://gitlab.example/owner/repo.git"),
        # What a user actually pastes.
        ("github.com/owner/repo", "https://github.com/owner/repo"),
        ("  https://github.com/owner/repo  ", "https://github.com/owner/repo"),
    ],
)
def test_accepted_urls(raw: str, expected: str):
    assert validate_git_url(raw) == expected


@pytest.mark.parametrize(
    "raw,fragment",
    [
        # git transport helpers turn a URL into command execution.
        ("ext::sh -c 'touch /tmp/pwned'", "espace"),
        ("ext::sh", "transport helper"),
        ("file:///etc/passwd", "Schéma"),
        ("git://github.com/owner/repo", "Schéma"),
        ("ssh://git@github.com/owner/repo", "Schéma"),
        ("https://user:secret@github.com/owner/repo", "identifiants"),
        ("--upload-pack=touch", "« - »"),
        ("https://git hub.com/owner/repo", "espace"),
        ("https://-evil-/owner/repo", "hôte"),
        ("", "vide"),
        ("https://github.com", "aucun dépôt"),
    ],
)
def test_refused_urls(raw: str, fragment: str):
    with pytest.raises(GitUrlError) as error:
        validate_git_url(raw)
    assert fragment in str(error.value)


def test_slug_is_stable_and_filesystem_safe():
    slug = repository_slug("https://github.com/popcornzerty/qa-navigator.git")
    assert slug == "github.com-popcornzerty-qa-navigator"
    # The `.git` suffix and the scheme must not change where a repository lands.
    assert slug == repository_slug("github.com/popcornzerty/qa-navigator")


def test_slug_of_different_repositories_differs():
    assert repository_slug("github.com/a/repo") != repository_slug("github.com/b/repo")
