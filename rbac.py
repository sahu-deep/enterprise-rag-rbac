"""SQLite-backed local authentication and role permissions."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TypedDict

DB_PATH = Path(__file__).resolve().parent / "users.db"
PASSWORD_HASH_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 12

ROLE_LABELS = {
    "finance": "Finance Team",
    "marketing": "Marketing Team",
    "hr": "HR Team",
    "engineering": "Engineering Department",
    "executive": "C-Level Executive",
    "employee": "Employee",
    "admin": "Administrator",
}

ROLE_COLLECTIONS = {
    "finance": ["finance"],
    "marketing": ["marketing"],
    "hr": ["hr"],
    "engineering": ["engineering"],
    "executive": ["engineering", "finance", "marketing", "hr", "general"],
    "employee": ["general"],
    "admin": [],
}

ASSIGNABLE_ROLES = {
    role: label for role, label in ROLE_LABELS.items() if role != "admin"
}


class User(TypedDict):
    username: str
    full_name: str
    role: str
    is_admin: bool
    allowed_collections: list[str]


@contextmanager
def _database_connection(isolation_level: str | None = None) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DB_PATH, isolation_level=isolation_level)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_auth_db() -> None:
    """Create the local user table if it does not already exist."""
    with _database_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY COLLATE NOCASE,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def has_users() -> bool:
    initialize_auth_db()
    with _database_connection() as connection:
        return connection.execute("SELECT EXISTS(SELECT 1 FROM users)").fetchone()[0] == 1


def _validate_user_fields(username: str, full_name: str, password: str, role: str) -> tuple[str, str]:
    normalized_username = username.strip().lower()
    normalized_name = full_name.strip()

    if not re.fullmatch(r"[a-z0-9_]{3,32}", normalized_username):
        raise ValueError("Username must be 3–32 characters and use only letters, numbers, or underscores.")
    if not normalized_name:
        raise ValueError("Full name is required.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > 1024:
        raise ValueError("Password is too long.")
    if role not in ROLE_LABELS:
        raise ValueError("Unknown user role.")

    return normalized_username, normalized_name


def _insert_user(
    connection: sqlite3.Connection,
    username: str,
    full_name: str,
    password: str,
    role: str,
) -> None:
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    connection.execute(
        """
        INSERT INTO users (username, full_name, role, password_salt, password_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        (username, full_name, role, salt.hex(), password_hash.hex()),
    )


def create_first_admin(username: str, full_name: str, password: str) -> User:
    """Create the initial administrator exactly once during first-run setup."""
    username, full_name = _validate_user_fields(username, full_name, password, "admin")
    initialize_auth_db()
    with _database_connection(isolation_level=None) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT EXISTS(SELECT 1 FROM users)").fetchone()[0]:
            connection.rollback()
            raise ValueError("An administrator has already been created.")
        _insert_user(connection, username, full_name, password, "admin")
        connection.commit()
    return _user_record(username, full_name, "admin")


def create_user(username: str, full_name: str, password: str, role: str) -> None:
    """Create a role account; this function is intended for administrator use."""
    if role not in ASSIGNABLE_ROLES:
        raise ValueError("Only department, executive, or employee roles can be assigned here.")
    username, full_name = _validate_user_fields(username, full_name, password, role)
    initialize_auth_db()
    try:
        with _database_connection() as connection:
            _insert_user(connection, username, full_name, password, role)
    except sqlite3.IntegrityError as exc:
        raise ValueError("That username already exists.") from exc


def authenticate_user(username: str, password: str) -> User | None:
    """Return the public user record for valid credentials, otherwise None."""
    initialize_auth_db()
    with _database_connection() as connection:
        row = connection.execute(
            """
            SELECT username, full_name, role, password_salt, password_hash
            FROM users WHERE username = ? COLLATE NOCASE
            """,
            (username.strip(),),
        ).fetchone()

    if row is None:
        salt = b"\0" * 16
        expected_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
        )
        hmac.compare_digest(expected_hash, b"\0" * len(expected_hash))
        return None

    stored_salt = bytes.fromhex(row[3])
    stored_hash = bytes.fromhex(row[4])
    supplied_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), stored_salt, PASSWORD_HASH_ITERATIONS
    )
    if not hmac.compare_digest(supplied_hash, stored_hash):
        return None

    return _user_record(row[0], row[1], row[2])


def _user_record(username: str, full_name: str, role: str) -> User:
    return {
        "username": username,
        "full_name": full_name,
        "role": role,
        "is_admin": role == "admin",
        "allowed_collections": ROLE_COLLECTIONS[role].copy(),
    }


def get_role_label(role: str) -> str:
    return ROLE_LABELS[role]


def get_available_collections(user: User) -> list[str]:
    return user["allowed_collections"].copy()


def can_access_collection(user: User, collection: str) -> bool:
    return collection.lower() in {item.lower() for item in get_available_collections(user)}
