"""Jira import tests — offline.

Jira itself is never contacted: these cover the parts that decide what lands in the
backlog (ADF flattening, acceptance-criteria extraction, non-destructive re-import) and
the error surface when credentials are missing.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qa_engine import jira, services
from qa_engine.main import app

PREFIX = "/api/v1"


def _repository(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "App.tsx").write_text(
        'export const App = () => <Route path="/" />;', encoding="utf-8"
    )
    return repo


def test_adf_is_flattened_to_text():
    document = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "En tant que client,"}]},
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "premier"}]}
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "second"}]}
                        ],
                    },
                ],
            },
        ],
    }
    assert jira.adf_to_text(document) == "En tant que client,\n- premier\n- second"


def test_criteria_come_from_the_custom_field_first():
    criteria = jira.extract_criteria(
        "Description sans critères.", "- Le panier est vide\n- Le total est à zéro"
    )
    assert criteria == ["Le panier est vide", "Le total est à zéro"]


@pytest.mark.parametrize(
    "heading",
    ["Critères d'acceptation :", "Acceptance Criteria", "conditions d'acceptation:"],
)
def test_criteria_are_read_from_a_headed_section(heading: str):
    description = f"En tant que client…\n\n{heading}\n- Premier critère\n- Second critère"
    assert jira.extract_criteria(description, None) == ["Premier critère", "Second critère"]


def test_numbered_and_ac_prefixed_criteria_are_supported():
    description = "Résumé\n\nAcceptance Criteria\n1. Premier\nAC-02 Second\n* Troisième"
    assert jira.extract_criteria(description, None) == ["Premier", "Second", "Troisième"]


def test_description_without_a_criteria_section_yields_nothing():
    assert jira.extract_criteria("Juste une description.", None) == []


def test_search_requires_configuration(monkeypatch):
    monkeypatch.setattr(jira.settings, "jira_base_url", "", raising=False)
    with pytest.raises(jira.JiraNotConfigured):
        jira.search_issues("project = ATL")


def test_import_creates_then_refreshes_without_duplicating(tmp_path: Path, monkeypatch):
    issues = [
        jira.JiraIssue(
            key="ATL-482",
            summary="Se connecter avec des identifiants valides",
            description="En tant que client, je veux me connecter.",
            epic="Authentification",
            acceptance_criteria=["Le formulaire est affiché", "L'email est obligatoire"],
        )
    ]
    monkeypatch.setattr(services.jira, "search_issues", lambda *a, **k: list(issues))

    with TestClient(app) as client:
        created = client.post(
            f"{PREFIX}/projects",
            json={
                "name": "Jira",
                "repository": str(_repository(tmp_path, "jira")),
                "repositorySource": "local",
                "jiraProject": "ATL",
            },
        )
        project_id = created.json()["id"]

        first = client.post(f"{PREFIX}/projects/{project_id}/jira-import", json={})
        assert first.status_code == 200
        assert first.json()["imported"] == 1
        assert first.json()["updated"] == 0
        assert 'project = "ATL"' in first.json()["jql"]

        story_id = first.json()["storyIds"][0]
        story = client.get(f"{PREFIX}/stories/{story_id}").json()
        assert story["jiraKey"] == "ATL-482"
        assert story["status"] == "created"
        assert story["confidence"] == 1.0
        assert len(story["acceptanceCriteria"]) == 2

        # Re-importing the same issue refreshes it instead of creating a duplicate.
        issues[0].summary = "Se connecter (titre mis à jour)"
        second = client.post(f"{PREFIX}/projects/{project_id}/jira-import", json={})
        assert second.json() == {
            **second.json(),
            "imported": 0,
            "updated": 1,
        }

        refreshed = client.get(f"{PREFIX}/stories/{story_id}").json()
        assert refreshed["title"] == "Se connecter (titre mis à jour)"
        assert len(refreshed["acceptanceCriteria"]) == 2  # not duplicated

        assert len(client.get(f"{PREFIX}/stories?project_id={project_id}").json()) == 1


def test_import_without_a_project_key_is_refused(tmp_path: Path):
    with TestClient(app) as client:
        created = client.post(
            f"{PREFIX}/projects",
            json={
                "name": "Sans clé",
                "repository": str(_repository(tmp_path, "nokey")),
                "repositorySource": "local",
            },
        )
        project_id = created.json()["id"]
        response = client.post(f"{PREFIX}/projects/{project_id}/jira-import", json={})
        assert response.status_code == 409
        assert "Jira" in response.json()["detail"]


def test_unconfigured_jira_reports_503(tmp_path: Path, monkeypatch):
    def unconfigured(*_args, **_kwargs):
        raise jira.JiraNotConfigured("Jira n'est pas configuré.")

    monkeypatch.setattr(services.jira, "search_issues", unconfigured)

    with TestClient(app) as client:
        created = client.post(
            f"{PREFIX}/projects",
            json={
                "name": "Non configuré",
                "repository": str(_repository(tmp_path, "unconfigured")),
                "repositorySource": "local",
                "jiraProject": "ATL",
            },
        )
        project_id = created.json()["id"]
        response = client.post(f"{PREFIX}/projects/{project_id}/jira-import", json={})
        assert response.status_code == 503
