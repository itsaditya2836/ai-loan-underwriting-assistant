"""Local-Only Synthetic Demo User Setup Script.

Creates four synthetic demo accounts (one per RBAC role) using passwords
supplied solely through environment variables—never hardcoded in source control.

Safety guards:
- Strictly refuses to execute when APP_ENV is 'production' / 'prod'.
- Requires ALLOW_DEMO_SEED=true in environment AND --confirm-local-demo CLI flag.
- Requires 8+ character passwords from DEMO_*_PASSWORD environment variables.

Usage:
    ALLOW_DEMO_SEED=true \
    DEMO_ADMIN_PASSWORD='<set-local-password>' \
    DEMO_OFFICER_PASSWORD='<set-local-password>' \
    DEMO_UNDERWRITER_PASSWORD='<set-local-password>' \
    DEMO_SUPERVISOR_PASSWORD='<set-local-password>' \
    .venv/bin/python scripts/seed_demo_users.py --confirm-local-demo
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.auth.models import Role, UserCreate
from app.auth.service import AuthService
from app.database import init_db
from config.settings import get_settings

DEMO_ACCOUNTS: Tuple[Tuple[str, str, str, Role, str], ...] = (
    (
        "demo_admin",
        "Synthetic Demo Administrator",
        "demo_admin@synthetic.local",
        Role.ADMINISTRATOR,
        "DEMO_ADMIN_PASSWORD",
    ),
    (
        "demo_officer",
        "Synthetic Demo Loan Officer",
        "demo_officer@synthetic.local",
        Role.LOAN_OFFICER,
        "DEMO_OFFICER_PASSWORD",
    ),
    (
        "demo_underwriter",
        "Synthetic Demo Underwriter",
        "demo_underwriter@synthetic.local",
        Role.UNDERWRITER,
        "DEMO_UNDERWRITER_PASSWORD",
    ),
    (
        "demo_supervisor",
        "Synthetic Demo Supervisor",
        "demo_supervisor@synthetic.local",
        Role.SUPERVISOR,
        "DEMO_SUPERVISOR_PASSWORD",
    ),
)


def main() -> int:
    """Provision synthetic local demo accounts idempotently under strict safety checks."""
    parser = argparse.ArgumentParser(
        description="Provision synthetic demo accounts for local evaluation (never production)."
    )
    parser.add_argument(
        "--confirm-local-demo",
        action="store_true",
        help="Explicitly confirm seeding synthetic demo accounts in a local non-production DB.",
    )
    args = parser.parse_args()

    settings = get_settings()
    if settings.is_production():
        print(
            "ERROR: Refusing to create demo accounts when APP_ENV is configured for production.",
            file=sys.stderr,
        )
        return 1

    if os.environ.get("ALLOW_DEMO_SEED", "").strip().lower() != "true":
        print(
            "ERROR: Set ALLOW_DEMO_SEED=true explicitly before running demo account seeding.",
            file=sys.stderr,
        )
        return 1

    if not args.confirm_local_demo:
        print(
            "ERROR: Pass --confirm-local-demo explicitly to confirm non-production demo seeding.",
            file=sys.stderr,
        )
        return 1

    resolved_passwords: dict[str, str] = {}
    for username, _full_name, _email, _role, env_var in DEMO_ACCOUNTS:
        pw = os.environ.get(env_var, "")
        if len(pw) < 8:
            print(
                f"ERROR: Environment variable '{env_var}' for '{username}' must be set "
                "with at least 8 characters (no hardcoded passwords allowed).",
                file=sys.stderr,
            )
            return 1
        resolved_passwords[username] = pw

    if settings.database_url.startswith("sqlite"):
        init_db()
    auth = AuthService()
    auth.init_tables()

    print(f"Database target: {settings.database_url}")
    print("Provisioning SYNTHETIC DEMO ACCOUNTS (for local presentation only):")
    for username, full_name, email, role, _env_var in DEMO_ACCOUNTS:
        existing = auth.get_user_by_username(username)
        if existing is not None:
            print(f"  [SKIP] {username} ({existing.role.value}) — already exists")
            continue
        created = auth.create_user(
            UserCreate(
                username=username,
                full_name=full_name,
                email=email,
                password=resolved_passwords[username],
                role=role,
            )
        )
        print(f"  [CREATED] {created.username} (role={created.role.value}, synthetic)")

    print("\nMaker-Checker Workflow Reminder:")
    print("  1. Sign in as 'demo_officer' to create applicants and run underwriting.")
    print("  2. Sign in as 'demo_underwriter' to review/approve/reject cases.")
    print("  3. Sign in as 'demo_supervisor' to issue linked decision corrections.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
