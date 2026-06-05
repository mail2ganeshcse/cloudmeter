from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://cloudmeter:cloudmeter@localhost:55432/cloudmeter"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    google_client_id: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    sso_client_id: str = ""
    sso_client_secret: str = ""
    sso_authorize_url: str = ""
    sso_token_url: str = ""
    sso_userinfo_url: str = ""
    session_cookie_name: str = "cloudmeter_session"
    session_ttl_days: int = 7
    session_cookie_secure: bool = False
    public_api_url: str = "http://localhost:8001"
    frontend_url: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
