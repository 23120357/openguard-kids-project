import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./data/server.db"
    cookie_secure: bool = False
    policy_signing_key: str = "development-only-policy-signing-key-change-me"

    @classmethod
    def from_env(cls):
        load_dotenv()
        return cls(
            database_url=os.getenv("OGK_DATABASE_URL", "sqlite:///./data/server.db"),
            cookie_secure=os.getenv("OGK_COOKIE_SECURE", "false").lower() == "true",
            policy_signing_key=os.getenv(
                "OGK_POLICY_SIGNING_KEY",
                "development-only-policy-signing-key-change-me",
            ),
        )
