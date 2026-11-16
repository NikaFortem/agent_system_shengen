"""Цикл агента: модель предлагает шаг → код проверяет и выполняет → результат в контекст → снова модель."""
import json

from .data import VisaStore
from .providers import make_provider
from .tools import TOOLS, Session, err, execute_tool, tool_specs

RETRYABLE = ("timeout", "unavailable", "rate_limit")

SYSTEM = """Ты помощник по шенгенским визам для граждан России. Отвечай по-русски, коротко и по делу.
Цифры (сроки, доли отказов) бери только из результатов инструментов и не придумывай. Указывай источник.
Если инструмент вернул ошибку — прочитай type и hint: исправь аргументы, уточни у пользователя
или честно скажи, что данные сейчас недоступны. Не выдумывай ответ вместо данных.
Добавление в календарь выполняется только после подтверждения пользователем — не утверждай,
что пользователь согласен, это проверяет система. Сегодня {today}."""


class PendingConfirmation(Exception):
    """Для UI: действие ждёт решения пользователя (кнопки «Да/Нет»)."""
    def __init__(self, card):
        self.card = card


class Agent:
    def __init__(self, cfg: dict, session: Session, provider=None, trace=None):
        self.cfg, self.session = cfg, session
        self.provider = provider or make_provider(cfg)
        self.store = VisaStore(cfg["data"]["cases"], cfg["data"]["ec_stats"])
        self.tools = tool_specs()
        self.messages = [{"role": "system", "content": SYSTEM.format(today=session.today.isoformat())}]
        self.trace = trace or (lambda *a: None)     # куда писать трассу шагов

    def ask(self, text: str, confirm=None) -> str:
        self.messages.append({"role": "user", "content": text})
        self._fails = {}
        return self._loop(confirm)

    def resume(self, approved: bool) -> str:
        """Продолжить после карточки подтверждения в UI."""
        self._run_calls(self.messages[-1]["tool_calls"], lambda *_: approved)
        return self._loop(None)

    def _run_calls(self, calls, confirm):
        for c in calls:
            limit = self.cfg["agent"]["max_tool_retries"]
            if self._fails.get(c["name"], 0) > limit:
                res = err("retry_limit", f"{c['name']} уже падал {self._fails[c['name']]} раз(а)",
                          "Больше не повторяй, честно сообщи пользователю")
            else:
                res = execute_tool(c["name"], c["arguments"], self.session, self.store, self.cfg, confirm)
                # сбой сервиса при ЧТЕНИИ harness повторяет сам (действие — нет, только с ключом идемпотентности)
                for _ in range(self.cfg["agent"].get("read_retries", 1)):
                    if TOOLS.get(c["name"], {}).get("kind") != "read" or res.get("error", {}).get("type") not in RETRYABLE:
                        break
                    self.trace("retry", c["name"], res["error"]["type"])
                    res = execute_tool(c["name"], c["arguments"], self.session, self.store, self.cfg, confirm)
            if "error" in res:
                self._fails[c["name"]] = self._fails.get(c["name"], 0) + 1
            self.trace("tool", c["name"], c["arguments"], res)
            self.messages.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                                  "content": json.dumps(res, ensure_ascii=False, default=str)})

    def _loop(self, confirm) -> str:
        for step in range(self.cfg["agent"]["max_steps"]):
            try:
                out = self.provider.chat(self.messages, self.tools)
            except Exception as e:  # noqa: BLE001 — модель недоступна: не падаем, честно говорим
                self.trace("final", f"provider error: {e}")
                return f"Модель сейчас недоступна ({type(e).__name__}): {str(e)[:200]}"
            calls = out.get("tool_calls") or []
            self.messages.append({"role": "assistant", "content": out.get("content"), "tool_calls": calls})
            if not calls:
                self.trace("final", out.get("content"))
                return out.get("content") or ""
            self.trace("model", step + 1, calls)
            if confirm is None:                               # режим UI: карточка вместо input()
                def confirm(name, card):
                    raise PendingConfirmation(card)
            self._run_calls(calls, confirm)
        msg = "Не удалось уложиться в лимит шагов. Попробуйте переформулировать вопрос."
        self.trace("final", msg)
        self.messages.append({"role": "assistant", "content": msg, "tool_calls": []})
        return msg
