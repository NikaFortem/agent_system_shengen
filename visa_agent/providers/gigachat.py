"""GigaChat API: functions / function_call, arguments — объект, результат — роль function.

Документация: https://developers.sber.ru/docs/ru/gigachat/guides/functions-overview
Ключ авторизации (Authorization key из личного кабинета Studio) — в .env: GIGACHAT_AUTH_KEY.
Проверка подключения: python scripts/check_gigachat.py
"""
import copy
import json
import os
import time
import uuid

import httpx


class ProviderError(RuntimeError):
    pass


def simplify_schema(s):
    """GigaChat понимает не весь JSON Schema: убираем anyOf с null, title и default=None."""
    s = copy.deepcopy(s)
    if isinstance(s, dict):
        if "anyOf" in s:
            non_null = [x for x in s["anyOf"] if x.get("type") != "null"]
            if len(non_null) == 1:
                base = non_null[0]
                s = {**{k: v for k, v in s.items() if k != "anyOf"}, **base}
        s.pop("title", None)
        if s.get("default", 0) is None:
            s.pop("default")
        if "enum" in s and "type" not in s:
            s["type"] = "string"
        return {k: simplify_schema(v) for k, v in s.items()}
    if isinstance(s, list):
        return [simplify_schema(x) for x in s]
    return s


class GigaChatProvider:
    def __init__(self, model: str, cfg: dict):
        self.model = model
        self.scope = cfg.get("scope", "GIGACHAT_API_PERS")
        self.verify = cfg.get("verify_ssl", False)
        self.oauth_url = cfg.get("oauth_url", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth")
        self.api_url = cfg.get("api_url", "https://gigachat.devices.sberbank.ru/api/v1").rstrip("/")
        self.auth_key = os.environ.get("GIGACHAT_AUTH_KEY", "").strip()
        if not self.auth_key:
            raise ProviderError("Нет GIGACHAT_AUTH_KEY в .env (скопируйте .env.example в .env и вставьте ключ)")
        if not self.auth_key.isascii() or " " in self.auth_key:
            raise ProviderError("В GIGACHAT_AUTH_KEY лишние символы (пробел, кириллица или комментарий). "
                                "В .env в этой строке должен быть только ключ")
        self._token, self._exp = None, 0

    def _req(self, method, url, **kw):
        try:
            r = httpx.request(method, url, verify=self.verify, timeout=60, **kw)
        except httpx.ConnectError as e:
            raise ProviderError(f"Нет соединения с {url}: {e}. Если это ошибка SSL — поставьте verify_ssl: false "
                                f"или путь к сертификату НУЦ Минцифры в config.yaml") from e
        if r.status_code >= 400:
            raise ProviderError(f"GigaChat {r.status_code} на {url}: {r.text[:300]}")
        return r.json()

    def token(self):
        if self._token and time.time() < self._exp - 60:
            return self._token
        j = self._req("POST", self.oauth_url, data={"scope": self.scope},
                      headers={"Authorization": f"Basic {self.auth_key}", "RqUID": str(uuid.uuid4()),
                               "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        self._token, self._exp = j["access_token"], j["expires_at"] / 1000
        return self._token

    def models(self):
        return [m["id"] for m in self._req("GET", f"{self.api_url}/models",
                                           headers={"Authorization": f"Bearer {self.token()}"})["data"]]

    @staticmethod
    def _msg(m):
        if m["role"] == "assistant" and m.get("tool_calls"):
            c = m["tool_calls"][0]                      # GigaChat возвращает один вызов за ответ
            return {"role": "assistant", "content": m.get("content") or "",
                    "function_call": {"name": c["name"], "arguments": c["arguments"]}}
        if m["role"] == "tool":
            return {"role": "function", "name": m["name"], "content": m["content"]}
        return {"role": m["role"], "content": m.get("content") or ""}

    def chat(self, messages, tools):
        functions = [{"name": t["name"], "description": t["description"],
                      "parameters": simplify_schema(t["parameters"])} for t in tools]
        body = {"model": self.model, "messages": [self._msg(m) for m in messages],
                "functions": functions, "function_call": "auto", "temperature": 0.1}
        j = self._req("POST", f"{self.api_url}/chat/completions", json=body,
                      headers={"Authorization": f"Bearer {self.token()}"})
        msg = j["choices"][0]["message"]
        calls = []
        if fc := msg.get("function_call"):
            args = fc.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    pass                                # пусть execute_tool вернёт validation
            calls.append({"id": f"call_{uuid.uuid4().hex[:8]}", "name": fc["name"], "arguments": args})
        return {"content": msg.get("content"), "tool_calls": calls}
