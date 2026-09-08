"""Client for the local Ollama runtime.

Everything stays on this machine: no API key, no remote provider, no telemetry. The
module keeps stdlib-only dependencies so the service still starts when Ollama is absent.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from qa_engine.config import settings

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 2


class OllamaError(RuntimeError):
    """Raised when the local runtime cannot answer a generation request."""


def _endpoint(path: str) -> str:
    return f"{settings.ollama_base_url.rstrip('/')}{path}"


def available_models() -> list[str]:
    """Model names served by the local runtime; empty when it is unreachable."""
    try:
        with urllib.request.urlopen(_endpoint("/api/tags"), timeout=PROBE_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        logger.debug("Ollama unreachable: %s", exc)
        return []
    return [model.get("name", "") for model in payload.get("models", [])]


def is_available() -> bool:
    """True when the runtime answers and serves the configured model."""
    models = available_models()
    if not models:
        return False
    configured = settings.ollama_model
    return any(name == configured or name.startswith(f"{configured}:") for name in models)


def chat_json(
    system: str,
    prompt: str,
    schema: dict,
    *,
    temperature: float = 0.2,
) -> dict:
    """One structured generation round-trip.

    The JSON schema is enforced by the runtime itself, which removes the usual "the model
    wrapped its answer in prose" failure mode. Thinking is disabled: the reasoning trace
    would be spent on tokens we discard.
    """
    body = {
        "model": settings.ollama_model,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": temperature},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        _endpoint("/api/chat"),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=settings.ollama_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise OllamaError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OllamaError(f"Ollama unreachable at {settings.ollama_base_url}: {exc}") from exc
    except ValueError as exc:
        raise OllamaError(f"Ollama returned a malformed envelope: {exc}") from exc

    content = payload.get("message", {}).get("content", "")
    if not content:
        raise OllamaError("Ollama returned an empty message")

    try:
        parsed = json.loads(content)
    except ValueError as exc:
        raise OllamaError(f"Ollama returned invalid JSON: {content[:400]}") from exc

    logger.info(
        "Ollama %s: %d tokens in %.1fs",
        settings.ollama_model,
        payload.get("eval_count", 0),
        time.monotonic() - started,
    )
    return parsed
