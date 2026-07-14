"""Create or update the owner admin from ADMIN_SEED_* env vars.

Runnable as either:
    python -m scripts.create_admin        (from repo root)
    python scripts/create_admin.py
    cd backend && python -m scripts.create_admin

Never prints the password.
"""
from __future__ import annotations

import asyncio
import os
import sys

# Ensure the backend package is importable regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
if os.path.isdir(_BACKEND) and _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


async def _run() -> None:
    from app.core.config import settings
    from app.core.db import close_client
    from app.core.security import hash_password
    from app.models.common import new_id, now_utc
    from app.repositories.collections import users_repo

    email = settings.admin_seed_email.lower().strip()
    password = settings.admin_seed_password
    if not email or not password:
        print("ADMIN_SEED_EMAIL and ADMIN_SEED_PASSWORD must be set.")
        raise SystemExit(1)

    existing = await users_repo.get_by(email=email)
    password_hash = hash_password(password)
    if existing:
        await users_repo.update(existing["id"], {
            "passwordHash": password_hash,
            "role": "owner",
            "isActive": True,
            "forcePasswordChange": settings.force_password_change,
            "updatedAt": now_utc(),
        })
        print(f"Updated owner account: {email}")
    else:
        await users_repo.create({
            "id": new_id(),
            "email": email,
            "passwordHash": password_hash,
            "role": "owner",
            "name": "Owner",
            "isActive": True,
            "forcePasswordChange": settings.force_password_change,
            "failedLoginCount": 0,
            "createdAt": now_utc(),
            "updatedAt": now_utc(),
        })
        print(f"Created owner account: {email}")
    await close_client()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
