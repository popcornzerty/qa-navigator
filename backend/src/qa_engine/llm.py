"""The model that writes proposals — local, or behind a remote API.

Every generation in the engine goes through `chat_json`. Which service answers is a
configuration choice, `GENERATION_PROVIDER`:

* `ollama` — a runtime on this machine. Nothing leaves it.
* `openai` — any service speaking the OpenAI chat-completions protocol: Meta's Model API,
  OpenRouter, OpenCode Zen, a self-hosted vLLM. **What the prompt holds is sent to that
  service**: excerpts of the analysed source, the labels and copy of its screens, its
  routes, and the requirements being written. Some offers — "contributor" and "free" tiers
  among them — keep that data to train their models.

The choice is surfaced wherever a person could be surprised by it: in the startup log, and
on the settings screen, which names where the data goes.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from qa_engine.config import settings

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 3
PROVIDERS = ("ollama", "openai")

# A model asked for JSON sometimes answers ```json … ``` anyway.
FENCED = re.compile(r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL)


class LLMError(RuntimeError):
    """A generation request that did not produce a usable answer."""


@dataclass(frozen=True)
class Provider:
    """What the engine is configured to use, as a person needs to know it."""

    name: str  # ollama | openai
    model: str
    endpoint: str
    #: True when prompts leave this machine.
    remote: bool


def provider() -> Provider:
    name = (settings.generation_provider or "ollama").strip().lower()
    if name not in PROVIDERS:
        raise LLMError(
            f"GENERATION_PROVIDER « {settings.generation_provider} » inconnu : "
            f"valeurs possibles {', '.join(PROVIDERS)}."
        )
    if name == "ollama":
        return Provider("ollama", settings.ollama_model, settings.ollama_base_url, remote=False)
    return Provider(
        "openai",
        settings.generation_model,
        settings.generation_base_url.rstrip("/"),
        remote=not _is_local(settings.generation_base_url),
    )


def _is_local(url: str) -> bool:
    """A self-hosted server on this machine keeps the data here too."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def describe() -> str:
    """`model (language)`, as analysis steps report it."""
    try:
        current = provider()
    except LLMError:
        return f"? ({settings.generation_language})"
    return f"{current.model or '?'} ({settings.generation_language})"


def is_available() -> bool:
    """Whether the configured service answers. Sends no prompt."""
    try:
        current = provider()
    except LLMError:
        return False
    if current.name == "ollama":
        from qa_engine import ollama

        return ollama.is_available()
    if not (current.endpoint and current.model and settings.generation_api_key):
        return False
    request = urllib.request.Request(
        f"{current.endpoint}/models", headers=_auth_headers(), method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def chat_json(system: str, prompt: str, schema: dict, *, temperature: float = 0.2) -> dict:
    """One structured generation round-trip, on whichever service is configured."""
    current = provider()
    if current.name == "ollama":
        from qa_engine import ollama

        return ollama.chat_json(system, prompt, schema, temperature=temperature)
    return _openai_chat_json(current, system, prompt, schema, temperature)


def _auth_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.generation_api_key:
        headers["Authorization"] = f"Bearer {settings.generation_api_key}"
    return headers


def _openai_chat_json(
    current: Provider, system: str, prompt: str, schema: dict, temperature: float
) -> dict:
    if not current.endpoint or not current.model:
        raise LLMError(
            "GENERATION_PROVIDER=openai demande GENERATION_BASE_URL et GENERATION_MODEL."
        )

    # The schema is asked for twice: as a structured-output constraint, which the best
    # services enforce, and in the system prompt, for the ones that only honour
    # `json_object`. A service rejecting `json_schema` outright is retried once without it.
    constrained = {
        "type": "json_schema",
        "json_schema": {"name": "reponse", "schema": schema, "strict": False},
    }
    system_with_schema = (
        f"{system}\n\nRéponds uniquement par un objet JSON conforme à ce schéma :\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )
    try:
        return _openai_round_trip(current, system_with_schema, prompt, temperature, constrained)
    except _FormatRejected:
        logger.info("%s refuse json_schema ; nouvel essai en json_object", current.endpoint)
        return _openai_round_trip(
            current, system_with_schema, prompt, temperature, {"type": "json_object"}
        )


class _FormatRejected(LLMError):
    """The service does not support the requested response format."""


def _openai_round_trip(
    current: Provider, system: str, prompt: str, temperature: float, response_format: dict
) -> dict:
    body = {
        "model": current.model,
        "temperature": temperature,
        "response_format": response_format,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        f"{current.endpoint}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers=_auth_headers(),
        method="POST",
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=settings.generation_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        if exc.code == 400 and response_format.get("type") == "json_schema" and (
            "response_format" in detail or "json_schema" in detail
        ):
            raise _FormatRejected(detail) from exc
        if exc.code in (401, 403):
            raise LLMError(
                f"{current.endpoint} refuse la clé (HTTP {exc.code}) : vérifiez GENERATION_API_KEY."
            ) from exc
        raise LLMError(f"{current.endpoint} a répondu HTTP {exc.code} : {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f"{current.endpoint} injoignable : {exc}") from exc
    except ValueError as exc:
        raise LLMError(f"{current.endpoint} a renvoyé une enveloppe illisible : {exc}") from exc

    try:
        content = payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"{current.endpoint} a renvoyé une réponse sans message") from exc

    fenced = FENCED.match(content)
    if fenced:
        content = fenced.group("body")
    try:
        parsed = json.loads(content)
    except ValueError as exc:
        raise LLMError(f"{current.model} a renvoyé du JSON invalide : {content[:400]}") from exc
    if not isinstance(parsed, dict):
        raise LLMError(f"{current.model} a renvoyé un JSON qui n'est pas un objet")

    usage = payload.get("usage") or {}
    logger.info(
        "%s via %s : %s tokens en %.1fs",
        current.model,
        urllib.parse.urlparse(current.endpoint).hostname,
        usage.get("completion_tokens", "?"),
        time.monotonic() - started,
    )
    return parsed
