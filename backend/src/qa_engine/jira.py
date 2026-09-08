"""Jira Cloud client — read-only.

Credentials never pass through the frontend or the API payload: the service reads them
from its own environment (`JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`) and they are
never echoed back in a response or a log line.

Only issue *reading* is implemented. Pushing stories back to Jira writes to a system
outside this project and is deliberately left out until it is explicitly asked for.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from qa_engine.config import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
MAX_RESULTS = 100

# Atlassian replaced `/rest/api/3/search` with `/rest/api/3/search/jql`; older Jira
# deployments still only serve the former, so both are attempted in order.
SEARCH_PATHS = ("/rest/api/3/search/jql", "/rest/api/3/search")

FIELDS = ["summary", "description", "issuetype", "parent", "status", "labels"]

CRITERIA_HEADING = re.compile(
    r"^\s*(?:crit[eè]res?\s+d['’]acceptation|acceptance\s+criteria|"
    r"conditions?\s+d['’]acceptation)\s*:?\s*$",
    re.IGNORECASE,
)
BULLET = re.compile(r"^\s*(?:[-*•–]|\d+[.)]|AC-?\d+\s*[:.\-]?)\s*(?P<text>.+?)\s*$")


class JiraError(RuntimeError):
    """Raised when Jira cannot be reached or refuses the request."""


class JiraNotConfigured(JiraError):
    """Raised when the service has no Jira credentials."""


@dataclass
class JiraIssue:
    key: str
    summary: str
    description: str
    epic: str = ""
    status: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)


def is_configured() -> bool:
    return bool(settings.jira_base_url and settings.jira_email and settings.jira_api_token)


def _authorization() -> str:
    raw = f"{settings.jira_email}:{settings.jira_api_token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def adf_to_text(node) -> str:
    """Flatten Atlassian Document Format into plain text.

    Jira returns rich documents; the backlog stores plain text. Paragraphs and list items
    become lines so that bullet lists survive as parseable acceptance criteria.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(part for part in (adf_to_text(item) for item in node) if part)

    node_type = node.get("type")
    if node_type == "text":
        return node.get("text", "")
    if node_type == "hardBreak":
        return "\n"

    inner = adf_to_text(node.get("content"))
    if node_type in {"paragraph", "heading", "listItem", "blockquote", "codeBlock"}:
        return inner
    if node_type in {"bulletList", "orderedList"}:
        items = node.get("content") or []
        return "\n".join(f"- {adf_to_text(item)}".rstrip() for item in items)
    return inner


def extract_criteria(description: str, custom_field_text: str | None) -> list[str]:
    """Acceptance criteria from a dedicated field, or from the description's own section.

    Jira has no standard acceptance-criteria field, so this looks where teams actually put
    them: a configured custom field first, then a headed bullet list in the description.
    """
    source = (custom_field_text or "").strip()
    if source:
        return _bullets(source) or [line.strip() for line in source.splitlines() if line.strip()]

    lines = description.splitlines()
    for index, line in enumerate(lines):
        if CRITERIA_HEADING.match(line):
            return _bullets("\n".join(lines[index + 1 :]))
    return []


def _bullets(text: str) -> list[str]:
    criteria: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if criteria:
                break  # a blank line ends the list once it has started
            continue
        match = BULLET.match(line)
        if not match:
            if criteria:
                break
            continue
        value = match.group("text").strip()
        if value:
            criteria.append(value)
    return criteria


def _request(path: str, payload: dict | None = None) -> dict:
    if not is_configured():
        raise JiraNotConfigured(
            "Jira n'est pas configuré. Renseignez JIRA_BASE_URL, JIRA_EMAIL et "
            "JIRA_API_TOKEN dans le .env du moteur, puis redémarrez-le."
        )

    url = f"{settings.jira_base_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": _authorization(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        if exc.code in (401, 403):
            raise JiraError(
                "Jira a refusé les identifiants (401/403). Vérifiez l'email et le jeton API."
            ) from exc
        if exc.code == 404:
            raise JiraError(f"Ressource Jira introuvable : {path}") from exc
        raise JiraError(f"Jira a répondu {exc.code} : {body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise JiraError(f"Jira injoignable à {settings.jira_base_url} : {exc}") from exc
    except ValueError as exc:
        raise JiraError(f"Réponse Jira illisible : {exc}") from exc


def search_issues(jql: str, max_results: int = 50) -> list[JiraIssue]:
    """Run a JQL search and map the issues onto the backlog shape."""
    limit = max(1, min(max_results, MAX_RESULTS))
    fields = list(FIELDS)
    if settings.jira_acceptance_criteria_field:
        fields.append(settings.jira_acceptance_criteria_field)

    payload = {"jql": jql, "maxResults": limit, "fields": fields}
    last_error: JiraError | None = None
    data: dict | None = None
    for path in SEARCH_PATHS:
        try:
            data = _request(path, payload)
            break
        except JiraNotConfigured:
            raise
        except JiraError as exc:
            last_error = exc
    if data is None:
        raise last_error or JiraError("Aucun point d'entrée de recherche Jira disponible.")

    return [_map_issue(issue) for issue in data.get("issues", [])]


def _map_issue(issue: dict) -> JiraIssue:
    fields_data = issue.get("fields") or {}
    description = adf_to_text(fields_data.get("description")).strip()

    custom_field_text = None
    if settings.jira_acceptance_criteria_field:
        raw = fields_data.get(settings.jira_acceptance_criteria_field)
        custom_field_text = adf_to_text(raw).strip() if raw else None

    parent = fields_data.get("parent") or {}
    status = (fields_data.get("status") or {}).get("name", "")

    return JiraIssue(
        key=issue.get("key", ""),
        summary=(fields_data.get("summary") or "").strip(),
        description=description,
        epic=((parent.get("fields") or {}).get("summary") or "").strip(),
        status=status,
        acceptance_criteria=extract_criteria(description, custom_field_text),
    )
