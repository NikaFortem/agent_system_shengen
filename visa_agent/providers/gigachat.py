"""GigaChat API: functions / function_call, arguments — объект, результат — роль function.

Документация: https://developers.sber.ru/docs/ru/gigachat/guides/functions-overview
Ключ авторизации (Authorization key из личного кабинета) — в .env: GIGACHAT_AUTH_KEY.
"""
import json
import os
import time
import uuid

import httpx

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"


class GigaChatProvider:
    def __init__(self, model: str, cfg: dict):
        self.model, self.scope, self.verify = model, cfg.get("scope", "GIGACHAT_API_PERS"), cfg.get("verify_ssl", False)
        self.auth_key = os.environ["GIGACHAT_AUTH_KEY"]
        self._token, self._exp = None, 0

    def _token_get(self):
        if self._token and time.time() < self._exp - 60:
            return self._token
        r = httpx.post(OAUTH_URL, data={"scope": self.scope}, verify=self.verify, timeout=30,
                       headers={"Authorization": f"Basic {self.auth_key}", "RqUID": str(uuid.uuid4()),
                                "Content-Type": "application/x-www-form-urlencoded"})
        r.raise_for_status()
        j = r.json()
        self._token, self._exp = j["access_token"], j["expires_at"] / 1000
        return self._token

    @staticmethod
    def _msg(m):
        if m["role"] == "assistant" and m.get("tool_calls"):
            c = m["tool_calls"][0]                      # GigaChat возвращает один вызов за ответ
            return {"role": "assistant", "content": m.get("content") or "",
                    "function_call": {"name": c["name"], "arguments": c["arguments"]}}
        if m["role"] == "tool":
            return {"role": "function", "name": m["name"], "content": m["content"]}
        return {"role": m["role"], "content": m["content"]}

    def chat(self, messages, tools):
        body = {"model": self.model, "messages": [self._msg(m) for m in messages],
                "functions": tools, "function_call": "auto"}
        r = httpx.post(API_URL, json=body, verify=self.verify, timeout=60,
                       headers={"Authorization": f"Bearer {self._token_get()}"})
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        fc = msg.get("function_call")
        calls = []
        if fc:
            args = fc.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    pass
            calls.append({"id": f"call_{uuid.uuid4().hex[:8]}", "name": fc["name"], "arguments": args})
        return {"content": msg.get("content"), "tool_calls": calls}
