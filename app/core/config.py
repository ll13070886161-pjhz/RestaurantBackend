import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv


load_dotenv()


def _normalize_llm_base_url(raw_url: str) -> str:
    url = (raw_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/api/v3"):
        return f"{url}/chat/completions"
    return url


def _compose_db_url_from_parts() -> str:
    db_type = (os.getenv("DB_TYPE", "") or "").strip().lower()
    if db_type != "mysql":
        return ""

    host = (os.getenv("DB_HOST", "") or "").strip()
    port = (os.getenv("DB_PORT", "3306") or "3306").strip()
    user = (os.getenv("DB_USER", "") or "").strip()
    password = os.getenv("DB_PASS", "") or ""
    name = (os.getenv("DB_NAME", "") or "").strip()
    params = (os.getenv("DB_PARAMS", "charset=utf8mb4") or "charset=utf8mb4").strip()
    if not all([host, user, name]):
        return ""

    user_enc = quote_plus(user)
    pass_enc = quote_plus(password)
    auth = f"{user_enc}:{pass_enc}"
    return f"mysql+pymysql://{auth}@{host}:{port}/{name}?{params}"


class Settings:
    app_name: str = "Image2Excel"
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "temp_uploads"))
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", "outputs"))
    llm_timeout: int = int(os.getenv("LLM_TIMEOUT", "45"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    llm_provider_name: str = os.getenv("LLM_PROVIDER_NAME", "volcengine")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model_name: str = os.getenv("LLM_MODEL_NAME", os.getenv("DOUBAO_ENDPOINT_ID", "doubao-1.5-thinking-vision-pro"))
    llm_base_url: str = _normalize_llm_base_url(
        os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
    )
    db_url: str = os.getenv("DB_URL", "").strip() or _compose_db_url_from_parts() or "sqlite:///./app.db"
    write_allowed_ips: set[str] = {
        ip.strip()
        for ip in os.getenv("WRITE_ALLOWED_IPS", "127.0.0.1,::1,localhost").split(",")
        if ip.strip()
    }
    inventory_alert_popup_enabled: bool = (os.getenv("INVENTORY_ALERT_POPUP_ENABLED", "true").strip().lower() == "true")
    inventory_alert_openclaw_enabled: bool = (
        os.getenv("INVENTORY_ALERT_OPENCLAW_ENABLED", "false").strip().lower() == "true"
    )
    inventory_alert_openclaw_webhook_url: str = os.getenv("INVENTORY_ALERT_OPENCLAW_WEBHOOK_URL", "").strip()
    inventory_alert_feishu_webhook_url: str = os.getenv("INVENTORY_ALERT_FEISHU_WEBHOOK_URL", "").strip()

    def ensure_dirs(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
