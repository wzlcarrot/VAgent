"""
全局配置 —— 全部用环境变量覆盖，避免代码里散落 magic numbers
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional

try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
    elif os.path.exists(".env"):
        load_dotenv(".env")
except ImportError:
    pass


class Settings(BaseSettings):
    app_name: str = "ViewHub AI Agent"
    debug: bool = False

    # ─── 数据库 ───
    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_user: str = "postgres"
    pg_password: str = ""
    pg_database: str = "viewhub"
    db_pool_size: int = 20
    db_health_check_interval: float = 30.0

    # ─── LLM ───
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.chat/v1"
    minimax_model: str = "MiniMax-Text-01"
    llm_provider: str = "deepseek"
    router_llm_provider: str = "deepseek"
    llm_timeout: int = 30

    # ─── LLM Retry ───
    llm_retry_max_attempts: int = 3
    llm_retry_base_delay: float = 1.0
    llm_retry_max_delay: float = 8.0

    # ─── Redis ───
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_cooldown_seconds: float = 5.0

    # ─── Video service ───
    video_service_url: str = "http://127.0.0.1:7071"
    # 给前端浏览器访问的 cover URL 前缀（应公网可访问）。
    # 默认等于 video_service_url；生产部署到独立域名时通过环境变量覆盖。
    public_video_url: str = ""

    # ─── CORS ───
    cors_origins: str = "http://localhost:4000,http://127.0.0.1:4000,http://localhost:4091,http://127.0.0.1:4091"

    # ─── Context 三层隔离 ───
    context_max_rounds: int = 5
    context_summary_ttl: int = 3600
    context_ttl: int = 7200
    compact_token_threshold: int = 3000
    compact_cooldown_seconds: int = 300

    # ─── Auth ───
    token_ttl_seconds: int = 7 * 24 * 3600
    # 登录 cookie 是否要求 HTTPS（生产环境设 True；本地 http 开发保持 False）
    cookie_secure: bool = False

    # ─── 测试账户（从环境变量读取，避免硬编码） ───
    test_account_enabled: bool = False
    test_account_email: str = ""
    test_account_password_md5: str = ""
    test_account_user_id: str = ""
    test_account_nickname: str = ""
    test_account_avatar: str = ""

    # ─── Embedding ───
    embed_model_name: str = "BAAI/bge-base-zh-v1.5"
    embed_cache_max: int = 5000
    embed_cache_ttl: int = 86400

    # ─── Harness ───
    harness_enabled: bool = True

    # 同步 workflow 执行的线程池并发数（每请求并行 2 路 workflow，建议 ≥ 4 的倍数）
    agent_async_max_workers: int = 8

    # ─── Admin ───
    # 运营看板的访问控制：简单 API Key（生产建议改 OIDC/JWT）
    # 必须通过环境变量 ADMIN_API_KEY 配置，未配置时 /admin/* 拒绝访问（fail-closed）
    admin_api_key: str = ""

    # ─── Input limits ───
    max_question_length: int = 2000
    max_image_urls: int = 4

    @field_validator("pg_port")
    @classmethod
    def validate_pg_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"Invalid pg_port: {v}, must be 1-65535")
        return v

    @field_validator("redis_port")
    @classmethod
    def validate_redis_port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError(f"Invalid redis_port: {v}, must be 1-65535")
        return v

    @field_validator("llm_timeout")
    @classmethod
    def validate_llm_timeout(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"Invalid llm_timeout: {v}, must be >= 1")
        return v

    @field_validator("context_max_rounds")
    @classmethod
    def validate_context_max_rounds(cls, v: int) -> int:
        if v < 1 or v > 50:
            raise ValueError(f"Invalid context_max_rounds: {v}, must be 1-50")
        return v

    @field_validator("max_question_length")
    @classmethod
    def validate_max_question_length(cls, v: int) -> int:
        if v < 10 or v > 10000:
            raise ValueError(f"Invalid max_question_length: {v}, must be 10-10000")
        return v

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def cors_origins_list(self) -> list:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def test_account(self) -> Optional[dict]:
        """获取测试账户配置，未启用时返回 None"""
        if not self.test_account_enabled or not self.test_account_email:
            return None
        return {
            "email": self.test_account_email,
            "password_md5": self.test_account_password_md5,
            "user_id": self.test_account_user_id,
            "nick_name": self.test_account_nickname,
            "avatar": self.test_account_avatar,
        }

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        extra="ignore"
    )


def build_cover_url(cover_path: str) -> str:
    if not cover_path:
        return ""
    if cover_path.startswith("http"):
        return cover_path
    base = (settings.public_video_url or settings.video_service_url).rstrip("/")
    return f"{base}/api/file/getResource?sourceName={cover_path}"


settings = Settings()
