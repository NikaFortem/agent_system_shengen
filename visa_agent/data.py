"""Хранилище данных: кейсы из Telegram-чата и статистика Еврокомиссии.

Это «сервис» за инструментами. Инструменты не отдают модели сырые данные,
а только отфильтрованный и урезанный результат.
"""
import csv
import json
import statistics
from datetime import date, timedelta

COUNTRY_NAMES = {
    "IT": "Italy", "ES": "Spain", "FR": "France", "GR": "Greece", "HU": "Hungary",
    "DE": "Germany", "BG": "Bulgaria", "NL": "Netherlands", "CH": "Switzerland",
    "CY": "Cyprus", "FI": "Finland",
}
COUNTRY_RU = {
    "IT": "Италия", "ES": "Испания", "FR": "Франция", "GR": "Греция", "HU": "Венгрия",
    "DE": "Германия", "BG": "Болгария", "NL": "Нидерланды", "CH": "Швейцария",
    "CY": "Кипр", "FI": "Финляндия",
}
CITY_EC = {"Москва": "MOSCOW", "Санкт-Петербург": "ST. PETERSBURG", "Екатеринбург": "YEKATERINBURG",
           "Казань": "KAZAN", "Новороссийск": "NOVOROSSIYSK", "Калининград": "KALININGRAD"}


class VisaStore:
    def __init__(self, cases_path: str, ec_path: str):
        self.cases = json.load(open(cases_path, encoding="utf-8"))
        with open(ec_path, encoding="utf-8") as f:
            self.ec = list(csv.DictReader(f))

    # --- кейсы из чата -------------------------------------------------
    def find_cases(self, country, city=None, outcome=None, date_from=None, date_to=None):
        res = []
        for c in self.cases:
            if c["country"] != country:
                continue
            if city and c["city"] != city:
                continue
            if outcome and c["outcome"] != outcome:
                continue
            if date_from and c["posted"] < date_from:
                continue
            if date_to and c["posted"] > date_to:
                continue
            res.append(c)
        return sorted(res, key=lambda c: c["posted"], reverse=True)

    def processing_stats(self, country, city=None, period_days=180, today=None):
        today = today or date.today()
        since = (today - timedelta(days=period_days)).isoformat()
        cases = [c for c in self.find_cases(country, city, date_from=since) if c["processing_days"]]
        days = sorted(c["processing_days"] for c in cases)
        if not days:
            return {"n": 0}
        q = statistics.quantiles(days, n=4) if len(days) >= 2 else [days[0]] * 3
        return {"n": len(days), "median": statistics.median(days), "p25": q[0], "p75": q[2],
                "refused_in_chat": sum(c["outcome"] == "refused" for c in cases)}

    # --- статистика Еврокомиссии ---------------------------------------
    def ec_stats(self, country, city=None):
        rows = [r for r in self.ec if r["schengen_state"] == COUNTRY_NAMES[country]
                and (not city or r["city"] == CITY_EC.get(city, "?"))]
        if not rows:
            return None
        app = sum(float(r["applications"]) for r in rows)
        iss = sum(float(r["issued"]) for r in rows)
        ref = sum(float(r["refused"]) for r in rows)
        mev = sum(float(r["multiple_entry_issued"]) for r in rows)
        return {"year": 2025, "applications": int(app), "refusal_rate_pct": round(100 * ref / app, 1),
                "multi_entry_share_pct": round(100 * mev / iss, 1) if iss else None}
