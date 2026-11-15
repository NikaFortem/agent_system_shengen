"""Сценарии для демо (3 минуты): обычный сценарий, действие с подтверждением, ошибка инструмента.

python demo.py            — с провайдером из config.yaml
VISA_AGENT_PROVIDER=mock python demo.py   — без сети и ключей
"""
from cli import confirm_cli, trace
from visa_agent import tools
from visa_agent.agent import Agent
from visa_agent.config import load_config
from visa_agent.tools import Session


def run(title, q, confirm=confirm_cli, fault=None):
    print(f"\n=== {title} ===\nВы: {q}")
    tools.FAULTS.clear()
    if fault:
        tools.FAULTS.update(fault)
        print(f"  (подменяем ответ сервиса: {fault})")
    agent = Agent(load_config(), Session(user_id="demo_user"), trace=trace)
    print("Агент:", agent.ask(q, confirm=confirm))


if __name__ == "__main__":
    run("1. Обычный сценарий", "Сколько сейчас рассматривают визу в Италию в Москве?")
    run("2. Похожие кейсы", "Покажи кейсы отказов по Италии")
    run("3. Действие с подтверждением", "Лечу в Испанию 2027-03-20, когда подавать? Добавь в календарь")
    run("4. Ошибка инструмента: таймаут дважды", "Какие сроки по Франции?",
        fault={"get_country_metrics": ["timeout", "timeout"]})
    run("5. Ошибка инструмента: таймаут один раз → повтор", "Какие сроки по Франции?",
        fault={"get_country_metrics": ["timeout"]})
    run("6. Бизнес-правило: не успеть", "Лечу в Италию 2026-12-10, когда подавать?")
