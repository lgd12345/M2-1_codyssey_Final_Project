"""Create a login account. There is no public sign-up; this is the only way to add users.

The password is read from a hidden prompt (or APP_NEW_PASSWORD for automation), never from argv,
so it does not land in shell history or the process list.
"""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
sys.path.insert(0, str(ROOT))

from app.auth.deps import database  # noqa: E402
from app.auth.service import AuthError, create_user  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a manual-agent login account.")
    parser.add_argument("--login-id", required=True)
    parser.add_argument("--role", choices=("user", "admin"), default="user")
    return parser


def _prompt_password() -> str:
    supplied = os.getenv("APP_NEW_PASSWORD")
    if supplied:
        return supplied
    first = getpass.getpass("비밀번호: ")
    if getpass.getpass("비밀번호 확인: ") != first:
        raise AuthError("비밀번호가 일치하지 않습니다.")
    return first


def main(argv: list[str] | None = None, *, read_password=_prompt_password) -> int:
    args = build_parser().parse_args(argv)
    try:
        password = read_password()
        with database() as connection:
            user = create_user(connection, args.login_id, password, role=args.role)
    except AuthError as error:
        print(f"계정을 만들지 못했습니다: {error.message}", file=sys.stderr)
        return 1
    print(f"계정을 만들었습니다: {user.login_id} ({user.role})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
