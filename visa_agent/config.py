import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (без зависимостей): KEY=VALUE в окружение, если ещё не задано."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path: str | None = None) -> dict:
    _load_dotenv(ROOT / ".env")
    cfg = yaml.safe_load(Path(path or ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["provider"] = os.environ.get("VISA_AGENT_PROVIDER", cfg["provider"])  # удобно для демо
    for k, v in cfg["data"].items():
        cfg["data"][k] = str(ROOT / v)
    return cfg
