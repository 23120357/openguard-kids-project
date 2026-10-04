"""Read-only diagnostics for the local F1 state database."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from agent.time_control import SQLiteTimeStore
from agent.windows_service import f1_data_paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", help="Override the F1 SQLite database path")
    parser.add_argument("--events", type=int, default=50, help="Recent event count")
    args = parser.parse_args()
    _, default_database = f1_data_paths()
    store = SQLiteTimeStore(args.database or default_database)
    print(
        json.dumps(
            {
                "state": asdict(store.load_state()),
                "events": store.recent_events(limit=max(1, min(args.events, 500))),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
