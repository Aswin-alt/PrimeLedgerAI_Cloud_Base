#!/usr/bin/env python3
"""Seed roles, permissions, default Admin, and locations."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from webapp.config import (  # noqa: E402
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    PERMISSIONS,
    UPLOAD_DIR,
    OUTPUT_DIR,
)
from webapp.database import Base, SessionLocal, engine  # noqa: E402
from webapp.models import (  # noqa: E402
    ChartOfAccountRule,
    Location,
    Permission,
    Role,
    RolePermission,
    User,
)
from webapp.security import hash_password  # noqa: E402

DEFAULT_ROLE_GRANTS = {
    "Admin": [p[0] for p in PERMISSIONS],
    "Manager": [
        "dashboard.view",
        "records.view",
        "records.upload",
        "records.edit",
        "records.export",
        "records.approve",
        "convert.run",
        "convert.download",
        "audit.view_own",
        "audit.view_all",
        "audit.export",
        "settings.manage",
        "analytics.view",
    ],
    "Accountant": [
        "dashboard.view",
        "records.view",
        "records.upload",
        "records.edit",
        "records.export",
        "convert.run",
        "convert.download",
        "audit.view_own",
        "analytics.view",
    ],
    "Viewer": [
        "dashboard.view",
        "records.view",
        "records.export",
        "audit.view_own",
        "analytics.view",
    ],
}

LOCATIONS = [
    ("5164", "5164-Berkshire OH", "Cash on Hand - Berkshire OH", "FCB - Sunbury ac# 7053"),
    ("5165", "5165-Perrysburg OH", "Cash on Hand - Perrysburg,OH", "FCB - Perrysburgh ac# 7061"),
    ("5166", "5166-Jeffersonville", "Cash on Hand - Jeffersonville", "FCB - Jeffersonville ac# 2945"),
    ("5167", "5167-Elizabethtown KY", "Cash on Hand - Elizabethtown-KY", "FCB - ETown ac# 7045"),
    ("5168", "5168-Catlettsburg KY", "Cash on hand - Catlettsburg KY", "FCB - Cattletsburgh ac# 7079"),
    ("5169", "5169-Columbus OH", "Cash on Hand - Columbus OH", "FCB - Columbus ac# 7037"),
    ("7401", "7401-Youngstown", "Cash on Hand - Youngstown", "Marietta Restaurant llc (1842) - 1"),
    ("9690", "9690 - Marietta Rest", "Cash on Hand - Marietta", "Marietta Restaurant llc (1842) - 1"),
    ("9697", "9697-Findley", "Cash on Hand - Findlay", "FC Bank Ac#0167 - Nights and Bites"),
    ("HOTEL", "Marietta Hotel", "Cash on Hand - Marietta Hotel", "FC Bank AC# 0606"),
]

COA_RULES = [
    ("Fees Credit Cards QR", "Commissions & fees  *:Credit Card Fee", "Fees Credit Cards QR", "DEBIT"),
    ("Fees - Credit Cards", "Commissions & fees  *:Credit Card Fee", "Fees - Credit Cards", "DEBIT"),
    ("Amx Fees", "Commissions & fees  *:Credit Card Fee", "Fees - Credit Cards", "DEBIT"),
    ("Gross Credit Cards QR", "Credit Sales:QR Pay - Sales", "Gross Credit Cards QR", "CREDIT"),
    ("Gross - Credit Cards", "Credit Sales:Credit card - Sales to Dennys", "Gross - Credit Cards", "CREDIT"),
]


def seed() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Permissions
        perm_by_code: dict[str, Permission] = {}
        for code, name, category in PERMISSIONS:
            perm = db.query(Permission).filter_by(code=code).first()
            if not perm:
                perm = Permission(code=code, name=name, category=category)
                db.add(perm)
                db.flush()
            perm_by_code[code] = perm

        # Roles
        role_meta = {
            "Admin": ("Full system access; manage users and permissions", True),
            "Manager": ("Review, approve, manage mappings; no user admin", True),
            "Accountant": ("Upload, convert, edit records", True),
            "Viewer": ("Read-only dashboard and export", True),
        }
        roles: dict[str, Role] = {}
        for name, (desc, is_system) in role_meta.items():
            role = db.query(Role).filter_by(name=name).first()
            if not role:
                role = Role(name=name, description=desc, is_system=is_system)
                db.add(role)
                db.flush()
            roles[name] = role

        # Role permissions (only seed if role has none yet)
        for role_name, codes in DEFAULT_ROLE_GRANTS.items():
            role = roles[role_name]
            existing = db.query(RolePermission).filter_by(role_id=role.id).count()
            if existing:
                continue
            for code in codes:
                db.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=perm_by_code[code].id,
                        allowed=True,
                    )
                )

        # Admin user
        admin = db.query(User).filter_by(username=DEFAULT_ADMIN_USERNAME).first()
        if not admin:
            admin = User(
                username=DEFAULT_ADMIN_USERNAME,
                email=DEFAULT_ADMIN_EMAIL,
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                role_id=roles["Admin"].id,
                is_active=True,
            )
            db.add(admin)

        # Locations
        for code, name, cash, bank in LOCATIONS:
            loc = db.query(Location).filter_by(code=code).first()
            if not loc:
                db.add(
                    Location(
                        code=code, name=name, cash_account=cash, bank_account=bank
                    )
                )

        # Chart of accounts sample rules
        if db.query(ChartOfAccountRule).count() == 0:
            for contains, account, desc, entry in COA_RULES:
                db.add(
                    ChartOfAccountRule(
                        source_contains=contains,
                        account=account,
                        output_description=desc,
                        entry_type=entry,
                        tool_scope="remittance",
                    )
                )

        db.commit()
        print("Seed complete.")
        print(f"  Admin login: {DEFAULT_ADMIN_USERNAME} / {DEFAULT_ADMIN_PASSWORD}")
        print(f"  Roles: {', '.join(roles)}")
        print(f"  Permissions: {len(perm_by_code)}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
