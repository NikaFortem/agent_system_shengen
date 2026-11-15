"""Уровень 1 (инструмент как функция) и уровень 3 (подмена ответа сервиса). Модель не нужна."""
import os
import time
from datetime import date

import pytest

from visa_agent import tools
from visa_agent.agent import Agent
from visa_agent.config import load_config
from visa_agent.data import VisaStore
from visa_agent.providers.mock import MockProvider
from visa_agent.tools import Session, execute_tool, tool_specs


@pytest.fixture
def cfg(tmp_path):
    c = load_config()
    c["provider"] = "mock"
    c["data"]["calendar_dir"] = str(tmp_path / "cal")
    c["data"]["audit_log"] = str(tmp_path / "audit.log")
    c["agent"]["tool_timeout_s"] = 1
    return c


@pytest.fixture
def store(cfg):
    return VisaStore(cfg["data"]["cases"], cfg["data"]["ec_stats"])


@pytest.fixture
def session():
    return Session(user_id="u1", today=date(2026, 11, 15))


@pytest.fixture(autouse=True)
def no_faults():
    tools.FAULTS.clear()
    yield
    tools.FAULTS.clear()


def run(name, args, session, store, cfg, confirm=None):
    return execute_tool(name, args, session, store, cfg, confirm)


# --- схема и проверка аргументов ---------------------------------------
def test_specs_have_no_user_id():
    for t in tool_specs():
        assert "user_id" not in t["parameters"]["properties"]   # пользователь — из сессии


def test_unknown_country_is_validation_error(session, store, cfg):
    r = run("get_country_metrics", {"country": "RU"}, session, store, cfg)
    assert r["error"]["type"] == "validation" and "hint" in r["error"]


def test_period_out_of_range(session, store, cfg):
    r = run("get_country_metrics", {"country": "IT", "period_days": 1000}, session, store, cfg)
    assert r["error"]["type"] == "validation"


def test_bad_json_arguments(session, store, cfg):
    r = run("search_visa_cases", "{not json", session, store, cfg)
    assert r["error"]["type"] == "validation"


def test_bad_date_format(session, store, cfg):
    r = run("add_visa_timeline_to_calendar", {"country": "ES", "trip_start": "20.03.2027"}, session, store, cfg,
            confirm=lambda *_: True)
    assert r["error"]["type"] == "validation"


# --- результат ограничен --------------------------------------------------
def test_search_limit_and_total(session, store, cfg):
    r = run("search_visa_cases", {"country": "IT", "limit": 3}, session, store, cfg)
    assert r["shown"] == 3 and r["total"] > 3 and "показано 3" in r["note"]
    assert all(len(c["excerpt"]) <= tools.EXCERPT_CHARS for c in r["cases"])


def test_search_limit_cap(session, store, cfg):
    r = run("search_visa_cases", {"country": "IT", "limit": 500}, session, store, cfg)
    assert r["error"]["type"] == "validation"


def test_not_found(session, store, cfg):
    r = run("search_visa_cases", {"country": "FI", "city": "Казань"}, session, store, cfg)
    assert r["error"]["type"] == "not_found"


def test_insufficient_data(session, store, cfg):
    r = run("get_country_metrics", {"country": "FI"}, session, store, cfg)
    assert r["error"]["type"] == "insufficient_data"


def test_metrics_ok(session, store, cfg):
    r = run("get_country_metrics", {"country": "IT", "city": "Москва"}, session, store, cfg)
    assert r["processing_days"]["cases"] >= 5 and 0 < r["ec_2025"]["refusal_rate_pct"] < 100


# --- действие: подтверждение, идемпотентность, бизнес-правила -------------
ARGS = {"country": "ES", "trip_start": "2027-03-20"}


def test_action_needs_confirmation(session, store, cfg):
    r = run("add_visa_timeline_to_calendar", ARGS, session, store, cfg, confirm=lambda *_: False)
    assert r == {"cancelled": True, "message": "Пользователь не подтвердил действие"}
    assert not os.path.exists(cfg["data"]["calendar_dir"])


def test_action_without_confirm_callback_is_not_executed(session, store, cfg):
    r = run("add_visa_timeline_to_calendar", ARGS, session, store, cfg, confirm=None)
    assert r.get("cancelled") is True


def test_action_executes_exactly_confirmed_params(session, store, cfg):
    seen = {}
    r = run("add_visa_timeline_to_calendar", ARGS, session, store, cfg,
            confirm=lambda n, card: seen.update(card) or True)
    assert r["status"] == "added" and r["events"] == seen["events"]
    assert open(r["file"], encoding="utf-8").read().count("BEGIN:VEVENT") == 4


def test_action_idempotent(session, store, cfg):
    yes = lambda *_: True
    run("add_visa_timeline_to_calendar", ARGS, session, store, cfg, confirm=yes)
    r = run("add_visa_timeline_to_calendar", ARGS, session, store, cfg, confirm=yes)
    assert r["status"] == "already_exists"


def test_too_late(session, store, cfg):
    r = run("add_visa_timeline_to_calendar", {"country": "IT", "trip_start": "2026-12-10"}, session, store, cfg,
            confirm=lambda *_: True)
    assert r["error"]["type"] == "too_late" and "hint" in r["error"]


def test_trip_in_past(session, store, cfg):
    r = run("add_visa_timeline_to_calendar", {"country": "IT", "trip_start": "2026-01-01"}, session, store, cfg,
            confirm=lambda *_: True)
    assert r["error"]["type"] == "validation"


# --- уровень 3: сбои сервиса ----------------------------------------------
def test_fault_becomes_error_not_exception(session, store, cfg):
    tools.FAULTS["get_country_metrics"] = ["timeout"]
    r = run("get_country_metrics", {"country": "IT"}, session, store, cfg)
    assert r["error"]["type"] == "timeout"


def test_real_timeout(session, store, cfg, monkeypatch):
    monkeypatch.setitem(tools.IMPL, "get_country_metrics", lambda *a: time.sleep(3))
    r = run("get_country_metrics", {"country": "IT"}, session, store, cfg)
    assert r["error"]["type"] == "timeout"


def test_internal_exception_hidden(session, store, cfg, monkeypatch):
    def boom(*a):
        raise RuntimeError("db down")
    monkeypatch.setitem(tools.IMPL, "search_visa_cases", boom)
    r = run("search_visa_cases", {"country": "IT"}, session, store, cfg)
    assert r["error"]["type"] == "internal" and "db down" not in str(r)


# --- цикл агента на заглушке ----------------------------------------------
def test_agent_retries_once_then_answers_honestly(cfg, session):
    tools.FAULTS["get_country_metrics"] = ["timeout"] * 5
    a = Agent(cfg, session, provider=MockProvider())
    answer = a.ask("Какие сроки по Франции?")
    calls = [m for m in a.messages if m["role"] == "tool"]
    assert len(calls) == 2 and "не отвечает" in answer


def test_agent_step_limit(cfg, session):
    class Looping:
        def chat(self, messages, tools):
            return {"content": None, "tool_calls": [{"id": "x", "name": "search_visa_cases",
                                                     "arguments": {"country": "IT", "limit": 1}}]}
    cfg["agent"]["max_steps"] = 3
    a = Agent(cfg, session, provider=Looping())
    assert "лимит шагов" in a.ask("привет")
    assert sum(m["role"] == "tool" for m in a.messages) == 3
