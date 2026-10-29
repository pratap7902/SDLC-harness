#!/usr/bin/env python3
"""Mint, list or revoke bearer tokens (actor_tokens) in the configured DB.

    make token ACTOR=runner-sdk KIND=agent ROLES=ci LABEL="sdk runner"
    .venv/bin/python scripts/mint_token.py mint --actor priya --kind human [--roles admin] [--days 90]
    .venv/bin/python scripts/mint_token.py list
    .venv/bin/python scripts/mint_token.py revoke 3

The token is printed once; only its sha256 is stored. Kinds: human | agent (never system).
"""

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402,F401
from app.auth.services.token_service import TokenService  # noqa: E402
from app.core.database import SessionLocalPrimary  # noqa: E402
from app.core.utils.time import utcnow  # noqa: E402
from app.exceptions import BaseAppException  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mint")
    m.add_argument("--actor", required=True, help="person handle or runner name")
    m.add_argument("--kind", required=True, choices=["human", "agent"])
    m.add_argument("--roles", default="", help="comma-separated service roles (admin, ci)")
    m.add_argument("--label", default="")
    m.add_argument("--days", type=int, default=0, help="expiry in days (0 = never)")
    sub.add_parser("list")
    r = sub.add_parser("revoke")
    r.add_argument("id", type=int)
    args = p.parse_args(argv)
    db = SessionLocalPrimary()
    try:
        tokens = TokenService(db)
        if args.cmd == "mint":
            expires = utcnow() + timedelta(days=args.days) if args.days else None
            token, row = tokens.mint(args.actor, args.kind, args.roles.split(","), args.label, expires)
            print(f"token {row.id} for {row.principal} ({row.kind}; roles: {', '.join(row.roles) or '—'})")
            print(token)
            print("Shown once. Send it as: Authorization: Bearer <token>", file=sys.stderr)
        elif args.cmd == "list":
            for row in tokens.list():
                state = "revoked" if row.revoked_at else ("expired" if row.expires_at and row.expires_at <= utcnow() else "live")
                print(f"{row.id}\t{row.prefix}…\t{row.principal}\t{row.kind}\t{','.join(row.roles or [])}\t{state}\t{row.label}")
        else:
            row = tokens.revoke(args.id)
            print(f"revoked token {row.id} ({row.principal})")
        return 0
    except BaseAppException as e:
        print(e.message, file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
