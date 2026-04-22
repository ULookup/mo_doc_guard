"""Runtime settings loaded from environment variables."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import yaml

from app.connectors.model_router import ModelRouter


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str
    runs_dir: Path
    matrixone_repo_dir: Path
    docs_repo_dir: Path
    path_mapping_file: Path
    agents_config_path: Path
    models_config_path: Path
    prompts_config_path: Path
    quality_gates_config_path: Path
    matrixone_repo: str
    matrixorigin_docs_repo: str
    openai_api_key: str
    anthropic_api_key: str
    docs_repo_token: str
    model_router: ModelRouter


def _env_or_default(key: str, default: str) -> str:
    value = os.getenv(key)
    if value is None or value.strip() == "":
        return default
    return value


def _load_dotenv_if_present() -> None:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    dotenv_path = Path(".env")
    if not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        env_key = key.strip()
        if not env_key:
            continue
        env_value = value.strip().strip('"').strip("'")
        os.environ.setdefault(env_key, env_value)


def load_settings() -> Settings:
    _load_dotenv_if_present()
    app_env = _env_or_default("APP_ENV", "dev")
    matrixone_repo = _env_or_default("MATRIXONE_REPO", "")
    matrixorigin_docs_repo = _env_or_default("MATRIXORIGIN_DOCS_REPO", "")
    matrixone_repo_dir = _env_or_default("MATRIXONE_REPO_DIR", "./repos/matrixone")
    docs_repo_dir = _env_or_default("DOCS_REPO_DIR", "./repos/matrixorigin.io")
    path_mapping_file = _env_or_default("PATH_MAPPING_FILE", "./configs/path_mapping.yaml")
    agents_config_path = _env_or_default("AGENTS_CONFIG_PATH", "./configs/agents.yaml")
    models_config_path = _env_or_default("MODELS_CONFIG_PATH", "./configs/models.yaml")
    prompts_config_path = _env_or_default("PROMPTS_CONFIG_PATH", "./configs/prompts.yaml")
    quality_gates_config_path = _env_or_default("QUALITY_GATES_CONFIG_PATH", "./configs/quality_gates.yaml")
    openai_api_key = _env_or_default("OPENAI_API_KEY", "")
    anthropic_api_key = _env_or_default("ANTHROPIC_API_KEY", "")
    docs_repo_token = _env_or_default("DOCS_REPO_TOKEN", "")

    if app_env != "dev" and (not matrixone_repo or not matrixorigin_docs_repo):
        raise ValueError("MATRIXONE_REPO and MATRIXORIGIN_DOCS_REPO are required in non-dev mode")
    if app_env != "dev":
        _validate_non_dev_runtime(
            agents_config_path=Path(agents_config_path).resolve(),
            models_config_path=Path(models_config_path).resolve(),
        )

    return Settings(
        app_env=app_env,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        runs_dir=Path(os.getenv("RUNS_DIR", "./runs")).resolve(),
        matrixone_repo_dir=Path(matrixone_repo_dir).resolve(),
        docs_repo_dir=Path(docs_repo_dir).resolve(),
        path_mapping_file=Path(path_mapping_file).resolve(),
        agents_config_path=Path(agents_config_path).resolve(),
        models_config_path=Path(models_config_path).resolve(),
        prompts_config_path=Path(prompts_config_path).resolve(),
        quality_gates_config_path=Path(quality_gates_config_path).resolve(),
        matrixone_repo=matrixone_repo,
        matrixorigin_docs_repo=matrixorigin_docs_repo,
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        docs_repo_token=docs_repo_token,
        model_router=ModelRouter(Path(models_config_path).resolve()),
    )


def _validate_non_dev_runtime(*, agents_config_path: Path, models_config_path: Path) -> None:
    agents_cfg = _load_yaml_mapping(agents_config_path)
    models_cfg = _load_yaml_mapping(models_config_path)

    defaults = agents_cfg.get("defaults", {})
    plugins = agents_cfg.get("plugins", {})
    author_plugin_id = str(defaults.get("author_plugin", "")).strip()
    reviewer_plugin_id = str(defaults.get("reviewer_plugin", "")).strip()

    if _is_mcp_plugin(author_plugin_id, plugins):
        endpoint = _resolve_plugin_endpoint(
            plugin_id=author_plugin_id,
            plugins=plugins,
            env_key="MCP_AUTHOR_ENDPOINT",
        )
        if not endpoint:
            raise ValueError("MCP_AUTHOR_ENDPOINT is required when author plugin is mcp_author")
    if _is_mcp_plugin(reviewer_plugin_id, plugins):
        endpoint = _resolve_plugin_endpoint(
            plugin_id=reviewer_plugin_id,
            plugins=plugins,
            env_key="MCP_REVIEWER_ENDPOINT",
        )
        if not endpoint:
            raise ValueError("MCP_REVIEWER_ENDPOINT is required when reviewer plugin is mcp_reviewer")

    default_model = models_cfg.get("default", {})
    roles = models_cfg.get("roles", {})
    for role in ("author", "reviewer"):
        merged = {**default_model, **(roles.get(role, {}) if isinstance(roles.get(role, {}), dict) else {})}
        if not str(merged.get("provider", "")).strip() or not str(merged.get("model", "")).strip():
            raise ValueError(f"models config missing provider/model for role: {role}")


def _is_mcp_plugin(plugin_id: str, plugins: dict[str, Any]) -> bool:
    plugin_cfg = plugins.get(plugin_id, {}) if isinstance(plugins, dict) else {}
    if not isinstance(plugin_cfg, dict):
        return False
    return str(plugin_cfg.get("type", "")).strip().startswith("mcp_")


def _resolve_plugin_endpoint(*, plugin_id: str, plugins: dict[str, Any], env_key: str) -> str:
    plugin_cfg = plugins.get(plugin_id, {}) if isinstance(plugins, dict) else {}
    if not isinstance(plugin_cfg, dict):
        plugin_cfg = {}
    return str(plugin_cfg.get("endpoint", "")).strip() or os.getenv(env_key, "").strip()


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        return {}
    return data
