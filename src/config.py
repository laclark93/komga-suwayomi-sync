from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Komga connection
    komga_base_url: str
    komga_username: str = ""
    komga_password: str = ""
    komga_api_key: str = ""

    # Suwayomi connection
    suwayomi_base_url: str
    suwayomi_username: str = ""
    suwayomi_password: str = ""

    # Sync behavior
    initial_sync_on_start: bool = True
    polling_interval_seconds: int = 300
    sse_reconnect_delay_seconds: int = 5
    sse_reconnect_max_delay_seconds: int = 60

    # Matching
    match_threshold: float = 0.85

    # Cache
    cache_ttl_seconds: int = 3600

    # Health check
    health_port: int = 8080

    # Logging
    log_level: str = "INFO"
