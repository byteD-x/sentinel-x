"""应用配置 — 从环境变量加载，所有敏感值默认为空。"""

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Sentinel-X Control API 配置。"""

    # 运行环境
    sentinel_profile: str = "light"
    sentinel_environment: str = "local-demo"
    sentinel_log_level: str = "INFO"
    sentinel_actions_enabled: bool = False
    sentinel_kill_switch: bool = True

    # 服务端点
    control_api_host: str = "127.0.0.1"
    control_api_port: int = 8000

    # 数据库
    database_url: str = ""

    # Temporal
    temporal_address: str = "127.0.0.1:7233"
    temporal_namespace: str = "sentinel-local"

    # 可观测性
    otel_exporter_otlp_endpoint: str = "http://127.0.0.1:4317"

    # LLM
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # 安全
    action_gateway_url: str = ""
    action_gateway_audience: str = "sentinel-action-gateway"
    local_session_signing_key: str = ""
    alert_ingress_hmac_key: str = ""

    # 调查预算
    investigation_max_seconds: int = 480
    investigation_max_llm_calls: int = 8
    investigation_max_tool_calls: int = 20

    @model_validator(mode="after")
    def validate_profile_requirements(self) -> "Settings":
        if self.sentinel_profile not in {"light", "full"}:
            raise ValueError("SENTINEL_PROFILE 必须是 light 或 full")
        if self.sentinel_profile == "full":
            missing = [
                name
                for name, value in {
                    "DATABASE_URL": self.database_url,
                    "LOCAL_SESSION_SIGNING_KEY": self.local_session_signing_key,
                    "ACTION_GATEWAY_URL": self.action_gateway_url,
                    "ALERT_INGRESS_HMAC_KEY": self.alert_ingress_hmac_key,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(f"full profile 缺少必填配置: {', '.join(missing)}")
            if not self.database_url.startswith(("postgresql://", "postgresql+")):
                raise ValueError("full profile 的 DATABASE_URL 必须指向 PostgreSQL")
        return self

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # 配置字典由多个服务共享；Control API 忽略属于其他服务的变量。
        "extra": "ignore",
    }


settings = Settings()
