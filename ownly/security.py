"""Accounts, sessions, CSRF protection and rate limits."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import abort, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

SESSION_DAYS = 14
PASSWORD_MIN, PASSWORD_MAX = 8, 128
# Only a shape check: the user asked for no email verification.
EMAIL_SHAPE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{1,63}$")

# Sign-ins against unknown emails check this hash, so they take as long as real ones.
_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(16))

# kind: (attempts allowed, window in minutes)
LIMITS = {
    "login_email": (5, 15),
    "login_ip": (30, 15),
    "register_ip": (10, 60),
    "message": (30, 60),
    "listing": (20, 24 * 60),
}


# ---------------------------------------------------------------- passwords

def normalize_email(raw: str | None) -> str:
    return (raw or "").strip().lower()


def email_problem(email: str) -> str | None:
    if not EMAIL_SHAPE.match(email) or len(email) > 254:
        return "Enter an email address like name@example.com."
    return None


def password_problem(password: str, email: str) -> str | None:
    if len(password) < PASSWORD_MIN:
        return f"Use at least {PASSWORD_MIN} characters."
    if len(password) > PASSWORD_MAX:
        return f"Use at most {PASSWORD_MAX} characters."
    if password.strip().lower() == email:
        return "Your password can't be your email address."
    return None


def hash_password(password: str) -> str:
    return generate_password_hash(password)  # scrypt, salted


def password_matches(user, password: str) -> bool:
    if user is None:
        check_password_hash(_DUMMY_HASH, password)
        return False
    return check_password_hash(user["password_hash"], password)


# ---------------------------------------------------------------- sessions

def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _timestamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")  # the format of SQLite's datetime('now')


def start_session(user_id: int) -> None:
    """A fresh session token on every sign-in, so an old cookie cannot be fixed in place."""
    token = secrets.token_urlsafe(32)
    expires = _timestamp(datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS))
    db.run("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
           _digest(token), user_id, expires)
    db.run("DELETE FROM sessions WHERE expires_at <= datetime('now')")
    session.clear()
    session.permanent = True
    session["sid"] = token
    session["csrf"] = secrets.token_urlsafe(32)


def end_session() -> None:
    token = session.get("sid")
    if token:
        db.run("DELETE FROM sessions WHERE token_hash = ?", _digest(token))
    session.clear()


def end_other_sessions(user_id: int) -> None:
    token = session.get("sid", "")
    db.run("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", user_id, _digest(token))


def load_user() -> None:
    g.user = None
    token = session.get("sid")
    if not token:
        return
    g.user = db.one(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > datetime('now')", _digest(token))
    if g.user is None:
        session.pop("sid", None)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def safe_next(target: str | None) -> str | None:
    """Only same-site paths, so a crafted link cannot bounce people to another site."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


# ---------------------------------------------------------------- CSRF

def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf() -> None:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    expected = session.get("csrf", "")
    sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token", "")
    if not expected or not sent or not hmac.compare_digest(sent, expected):
        abort(400, "This form has expired. Go back, reload the page and try again.")


# ---------------------------------------------------------------- rate limits

def client_ip() -> str:
    return request.remote_addr or "unknown"


def limited(kind: str, key: str) -> bool:
    allowed, minutes = LIMITS[kind]
    row = db.one("SELECT COUNT(*) AS n FROM attempts WHERE kind = ? AND key = ? "
                 "AND created_at > datetime('now', ?)", kind, key, f"-{minutes} minutes")
    return row["n"] >= allowed


def record(kind: str, key: str) -> None:
    db.run("INSERT INTO attempts (kind, key) VALUES (?, ?)", kind, key)
    db.run("DELETE FROM attempts WHERE created_at < datetime('now', '-2 days')")


def forget(kind: str, key: str) -> None:
    db.run("DELETE FROM attempts WHERE kind = ? AND key = ?", kind, key)
