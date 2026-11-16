"""Инструменты агента: схема (видит модель) + реализация + обёртка execute_tool (знает только код).

execute_tool делает шаги 3–6 из лекции: разбирает и проверяет аргументы по схеме,
проверяет права/подтверждение, выполняет функцию с таймаутом и превращает любую
проблему в обычный результат {"error": {type, message, hint}} — агент не падает.
"""
import concurrent.futures as cf
import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from .data import COUNTRY_RU, VisaStore

Country = Literal["IT", "ES", "FR", "GR", "HU", "DE", "BG", "NL", "CH", "CY", "FI"]
City = Literal["Москва", "Санкт-Петербург", "Екатеринбург", "Казань", "Новосибирск", "Краснодар"]
MAX_RESULTS = 10          # потолок размера результата
EXCERPT_CHARS = 200
MIN_CASES = 5             # меньше — метрике не верим


# ---------------------------------------------------------------- сессия
@dataclass
class Session:
    """То, что код знает сам. Модель это не выбирает."""
    user_id: str
    today: date = field(default_factory=date.today)


# ---------------------------------------------------------------- схемы
class SearchVisaCases(BaseModel):
    """Найти реальные кейсы получения шенгенской визы гражданами РФ из Telegram-чата @schengen_chat \
(отчёты с тегом #статистика за июль–ноябрь 2026). Используй, когда пользователь хочет посмотреть похожие \
истории: «кто подавался в Италию в Москве», «были ли отказы у Испании». Не используй для сроков и \
процента отказов — для цифр есть get_country_metrics. Возвращает не больше `limit` кейсов (новые сверху) \
с датой подачи, сроком рассмотрения в днях, решением, коротким фрагментом и ссылкой на сообщение, \
а также сколько всего найдено."""
    country: Country = Field(description="Страна Шенгена, ISO-код: IT, ES, FR, GR, HU, DE, BG, NL, CH, CY, FI")
    city: Optional[City] = Field(None, description="Город подачи в России. Не указывай, если пользователь не назвал")
    outcome: Optional[Literal["approved", "refused"]] = Field(None, description="Только одобрения или только отказы")
    limit: int = Field(5, ge=1, le=MAX_RESULTS, description="Сколько кейсов вернуть, 1–10")


class GetCountryMetrics(BaseModel):
    """Посчитать метрики подачи на шенгенскую визу для граждан РФ по стране (и городу подачи): \
медиану и разброс срока рассмотрения в днях по кейсам из чата за последние `period_days` дней \
и долю отказов и мультивиз по официальной статистике Еврокомиссии за 2025 год. Используй, когда \
пользователь спрашивает «сколько рассматривают», «часто ли отказывают», «куда проще подаваться». \
Цифры считает код, не пересчитывай их сам. Не используй, чтобы посчитать, когда подавать документы, — для этого add_visa_timeline_to_calendar. Если кейсов меньше 5, вернётся ошибка insufficient_data — тогда сам повтори вызов с period_days=365 и без city."""
    country: Country = Field(description="Страна Шенгена, ISO-код")
    city: Optional[City] = Field(None, description="Город подачи в России, если пользователь его назвал")
    period_days: Literal[90, 180, 365] = Field(
        180, description="За сколько последних дней брать кейсы: 90, 180 или 365. По умолчанию 180; "
                         "90 — только если пользователь прямо просит последние месяцы")


class AddVisaTimelineToCalendar(BaseModel):
    """Рассчитать визовый план к дате вылета: когда открывается подача (−180 дней), когда начинать ловить \
запись, крайний срок подачи (медиана рассмотрения по стране + 10 дней запаса, но не позже чем за 15 дней \
до вылета) и ожидаемую дату решения. ВСЕГДА используй этот инструмент, когда пользователь назвал дату \
поездки и спрашивает, когда подавать документы, — даже если про календарь он не говорил. Сам даты не \
вычисляй. Пользователь увидит план на карточке и сам решит, добавлять ли его в календарь (.ics); если \
откажется, план всё равно вернётся в поле plan — перескажи его. Если по срокам уже не успеть, вернётся \
ошибка too_late с подсказкой — перескажи её. Перед вызовом не нужно вызывать get_country_metrics."""
    country: Country = Field(description="Страна Шенгена, ISO-код")
    city: Optional[City] = Field(None, description="Город подачи в России, если назван")
    trip_start: str = Field(description="Дата вылета, формат YYYY-MM-DD")

    @field_validator("trip_start")
    @classmethod
    def _iso(cls, v):
        date.fromisoformat(v)
        return v


TOOLS = {
    "search_visa_cases": {"model": SearchVisaCases, "kind": "read"},
    "get_country_metrics": {"model": GetCountryMetrics, "kind": "read"},
    "add_visa_timeline_to_calendar": {"model": AddVisaTimelineToCalendar, "kind": "action"},
}


