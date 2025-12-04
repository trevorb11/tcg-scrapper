"""
Configuration Management
========================

Centralized configuration for the Industry Deep Scan engine.
All settings can be overridden via environment variables.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database connection settings."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    driver: Literal["postgresql", "sqlite"] = "sqlite"
    host: str = "localhost"
    port: int = 5432
    name: str = "industry_deep_scan"
    user: str = "postgres"
    password: SecretStr = SecretStr("")

    # SQLite path (used when driver=sqlite)
    sqlite_path: str = "data/deep_scan.db"

    # Connection pool settings
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30

    @property
    def url(self) -> str:
        """Build database URL based on driver."""
        if self.driver == "sqlite":
            return f"sqlite+aiosqlite:///{self.sqlite_path}"
        password = self.password.get_secret_value()
        return f"postgresql+asyncpg://{self.user}:{password}@{self.host}:{self.port}/{self.name}"


class LLMSettings(BaseSettings):
    """LLM provider settings for signal classification."""

    model_config = SettingsConfigDict(env_prefix="LLM_")

    # Primary provider (openai or anthropic)
    provider: Literal["openai", "anthropic"] = "openai"

    # API keys
    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")

    # Model selection
    openai_model: str = "gpt-4-turbo-preview"
    anthropic_model: str = "claude-3-opus-20240229"

    # Rate limiting
    requests_per_minute: int = 60
    max_tokens: int = 4096

    # Cost control
    max_cost_per_day: float = 50.0  # USD
    cache_responses: bool = True


class ScrapingSettings(BaseSettings):
    """Web scraping configuration."""

    model_config = SettingsConfigDict(env_prefix="SCRAPE_")

    # Request settings
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 2.0

    # Rate limiting per domain
    requests_per_second: float = 0.5  # Conservative default
    concurrent_requests: int = 5

    # User agent rotation
    rotate_user_agents: bool = True

    # Proxy settings (for production use)
    proxy_enabled: bool = False
    proxy_url: str = ""
    proxy_rotation: bool = True

    # Playwright settings for JavaScript-heavy sites
    use_playwright: bool = True
    headless: bool = True

    # Geographic targeting
    target_states: list[str] = Field(
        default_factory=lambda: [
            "CA", "TX", "FL", "NY", "IL", "PA", "OH", "GA", "NC", "MI",
            "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MD", "MO", "WI"
        ]
    )
    target_cities: list[str] = Field(default_factory=list)


class SourceSettings(BaseSettings):
    """Individual source configurations."""

    model_config = SettingsConfigDict(env_prefix="SOURCE_")

    # Yelp API (official API - requires business account)
    yelp_api_key: SecretStr = SecretStr("")
    yelp_enabled: bool = True

    # Google News RSS (free)
    google_news_enabled: bool = True

    # LinkedIn (requires Sales Navigator API or manual import)
    linkedin_enabled: bool = False
    linkedin_cookie: SecretStr = SecretStr("")

    # Better Business Bureau
    bbb_enabled: bool = True

    # Business-for-sale listings
    bizbuysell_enabled: bool = True
    businessbroker_enabled: bool = True

    # Court records / liens
    court_records_enabled: bool = True

    # State equipment permits
    equipment_permits_enabled: bool = True

    # Secretary of State filings
    sos_filings_enabled: bool = True


class NotificationSettings(BaseSettings):
    """Notification configuration."""

    model_config = SettingsConfigDict(env_prefix="NOTIFY_")

    # Slack integration
    slack_enabled: bool = False
    slack_webhook_url: SecretStr = SecretStr("")
    slack_channel: str = "#mca-leads"

    # Email notifications (via SendGrid)
    email_enabled: bool = False
    sendgrid_api_key: SecretStr = SecretStr("")
    email_from: str = "alerts@yourbrokerage.com"
    email_recipients: list[str] = Field(default_factory=list)

    # Webhook (for CRM integration)
    webhook_enabled: bool = False
    webhook_url: str = ""
    webhook_secret: SecretStr = SecretStr("")

    # Alert thresholds
    min_priority_for_instant_alert: int = 8  # 1-10 scale
    daily_digest_enabled: bool = True
    daily_digest_hour: int = 8  # 8 AM


class SchedulerSettings(BaseSettings):
    """Job scheduling configuration."""

    model_config = SettingsConfigDict(env_prefix="SCHEDULER_")

    # Scan frequency (in minutes)
    news_scan_interval: int = 30
    review_scan_interval: int = 120
    linkedin_scan_interval: int = 240
    bbb_scan_interval: int = 360
    liens_scan_interval: int = 720
    permits_scan_interval: int = 720
    listings_scan_interval: int = 60

    # Full database refresh (hours)
    full_refresh_interval: int = 24

    # Celery settings (for production)
    celery_broker: str = "redis://localhost:6379/0"
    celery_backend: str = "redis://localhost:6379/1"


class APISettings(BaseSettings):
    """REST API configuration."""

    model_config = SettingsConfigDict(env_prefix="API_")

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Authentication
    api_key_enabled: bool = True
    api_keys: list[str] = Field(default_factory=list)

    # CORS
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # Rate limiting
    rate_limit_per_minute: int = 100


class ScoringSettings(BaseSettings):
    """Lead scoring configuration."""

    model_config = SettingsConfigDict(env_prefix="SCORING_")

    # Signal weights (1-10 scale)
    weight_cash_squeeze: float = 9.0
    weight_rapid_growth: float = 8.0
    weight_distress: float = 7.0
    weight_expansion: float = 6.0
    weight_new_contract: float = 7.0

    # Industry multipliers
    high_value_industries: list[str] = Field(
        default_factory=lambda: [
            "construction",
            "trucking",
            "restaurants",
            "medical",
            "manufacturing",
            "auto repair",
            "retail",
            "landscaping",
            "hvac",
            "plumbing",
            "electrical",
        ]
    )
    industry_multiplier: float = 1.5

    # Revenue indicators
    min_estimated_revenue: int = 100000  # $100K minimum
    ideal_revenue_range: tuple[int, int] = (250000, 5000000)  # $250K - $5M sweet spot


class Settings(BaseSettings):
    """Master settings aggregator."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    # Component settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    scraping: ScrapingSettings = Field(default_factory=ScrapingSettings)
    sources: SourceSettings = Field(default_factory=SourceSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    api: APISettings = Field(default_factory=APISettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
