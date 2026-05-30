import json
import os
from pathlib import Path


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "model_config.json"


def load_config(path):
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Failed to read config {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise SystemExit(f"Config {path} must be a JSON object.")
    return data


def save_config(path, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


def first_value(*values):
    for value in values:
        if value:
            return value
    return None


def normalize_base_url(base_url):
    return base_url.rstrip("/")


def build_runtime_config(args):
    config_path = Path(args.config).expanduser()
    saved_config = load_config(config_path)

    base_url = first_value(args.base_url, os.getenv("OPENAI_BASE_URL"), saved_config.get("base_url"), DEFAULT_BASE_URL)
    api_key = first_value(args.api_key, os.getenv("OPENAI_API_KEY"), saved_config.get("api_key"))
    model = first_value(args.model, os.getenv("OPENAI_MODEL"), saved_config.get("model"))

    runtime = {
        "base_url": normalize_base_url(base_url),
        "api_key": api_key,
        "model": model,
    }

    missing = [key for key, value in runtime.items() if not value]
    if missing:
        raise SystemExit(
            "Missing required config: "
            + ", ".join(missing)
            + ". Edit model_config.json, pass command line flags, or set OPENAI_* env vars."
        )

    if args.save_config:
        save_config(config_path, runtime)
        print(f"Saved config to {config_path}")

    return runtime
