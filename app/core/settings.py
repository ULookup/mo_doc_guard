"""Runtime settings loaded from environment variables."""

from dataclasses import dataclass
import os
from pathlib import Path

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


def load_settings() -> Settings:
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
