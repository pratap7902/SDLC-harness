from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE = f"sqlite+pysqlite:///{ROOT / 'var' / 'dev.db'}"


class MySQLConfig(BaseSettings):
    """MySQL (docker-compose `db`, port 3311). Used only when DB_MYSQL_HOST is set and
    DATABASE_URL is not."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = Field(default="", validation_alias="DB_MYSQL_HOST")
    port: int = Field(default=3311, validation_alias="DB_MYSQL_PORT")
    user: str = Field(default="root", validation_alias="DB_MYSQL_USER")
    password: str = Field(default="srs", validation_alias="DB_MYSQL_PASSWORD")
    db: str = Field(default="srs", validation_alias="DB_MYSQL_DB")

    def url(self) -> str:
        return (
            f"mysql+mysqlconnector://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )


class DatabaseSettings(BaseSettings):
    """`DATABASE_URL` wins; else MySQL from DB_MYSQL_*; else the SQLite file var/dev.db."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = Field(default="", validation_alias="DATABASE_URL")
    mysql: MySQLConfig = Field(default_factory=MySQLConfig)

    def url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        if self.mysql.host:
            return self.mysql.url()
        return DEFAULT_SQLITE


db_settings = DatabaseSettings()
