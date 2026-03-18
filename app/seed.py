"""Seed script to create an initial SUPER_ADMIN user.

Usage:
    python -m app.seed
"""

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User


def seed_super_admin():
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == "admin@oasys.com").first()
        if existing:
            print("Super admin already exists.")
            return
        user = User(
            email="admin@oasys.com",
            hashed_password=hash_password("admin123"),
            role="SUPER_ADMIN",
        )
        db.add(user)
        db.commit()
        print(f"Super admin created: admin@oasys.com / admin123")
    finally:
        db.close()


def seed_apollo_admin():
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == "apollo@oasys.com").first()
        if existing:
            print("Apollo admin already exists.")
            return
        user = User(
            email="apollo@oasys.com",
            hashed_password=hash_password("apollo123"),
            role="HOSPITAL_ADMIN",
            hospital_id="a4d4be5c-f0c8-49bc-9402-6f508e061009",
        )
        db.add(user)
        db.commit()
        print("Apollo hospital admin created: apollo@oasys.com / apollo123")
    finally:
        db.close()


if __name__ == "__main__":
    seed_super_admin()
    seed_apollo_admin()