def tool_specs() -> list[dict]:
    """Нейтральное описание инструментов; адаптеры провайдеров переводят его в свой формат."""
    specs = []
    for name, t in TOOLS.items():
        schema = t["model"].model_json_schema()
        specs.append({"name": name, "description": " ".join(schema.pop("description").split()),
                      "parameters": {k: v for k, v in schema.items() if k != "title"}})
    return specs


def err(type_, message, hint=None):
    e = {"type": type_, "message": message}
    if hint:
        e["hint"] = hint
    return {"error": e}


# ---------------------------------------------------------------- реализации
class ToolError(Exception):
    def __init__(self, type_, message, hint=None):
        super().__init__(message)
        self.payload = err(type_, message, hint)


def search_visa_cases(a: SearchVisaCases, s: Session, store: VisaStore):
    found = store.find_cases(a.country, a.city, a.outcome)
    if not found:
        raise ToolError("not_found", f"Нет кейсов: {COUNTRY_RU[a.country]}{', ' + a.city if a.city else ''}",
                        "Убери фильтр по городу или решению, либо предложи соседнюю страну")
    items = [{"posted": c["posted"], "city": c["city"], "submitted": c["submitted"],
              "processing_days": c["processing_days"], "outcome": c["outcome"],
              "excerpt": c["excerpt"][:EXCERPT_CHARS], "source": c["source"]} for c in found[:a.limit]]
    return {"shown": len(items), "total": len(found), "cases": items,
            "note": f"показано {len(items)} из {len(found)}" if len(found) > len(items) else None}


def get_country_metrics(a: GetCountryMetrics, s: Session, store: VisaStore):
    st = store.processing_stats(a.country, a.city, a.period_days, s.today)
    if st["n"] < MIN_CASES:
        raise ToolError("insufficient_data",
                        f"Мало кейсов для {COUNTRY_RU[a.country]}{', ' + a.city if a.city else ''}: {st['n']} (нужно ≥{MIN_CASES})",
                        "Сам повтори вызов с period_days=365 и без city, не спрашивая пользователя")
    return {"country": COUNTRY_RU[a.country], "city": a.city, "period_days": a.period_days,
            "processing_days": {"median": st["median"], "p25": st["p25"], "p75": st["p75"], "cases": st["n"]},
            "ec_2025": store.ec_stats(a.country, a.city if a.city in ("Москва", "Санкт-Петербург") else None),
            "sources": "кейсы @schengen_chat (#статистика); статистика Еврокомиссии по консульствам за 2025"}


def plan_timeline(a: AddVisaTimelineToCalendar, s: Session, store: VisaStore):
    """Чистый расчёт плана (без записи). Его же показываем на карточке подтверждения."""
    trip = date.fromisoformat(a.trip_start)
    if trip <= s.today:
        raise ToolError("validation", "Дата вылета уже прошла", "Уточни у пользователя дату вылета")
    if trip > s.today + timedelta(days=365):
        raise ToolError("validation", "Дата вылета дальше чем через год", "Уточни дату; план строим до года вперёд")
    st = store.processing_stats(a.country, None, 365, s.today)
    if st["n"] >= MIN_CASES:
        median, basis = int(round(st["median"])), f"медиана по {st['n']} кейсам из чата"
    else:
        median, basis = 15, "кейсов мало — взят официальный минимум 15 дней"
    deadline = min(trip - timedelta(days=median + 10), trip - timedelta(days=15))
    opens = trip - timedelta(days=180)
    if deadline < s.today:
        fastest = min((c for c in COUNTRY_RU if store.processing_stats(c, None, 365, s.today)["n"] >= MIN_CASES),
                      key=lambda c: store.processing_stats(c, None, 365, s.today)["median"])
        raise ToolError("too_late",
                        f"До вылета {(trip - s.today).days} дн., а {COUNTRY_RU[a.country]} рассматривает ~{median} дн. Подать вовремя уже не получится",
                        f"Предложи перенести поездку или выбрать страну с быстрым рассмотрением: {COUNTRY_RU[fastest]}")
    submit_by = max(deadline, s.today)
    events = [
        {"date": max(opens, s.today).isoformat(), "title": f"Виза {COUNTRY_RU[a.country]}: можно подавать документы"},
        {"date": max(submit_by - timedelta(days=21), s.today).isoformat(), "title": "Начать ловить запись в визовый центр"},
        {"date": submit_by.isoformat(), "title": f"Крайний срок подачи ({basis}: {median} дн. + 10 дн. запаса)"},
        {"date": (submit_by + timedelta(days=median)).isoformat(), "title": "Ожидаемое решение по визе"},
    ]
    return {"country": COUNTRY_RU[a.country], "trip_start": a.trip_start, "processing_median_days": median,
            "basis": basis, "events": events}


