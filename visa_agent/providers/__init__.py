"""Адаптеры провайдеров. Цикл агента один, форматы разные.

Внутренний формат сообщений (нейтральный):
  {"role": "system"|"user", "content": str}
  {"role": "assistant", "content": str|None, "tool_calls": [{"id", "name", "arguments": dict}]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str(JSON)}
Ответ провайдера: {"content": str|None, "tool_calls": [...]}.
"""


def make_provider(cfg: dict):
    p = cfg["provider"]
    model = cfg["models"][p]
    if p == "mock":
        from .mock import MockProvider
        return MockProvider()
    if p == "openai":
        from .openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(model, cfg["openai"].get("base_url"))
    if p == "gigachat":
        from .gigachat import GigaChatProvider
        return GigaChatProvider(model, cfg["gigachat"])
    raise ValueError(f"Неизвестный провайдер в config.yaml: {p}")
