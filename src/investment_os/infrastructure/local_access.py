"""Local browser grants; only hashes are persisted, never bearer/provider secrets."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

PAIR_TTL = 120
SESSION_TTL = 30 * 24 * 60 * 60
_GRANT = re.compile(r"^[A-Za-z0-9_-]{43}$")
_LOG = logging.getLogger(__name__)


def local_origin(value: str) -> str:
    """Accept one literal loopback HTTP origin, never a remote deployment."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("local access requires an explicit loopback HTTP origin")
    port = parsed.port or 80
    host = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
    return f"http://{host}" + (f":{port}" if port != 80 else "")


def cookie_name(origin: str) -> str:
    return "investment_os_local_" + hashlib.sha256(origin.encode()).hexdigest()[:12]


def _digest(grant: str) -> str:
    return hashlib.sha256(grant.encode()).hexdigest()


class LocalAccessStore:
    """Atomic one-time pairing and persistent, revocable local sessions (ADR-0017)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with closing(self._connect()) as db, db:
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if version not in {0, 1}:
                raise ValueError("unsupported local access store version")
            db.execute(
                "CREATE TABLE IF NOT EXISTS local_grants ("
                "digest TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                "origin TEXT NOT NULL, expires_at INTEGER NOT NULL)"
            )
            db.execute("PRAGMA user_version = 1")
            db.execute(
                "CREATE TABLE IF NOT EXISTS local_access_events ("
                "id INTEGER PRIMARY KEY, event TEXT NOT NULL, occurred_at INTEGER NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=3)

    def issue_pairing(self, origin: str, *, now: int | None = None) -> str:
        origin = local_origin(origin)
        issued = int(time.time()) if now is None else now
        code = secrets.token_urlsafe(32)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM local_grants WHERE expires_at <= ?", (issued,))
            if db.execute("SELECT COUNT(*) FROM local_grants").fetchone()[0] >= 512:
                raise ValueError("local access grant limit reached")
            db.execute(
                "INSERT INTO local_grants VALUES (?, 'PAIR', ?, ?)",
                (_digest(code), origin, issued + PAIR_TTL),
            )
            db.execute(
                "INSERT INTO local_access_events(event, occurred_at) VALUES ('PAIR_ISSUED', ?)",
                (issued,),
            )
        _LOG.info("local_pairing_issued")
        return code

    def exchange(self, code: str, origin: str, *, now: int | None = None) -> tuple[str, int]:
        if not _GRANT.fullmatch(code):
            raise ValueError("invalid or expired local pairing")
        issued = int(time.time()) if now is None else now
        token = secrets.token_urlsafe(32)
        expires = issued + SESSION_TTL
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "DELETE FROM local_grants WHERE digest = ? AND kind = 'PAIR' "
                "AND origin = ? AND expires_at > ? RETURNING digest",
                (_digest(code), origin, issued),
            ).fetchone()
            if row is None:
                raise ValueError("invalid or expired local pairing")
            db.execute(
                "INSERT INTO local_grants VALUES (?, 'SESSION', ?, ?)",
                (_digest(token), origin, expires),
            )
            db.execute(
                "INSERT INTO local_access_events(event, occurred_at) VALUES ('SESSION_CREATED', ?)",
                (issued,),
            )
        _LOG.info("local_session_created")
        return token, expires

    def session_expiry(self, token: str, origin: str, *, now: int | None = None) -> int | None:
        if not _GRANT.fullmatch(token):
            return None
        current = int(time.time()) if now is None else now
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT expires_at FROM local_grants WHERE digest = ? AND kind = 'SESSION' "
                "AND origin = ? AND expires_at > ?",
                (_digest(token), origin, current),
            ).fetchone()
        return int(row[0]) if row else None

    def revoke(self, token: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "DELETE FROM local_grants WHERE digest = ? AND kind = 'SESSION'", (_digest(token),)
            )
            db.execute(
                "INSERT INTO local_access_events(event, occurred_at) VALUES ('SESSION_REVOKED', ?)",
                (int(time.time()),),
            )
        _LOG.info("local_session_revoked")