def _ics(events, uid):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//visa-agent//RU"]
    for i, e in enumerate(events):
        d = e["date"].replace("-", "")
        lines += ["BEGIN:VEVENT", f"UID:{uid}-{i}", f"DTSTART;VALUE=DATE:{d}", f"SUMMARY:{e['title']}", "END:VEVENT"]
    return "\r\n".join(lines + ["END:VCALENDAR"]) + "\r\n"


def add_visa_timeline_to_calendar(a, s, store, cfg):
    plan = plan_timeline(a, s, store)
    key = f"{s.user_id}_{a.country}_{a.trip_start}"          # ключ идемпотентности
    path = os.path.join(cfg["data"]["calendar_dir"], f"{key}.ics")
    if os.path.exists(path):
        return {"status": "already_exists", "file": path, "events": plan["events"],
                "message": "Этот план уже был в календаре, дубль не создан. Даты — в events, других дат не называй"}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_ics(plan["events"], key))
    return {"status": "added", "file": path, "events": plan["events"],
            "message": "План добавлен. Перескажи даты из events, других дат не называй"}


IMPL = {"search_visa_cases": search_visa_cases, "get_country_metrics": get_country_metrics}

# ---------------------------------------------------------------- подмена сбоев (уровень 3)
FAULTS: dict[str, list[str]] = {}   # например {"get_country_metrics": ["timeout"]}


# ---------------------------------------------------------------- обёртка
def _audit(cfg, record):
    os.makedirs(os.path.dirname(cfg["data"]["audit_log"]), exist_ok=True)
    with open(cfg["data"]["audit_log"], "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def humanize_validation(e: ValidationError) -> str:
    parts = []
    for x in e.errors():
        loc = ".".join(str(p) for p in x["loc"]) or "arguments"
        parts.append(f"{loc}: {x['msg']}")
    return "; ".join(parts)


def execute_tool(name: str, raw_args, session: Session, store: VisaStore, cfg: dict,
                 confirm: Optional[Callable[[str, dict], bool]] = None) -> dict:
    """Единая точка выполнения. Никогда не бросает исключение наружу."""
    if name not in TOOLS:
        return err("unknown_tool", f"Нет инструмента {name}", f"Доступны: {', '.join(TOOLS)}")
    # 3. разбор JSON
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args or "{}")
        except json.JSONDecodeError:
            return err("validation", "Аргументы не являются JSON", "Пришли аргументы JSON-объектом")
    # 4. проверка по схеме
    try:
        args = TOOLS[name]["model"].model_validate(raw_args)
    except ValidationError as e:
        return err("validation", humanize_validation(e), "Исправь аргументы по схеме и повтори")
    # подменённый сбой (для тестов и демо)
    if FAULTS.get(name):
        kind = FAULTS[name].pop(0)
        _audit(cfg, {"tool": name, "args": raw_args, "user": session.user_id, "fault": kind})
        return err(kind, f"{name}: сервис не ответил ({kind}, тест)", "Повтор уже был. Не выдумывай цифры: честно скажи, что сервис сейчас недоступен")
    # 5. действие — только после подтверждения конкретных параметров человеком
    if TOOLS[name]["kind"] == "action":
        try:
            card = plan_timeline(args, session, store)
        except ToolError as e:
            return e.payload
        if confirm is None or not confirm(name, card):
            _audit(cfg, {"tool": name, "args": raw_args, "user": session.user_id, "result": "cancelled"})
            return {"cancelled": True, "message": "Пользователь не добавил план в календарь", "plan": card}
        fn = lambda: add_visa_timeline_to_calendar(args, session, store, cfg)
    else:
        fn = lambda: IMPL[name](args, session, store)
    # 6. выполнение с таймаутом
    ex = cf.ThreadPoolExecutor(max_workers=1)
    try:
        result = ex.submit(fn).result(timeout=cfg["agent"]["tool_timeout_s"])
    except cf.TimeoutError:
        result = err("timeout", f"{name}: сервис не ответил за {cfg['agent']['tool_timeout_s']} с",
                     "Повтор уже был. Не выдумывай цифры: честно скажи, что сервис сейчас недоступен")
    except ToolError as e:
        result = e.payload
    except Exception as e:  # noqa: BLE001 — стек в контекст модели не отдаём
        result = err("internal", "Внутренняя ошибка инструмента", "Извинись и предложи попробовать позже")
        _audit(cfg, {"tool": name, "exception": repr(e)})
    finally:
        ex.shutdown(wait=False)
    _audit(cfg, {"tool": name, "args": raw_args, "user": session.user_id,
                 "result": result.get("error", {}).get("type", "ok") if isinstance(result, dict) else "ok"})
    return result
