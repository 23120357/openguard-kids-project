import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./data/server.db"
    cookie_secure: bool = False
    policy_signing_key: str = ""
    data_encryption_key: str = ""
    admin_enabled: bool = False
    allow_insecure_http: bool = False

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(
            database_url=os.getenv("OGK_DATABASE_URL", "sqlite:///./data/server.db"),
            cookie_secure=os.getenv("OGK_COOKIE_SECURE", "false").lower() == "true",
            policy_signing_key=os.getenv("OGK_POLICY_SIGNING_KEY", ""),
            data_encryption_key=os.getenv("OGK_DATA_ENCRYPTION_KEY", ""),
            admin_enabled=os.getenv("OGK_ADMIN_ENABLED", "false").lower() == "true",
            allow_insecure_http=os.getenv("OGK_ALLOW_INSECURE_HTTP", "false").lower() == "true",
        )
