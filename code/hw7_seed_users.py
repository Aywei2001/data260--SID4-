from getpass import getpass

from hw7_authentication import Role, SessionLocal, User, pwd_context


def main():
    db = SessionLocal()
    try:
        accounts = [
            ("reader1", Role.reader),
            ("writer1", Role.writer),
            ("moderator1", Role.moderator),
        ]

        for username, role in accounts:
            existing = db.query(User).filter(User.username == username).first()
            if existing:
                print(f"{username} already exists; leaving it unchanged.")
                continue

            password = getpass(f"Set a password for {username}: ")
            db.add(
                User(
                    username=username,
                    password_hash=pwd_context.hash(password),
                    role=role,
                )
            )

        db.commit()
        print("HW7 accounts are ready.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
