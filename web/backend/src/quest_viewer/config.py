from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIEWER_", env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://quest:quest@127.0.0.1:5432/quest_viewer"
    frontend_dir: Path = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    pool_size: int = 5
