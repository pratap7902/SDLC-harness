#!/usr/bin/env python3
"""Integration jobs against the configured DB.

    make sync-people     # Teams users → people directory (merge by email; review list)
    make notify          # send due Teams notifications (run every minute from cron)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402,F401
from app.core.database import SessionLocalPrimary  # noqa: E402
from app.exceptions import BaseAppException  # noqa: E402


def main(argv) -> int:
    if not argv or argv[0] not in ("sync-people", "notify"):
        print(__doc__)
        return 2
    db = SessionLocalPrimary()
    try:
        if argv[0] == "sync-people":
            from app.teams.services.directory_sync import sync_teams_people

            out = sync_teams_people(db).to_dict()
        else:
            from app.teams.services.notifications import Notifier

            out = Notifier(db).run()
        print(json.dumps(out, indent=1))
        return 0
    except BaseAppException as e:
        print(e.message, file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
