"""Choosing which model writes proposals, and saying where its prompts go."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from qa_engine import llm, serializers
from qa_engine.config import settings

SCHEMA = {"type": "object", "properties": {"etapes": {"type": "array"}}, "required": ["etapes"]}


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(settings, "generation_provider", "openai")
    monkeypatch.setattr(settings, "generation_base_url", "https://opencode.ai/zen/v1/")
    monkeypatch.setattr(settings, "generation_model", "muse-spark-1.3-contributor-free")
    monkeypatch.setattr(settings, "generation_api_key", "sk-test-secret")


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _completion(content: str) -> _Response:
    body = {"choices": [{"message": {"content": content}}], "usage": {"completion_tokens": 12}}
    return _Response(json.dumps(body).encode("utf-8"))


def _http_error(code: int, detail: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(detail.encode("utf-8")))


class TestWhichProvider:
    def test_ollama_is_the_default_and_stays_on_this_machine(self, monkeypatch):
        monkeypatch.setattr(settings, "generation_provider", "ollama")
        current = llm.provider()
        assert current.name == "ollama"
        assert current.remote is False

    def test_a_remote_api_is_flagged_as_leaving_the_machine(self, remote):
        current = llm.provider()
        assert current.name == "openai"
        assert current.remote is True
        assert current.endpoint == "https://opencode.ai/zen/v1"

    def test_a_self_hosted_server_on_this_machine_is_not_remote(self, remote, monkeypatch):
        monkeypatch.setattr(settings, "generation_base_url", "http://127.0.0.1:8000/v1")
        assert llm.provider().remote is False

    def test_an_unknown_provider_is_refused_with_the_accepted_values(self, monkeypatch):
        monkeypatch.setattr(settings, "generation_provider", "gpt")
        with pytest.raises(llm.LLMError, match="ollama, openai"):
            llm.provider()


class TestOpenAICompatible:
    def test_a_structured_answer_is_returned(self, remote, monkeypatch):
        sent = {}

        def fake_urlopen(request, timeout):
            sent["url"] = request.full_url
            sent["auth"] = request.get_header("Authorization")
            sent["body"] = json.loads(request.data)
            return _completion('{"etapes": [1, 2]}')

        monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)

        assert llm.chat_json("système", "consigne", SCHEMA) == {"etapes": [1, 2]}
        assert sent["url"] == "https://opencode.ai/zen/v1/chat/completions"
        assert sent["auth"] == "Bearer sk-test-secret"
        assert sent["body"]["model"] == "muse-spark-1.3-contributor-free"
        assert sent["body"]["response_format"]["type"] == "json_schema"

    def test_a_fenced_answer_is_still_read(self, remote, monkeypatch):
        monkeypatch.setattr(
            llm.urllib.request,
            "urlopen",
            lambda request, timeout: _completion('```json\n{"etapes": []}\n```'),
        )
        assert llm.chat_json("s", "p", SCHEMA) == {"etapes": []}

    def test_a_service_without_json_schema_is_retried_with_json_object(self, remote, monkeypatch):
        formats = []

        def fake_urlopen(request, timeout):
            kind = json.loads(request.data)["response_format"]["type"]
            formats.append(kind)
            if kind == "json_schema":
                raise _http_error(400, '{"error": "response_format json_schema unsupported"}')
            return _completion('{"etapes": []}')

        monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
        assert llm.chat_json("s", "p", SCHEMA) == {"etapes": []}
        assert formats == ["json_schema", "json_object"]

    def test_a_refused_key_says_which_setting_to_check(self, remote, monkeypatch):
        def fake_urlopen(request, timeout):
            raise _http_error(401, "unauthorized")

        monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(llm.LLMError, match="GENERATION_API_KEY"):
            llm.chat_json("s", "p", SCHEMA)

    def test_prose_instead_of_json_is_an_error(self, remote, monkeypatch):
        monkeypatch.setattr(
            llm.urllib.request, "urlopen", lambda request, timeout: _completion("Bien sûr !")
        )
        with pytest.raises(llm.LLMError, match="JSON invalide"):
            llm.chat_json("s", "p", SCHEMA)

    def test_a_missing_model_is_named_before_any_request(self, remote, monkeypatch):
        monkeypatch.setattr(settings, "generation_model", "")

        def must_not_call(*a, **k):
            raise AssertionError("no request should be sent")

        monkeypatch.setattr(llm.urllib.request, "urlopen", must_not_call)
        with pytest.raises(llm.LLMError, match="GENERATION_MODEL"):
            llm.chat_json("s", "p", SCHEMA)


class TestWhatTheSettingsScreenShows:
    def test_the_destination_is_shown_and_the_key_never_is(self, remote, monkeypatch):
        monkeypatch.setattr(llm, "is_available", lambda: True)
        shown = serializers.ai_settings()
        assert shown.remote is True
        assert shown.endpoint == "https://opencode.ai/zen/v1"
        assert shown.model == "muse-spark-1.3-contributor-free"
        assert "sk-test-secret" not in shown.model_dump_json()

    def test_an_invalid_configuration_is_explained(self, monkeypatch):
        monkeypatch.setattr(settings, "generation_provider", "gpt")
        shown = serializers.ai_settings()
        assert shown.provider == "invalid"
        assert shown.detail is not None and "ollama, openai" in shown.detail
