"""Адаптер GigaChat без сети: подменяем HTTP и проверяем формат запроса и разбор ответа."""
import json

import httpx
import pytest

from visa_agent.providers import gigachat as g
from visa_agent.tools import tool_specs


def test_schema_has_no_anyof_null():
    for t in tool_specs():
        s = json.dumps(g.simplify_schema(t["parameters"]))
        assert '"null"' not in s and "anyOf" not in s and '"title"' not in s


def test_chat_roundtrip(monkeypatch):
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "dGVzdA==")
    sent = []

    def fake(method, url, **kw):
        sent.append((url, kw.get("json")))
        if url.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "tok", "expires_at": 9_999_999_999_000})
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": "",
            "function_call": {"name": "get_country_metrics", "arguments": {"country": "IT"}}}}]})

    monkeypatch.setattr(httpx, "request", fake)
    p = g.GigaChatProvider("GigaChat-2-Max", {})
    history = [{"role": "user", "content": "сроки Италия"},
               {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "name": "search_visa_cases", "arguments": {"country": "IT"}}]},
               {"role": "tool", "tool_call_id": "1", "name": "search_visa_cases", "content": "{}"}]
    r = p.chat(history, tool_specs())
    assert r["tool_calls"][0]["name"] == "get_country_metrics" and r["tool_calls"][0]["arguments"] == {"country": "IT"}
    body = sent[-1][1]
    assert body["functions"][0]["name"] == "search_visa_cases"
    assert body["messages"][1]["function_call"]["name"] == "search_visa_cases"
    assert body["messages"][2]["role"] == "function"


def test_http_error_is_readable(monkeypatch):
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "x")
    monkeypatch.setattr(httpx, "request", lambda *a, **k: httpx.Response(401, text="Unauthorized"))
    with pytest.raises(g.ProviderError, match="401"):
        g.GigaChatProvider("GigaChat-2-Max", {}).token()
