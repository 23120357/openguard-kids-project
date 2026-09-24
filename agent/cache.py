import json
import sqlite3
from pathlib import Path


class PolicyCache:
    """Cache only non-secret configuration. Device tokens remain in memory."""

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def load(self):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT value FROM cache WHERE key = 'policy'").fetchone()
            return json.loads(row[0]) if row else None

    def save(self, policy):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT INTO cache(key, value) VALUES ('policy', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (json.dumps(policy),),
            )
