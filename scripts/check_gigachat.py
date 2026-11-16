"""Пошаговая проверка подключения к GigaChat: ключ → токен → модели → вызов функции.

python scripts/check_gigachat.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from visa_agent.config import load_config  # noqa: E402
from visa_agent.providers.gigachat import GigaChatProvider, ProviderError  # noqa: E402
from visa_agent.tools import tool_specs  # noqa: E402

cfg = load_config()
model = cfg["models"]["gigachat"]
try:
    p = GigaChatProvider(model, cfg["gigachat"])
    print("1/4 ключ найден в .env")
    p.token()
    print("2/4 токен получен (scope =", p.scope + ")")
    ms = p.models()
    print("3/4 доступные модели:", ", ".join(ms))
    if model not in ms:
        print(f"    ⚠ модели {model} нет в списке — поменяйте models.gigachat в config.yaml на одну из доступных")
        sys.exit(1)
    r = p.chat([{"role": "user", "content": "Сколько сейчас рассматривают визу в Италию в Москве?"}], tool_specs())
    if r["tool_calls"]:
        c = r["tool_calls"][0]
        print(f"4/4 модель вызвала инструмент: {c['name']}({c['arguments']})")
        print("Готово: в config.yaml поставьте provider: gigachat и запускайте python demo.py")
    else:
        print("4/4 модель ответила текстом без вызова инструмента:", (r["content"] or "")[:200])
except ProviderError as e:
    print("ОШИБКА:", e)
    sys.exit(1)
