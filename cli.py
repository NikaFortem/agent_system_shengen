"""Консольный чат с агентом.  python cli.py  [--fault get_country_metrics:timeout]"""
import argparse
import json

from visa_agent import tools
from visa_agent.agent import Agent
from visa_agent.config import load_config
from visa_agent.tools import Session


def trace(kind, *a):
    if kind == "model":
        for c in a[1]:
            print(f"  [шаг {a[0]}] модель → {c['name']}({json.dumps(c['arguments'], ensure_ascii=False)})")
    elif kind == "retry":
        print(f"  [harness] {a[0]} → {a[1]}, повторяю вызов сам (чтение можно повторить)")
    elif kind == "tool":
        r = a[2]
        short = f"ошибка {r['error']['type']}: {r['error']['message']}" if "error" in r else "ok"
        print(f"  [harness] {a[0]} → {short}")


def confirm_cli(name, card):
    print("\n┌─ ПОДТВЕРЖДЕНИЕ ─────────────────────────────")
    print(f"│ {card['country']}, вылет {card['trip_start']} ({card['basis']}: {card['processing_median_days']} дн.)")
    for e in card["events"]:
        print(f"│  {e['date']}  {e['title']}")
    print("└─────────────────────────────────────────────")
    return input("Добавить эти события в календарь? [y/N] ").strip().lower() in ("y", "д", "да", "yes")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fault", help="подменить ответ сервиса, например get_country_metrics:timeout")
    a = p.parse_args()
    if a.fault:
        name, kind = a.fault.split(":")
        tools.FAULTS[name] = [kind] * 5
    cfg = load_config()
    agent = Agent(cfg, Session(user_id="demo_user"), trace=trace)
    print(f"Провайдер: {cfg['provider']} ({cfg['models'][cfg['provider']]}). Пустая строка — выход.")
    while True:
        q = input("\nВы: ").strip()
        if not q:
            break
        print("Агент:", agent.ask(q, confirm=confirm_cli))


if __name__ == "__main__":
    main()
