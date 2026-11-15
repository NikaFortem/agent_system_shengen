"""Минимальный веб-интерфейс: дашборд + чат с агентом и карточкой подтверждения.

streamlit run app.py
"""
import json
from datetime import date

import pandas as pd
import streamlit as st

from visa_agent import tools
from visa_agent.agent import Agent, PendingConfirmation
from visa_agent.config import load_config
from visa_agent.data import COUNTRY_NAMES, COUNTRY_RU
from visa_agent.tools import Session

st.set_page_config(page_title="Шенген-аналитика", page_icon="🛂", layout="wide")
cfg = load_config()


@st.cache_data
def load_frames():
    cases = pd.DataFrame(json.load(open(cfg["data"]["cases"], encoding="utf-8")))
    ec = pd.read_csv(cfg["data"]["ec_stats"])
    return cases, ec


cases, ec = load_frames()
tab_dash, tab_chat = st.tabs(["📊 Дашборд", "💬 Чат с агентом"])

# ------------------------------------------------------------------ дашборд
with tab_dash:
    st.header("Шенген для граждан РФ: сроки и отказы")
    st.caption("Сроки рассмотрения — отчёты #статистика из @schengen_chat (июль–ноябрь 2026). "
               "Отказы и мультивизы — статистика Еврокомиссии по консульствам в России за 2025 год.")
    ec_c = ec.groupby("schengen_state")[["applications", "issued", "refused", "multiple_entry_issued"]].sum()
    ec_c["Отказов, %"] = (100 * ec_c.refused / ec_c.applications).round(1)
    ec_c["Мультивиз, %"] = (100 * ec_c.multiple_entry_issued / ec_c.issued).round(1)
    proc = cases.dropna(subset=["processing_days"]).groupby("country").processing_days.agg(["median", "count"])
    rows = []
    for code, name in COUNTRY_NAMES.items():
        if name in ec_c.index:
            r = ec_c.loc[name]
            rows.append({"Страна": COUNTRY_RU[code], "Заявлений 2025": int(r.applications),
                         "Отказов, %": r["Отказов, %"], "Мультивиз, %": r["Мультивиз, %"],
                         "Медиана рассмотрения, дн.": proc.loc[code, "median"] if code in proc.index and proc.loc[code, "count"] >= 5 else None,
                         "Кейсов в чате": int(proc.loc[code, "count"]) if code in proc.index else 0})
    df = pd.DataFrame(rows).sort_values("Заявлений 2025", ascending=False)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Заявлений из РФ, 2025", f"{int(ec.applications.sum()):,}".replace(",", " "))
    k2.metric("Доля отказов, 2025", f"{100 * ec.refused.sum() / ec.applications.sum():.1f}%")
    k3.metric("Кейсов из чата", len(cases))
    k4.metric("Медиана рассмотрения (все)", f"{cases.processing_days.median():.0f} дн.")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Доля отказов, % (ЕК 2025)")
        st.bar_chart(df[df["Заявлений 2025"] > 1000].set_index("Страна")["Отказов, %"], horizontal=True)
    with c2:
        st.subheader("Медиана рассмотрения, дней (чат)")
        st.bar_chart(df.dropna(subset=["Медиана рассмотрения, дн."]).set_index("Страна")["Медиана рассмотрения, дн."],
                     horizontal=True)
    st.subheader("Сводная таблица")
    st.dataframe(df, hide_index=True, width="stretch")

    st.subheader("Кейсы из чата")
    f1, f2 = st.columns(2)
    sel_c = f1.selectbox("Страна", ["Все"] + sorted(cases.country.unique()), format_func=lambda c: COUNTRY_RU.get(c, c))
    sel_o = f2.selectbox("Решение", ["Все", "approved", "refused"])
    view = cases if sel_c == "Все" else cases[cases.country == sel_c]
    view = view if sel_o == "Все" else view[view.outcome == sel_o]
    st.dataframe(view[["posted", "country", "city", "outcome", "submitted", "processing_days", "source", "excerpt"]],
                 hide_index=True, width="stretch",
                 column_config={"source": st.column_config.LinkColumn("Сообщение")})

# ------------------------------------------------------------------ чат
with tab_chat:
    st.caption(f"Провайдер: **{cfg['provider']}** ({cfg['models'][cfg['provider']]}) — меняется в config.yaml")
    with st.sidebar:
        st.subheader("Отладка: подмена сбоев")
        fault = st.selectbox("Сбой для следующего вопроса", ["нет", "get_country_metrics: timeout ×1",
                                                              "get_country_metrics: timeout ×2"])
    if "agent" not in st.session_state:
        st.session_state.trace = []
        st.session_state.agent = Agent(cfg, Session(user_id="web_user", today=date.today()),
                                       trace=lambda *a: st.session_state.trace.append(a))
        st.session_state.history, st.session_state.pending = [], None
    agent = st.session_state.agent

    for role, text in st.session_state.history:
        st.chat_message(role).write(text)

    def handle(fn):
        try:
            ans = fn()
            st.session_state.pending = None
            st.session_state.history.append(("assistant", ans))
        except PendingConfirmation as p:
            st.session_state.pending = p.card
        st.rerun()

    if st.session_state.pending:
        card = st.session_state.pending
        with st.chat_message("assistant"):
            st.warning(f"**Подтвердите добавление в календарь** — {card['country']}, вылет {card['trip_start']} "
                       f"({card['basis']}: {card['processing_median_days']} дн.)")
            st.table(pd.DataFrame(card["events"]).rename(columns={"date": "Дата", "title": "Событие"}))
            b1, b2 = st.columns(2)
            if b1.button("✅ Добавить", width="stretch"):
                handle(lambda: agent.resume(True))
            if b2.button("✖ Отмена", width="stretch"):
                handle(lambda: agent.resume(False))

    if q := st.chat_input("Например: лечу в Испанию 2027-03-20, когда подавать?", disabled=bool(st.session_state.pending)):
        tools.FAULTS.clear()
        if fault != "нет":
            tools.FAULTS["get_country_metrics"] = ["timeout"] * (1 if "×1" in fault else 2)
        st.session_state.history.append(("user", q))
        handle(lambda: agent.ask(q))

    with st.expander("Трасса агента (шаги, вызовы, ошибки)"):
        for t in st.session_state.trace[-30:]:
            st.code(json.dumps(t, ensure_ascii=False, default=str)[:600])
