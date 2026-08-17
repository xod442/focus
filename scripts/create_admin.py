"""Bootstrap the first admin user (there is no one to invite them).

Usage:
    python -m scripts.create_admin --email you@hpe.com --password 'secret123'
"""
import argparse

from app.db import SessionLocal, init_db
from app.models import User, ROLE_ADMIN
from app.security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an additional FOCUS admin user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        email = args.email.strip().lower()
        if db.query(User).filter(User.email == email).first():
            print(f"User {email} already exists — nothing to do.")
            return
        db.add(
            User(email=email, password_hash=hash_password(args.password), role=ROLE_ADMIN)
        )
        db.commit()
        print(f"Created admin: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
