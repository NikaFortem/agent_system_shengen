"""Заглушка модели: по ключевым словам возвращает заранее определённые вызовы инструментов.

Нужна для отладки цикла и демо без ключей. Логика намеренно простая — это не «умная» модель,
а детерминированный стенд, на котором видно, как harness проверяет, выполняет и обрабатывает ошибки.
"""
import json
import re
import uuid

COUNTRIES = {"IT": r"итал", "ES": r"испан", "FR": r"франц", "GR": r"грец|грек", "HU": r"венгр",
             "DE": r"герман", "BG": r"болгар", "NL": r"нидерл|голланд", "CH": r"швейц", "FI": r"финл", "CY": r"кипр"}
CITIES = {"Москва": r"москв|мск", "Санкт-Петербург": r"спб|петербург|питер", "Екатеринбург": r"екатеринб",
          "Казань": r"казан"}


def _call(name, args):
    return {"content": None, "tool_calls": [{"id": f"call_{uuid.uuid4().hex[:6]}", "name": name, "arguments": args}]}


class MockProvider:
    def chat(self, messages, tools):
        last = messages[-1]
        if last["role"] == "tool":
            return self._after_tool(messages)
        text = last["content"].lower()
        country = next((k for k, v in COUNTRIES.items() if re.search(v, text)), None)
        city = next((k for k, v in CITIES.items() if re.search(v, text)), None)
        date_m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if not country:
            return {"content": "Подскажите, в какую страну Шенгена планируете подаваться и из какого города?", "tool_calls": []}
        if date_m or re.search(r"когда подава|календар|план", text):
            if not date_m:
                return {"content": "На какую дату вылета строить план? Формат ГГГГ-ММ-ДД.", "tool_calls": []}
            return _call("add_visa_timeline_to_calendar", {"country": country, "city": city, "trip_start": date_m[1]})
        if re.search(r"кейс|истори|опыт|отказ", text):
            args = {"country": country, "city": city, "limit": 3}
            if "отказ" in text:
                args["outcome"] = "refused"
            return _call("search_visa_cases", args)
        return _call("get_country_metrics", {"country": country, "city": city, "period_days": 180})

    def _after_tool(self, messages):
        last = messages[-1]
        res = json.loads(last["content"])
        # сколько раз подряд этот инструмент уже падал
        fails = 0
        for m in reversed(messages):
            if m["role"] == "tool" and m["name"] == last["name"] and "error" in json.loads(m["content"]):
                fails += 1
            elif m["role"] == "user":
                break
        if "error" in res:
            e = res["error"]
            if e["type"] in ("timeout", "rate_limit", "unavailable") and fails <= 1:
                prev = next(m for m in reversed(messages) if m["role"] == "assistant" and m.get("tool_calls"))
                c = prev["tool_calls"][0]
                return _call(c["name"], c["arguments"])          # один повтор
            if e["type"] == "insufficient_data" and last["name"] == "get_country_metrics":
                prev = next(m for m in reversed(messages) if m["role"] == "assistant" and m.get("tool_calls"))
                a = dict(prev["tool_calls"][0]["arguments"])
                if a.get("city") or a.get("period_days", 180) < 365:
                    a.update(city=None, period_days=365)
                    return _call("get_country_metrics", a)
            if e["type"] in ("timeout", "unavailable", "retry_limit"):
                return {"content": "Сервис статистики сейчас не отвечает — не буду гадать с цифрами. Попробуйте чуть позже.",
                        "tool_calls": []}
            hint = e.get("hint", "").replace("Предложи перенести", "Можно перенести")
            return {"content": f"{e['message']}. {hint}", "tool_calls": []}
        if res.get("cancelled"):
            return {"content": "Хорошо, ничего не добавляю в календарь.", "tool_calls": []}
        name = last["name"]
        if name == "get_country_metrics":
            p, ec = res["processing_days"], res.get("ec_2025") or {}
            return {"content": f"{res['country']}{', ' + res['city'] if res['city'] else ''}: по {p['cases']} кейсам из чата "
                               f"за {res['period_days']} дн. медиана рассмотрения {p['median']:.0f} дн. (обычно {p['p25']:.0f}–{p['p75']:.0f}). "
                               f"По статистике ЕК за 2025: отказов {ec.get('refusal_rate_pct')}%, мультивиз {ec.get('multi_entry_share_pct')}% "
                               f"(до запрета мультивиз в ноябре 2025 — сейчас дают в основном однократные).", "tool_calls": []}
        if name == "search_visa_cases":
            lines = [f"• {c['posted']}, {c['city'] or 'город не указан'}: {c['outcome'] or '?'}, "
                     f"{str(c['processing_days']) + ' дн.' if c['processing_days'] else 'срок не указан'} — {c['source']}"
                     for c in res["cases"]]
            return {"content": f"Найдено кейсов: {res['total']}, показываю {res['shown']}:\n" + "\n".join(lines), "tool_calls": []}
        if name == "add_visa_timeline_to_calendar":
            if res.get("status") == "already_exists":
                return {"content": "Этот план уже в календаре, дубли не создаю.", "tool_calls": []}
            ev = "\n".join(f"• {e['date']} — {e['title']}" for e in res["events"])
            return {"content": f"Добавил в календарь ({res['file']}):\n{ev}", "tool_calls": []}
        return {"content": json.dumps(res, ensure_ascii=False), "tool_calls": []}
