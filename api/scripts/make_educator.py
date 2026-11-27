"""Gives a user the educator role (SPEC 9.9), or takes it away with --learner.

Run from api/:  .venv/bin/python scripts/make_educator.py <email> [--learner]
(Windows: .\\.venv\\Scripts\\python.exe scripts\\make_educator.py <email>)
"""
import argparse
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402


def set_role(db, email: str, role: str) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise LookupError(f"no user with email {email!r}")
    user.role = role
    db.commit()
    return user


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    parser.add_argument("--learner", action="store_true", help="remove the educator role")
    args = parser.parse_args()
    with SessionLocal() as db:
        try:
            user = set_role(db, args.email, "learner" if args.learner else "educator")
        except LookupError as exc:
            print(exc, file=sys.stderr)
            return 1
    print(f"{user.email} is now {user.role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
