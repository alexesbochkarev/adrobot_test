from pydantic import HttpUrl, PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Adrobot API"
    database_url: str = "sqlite:///./adrobot.db"
    keitaro_base_url: HttpUrl | None = None
    keitaro_api_key: SecretStr | None = None
    keitaro_domain_id: PositiveInt | None = None
    keitaro_group_id: PositiveInt | None = None
    keitaro_traffic_source_id: PositiveInt | None = None

    @field_validator("keitaro_base_url")
    @classmethod
    def validate_keitaro_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value and (
            value.scheme != "https"
            or value.username
            or value.password
            or value.query
            or value.fragment
            or value.path not in (None, "/")
        ):
            raise ValueError("Use an HTTPS origin without credentials, path, query or fragment")
        return value
