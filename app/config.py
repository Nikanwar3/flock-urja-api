"""Runtime configuration.

Everything here can be overridden with environment variables (or a `.env`
file — see `.env.example`). Nothing here talks to the portal; it's just
values other modules read.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="URJA_", extra="ignore")

    # Credentials for the *single* portal account this service uses to talk
    # to Urja Meter Ops. There is only one login for the whole utility desk,
    # so this is a service-level secret, not a per-caller one — see README
    # "Assumptions" for why the API itself doesn't ask callers to authenticate.
    portal_base_url: str = "https://urja-ops.flockenergy.tech"
    portal_email: str = "operator@urja.local"
    portal_password: str = "urja-ops-2026"

    # How long we trust our own in-memory copy of portal data before
    # refetching. The bulk export is cheap (one request) so we default to a
    # short TTL; per-meter energy readings are fetched lazily and cached a
    # bit longer since a 30-min-interval feed doesn't change within seconds.
    meters_cache_ttl_seconds: int = 300
    transformers_cache_ttl_seconds: int = 300
    energy_cache_ttl_seconds: int = 120

    # Safety margin subtracted from the portal's session lifetime so we
    # re-login slightly *before* the cookie actually expires rather than
    # racing it.
    session_refresh_margin_seconds: int = 60

    request_timeout_seconds: float = 15.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
