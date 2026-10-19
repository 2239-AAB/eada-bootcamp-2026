"""Ownly: homes for sale in Ames, Iowa, each with a price estimate.

    .venv/bin/python -m ownly            # http://127.0.0.1:8720
    .venv/bin/python -m ownly seed       # add example listings
"""
import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .valuation import Valuer  # noqa: E402  first: it may restart Python so XGBoost finds OpenMP

from flask import Flask, abort, g, render_template, request  # noqa: E402

from . import db, security  # noqa: E402

INSTANCE = Path(__file__).resolve().parent / "instance"
MAX_UPLOAD_MB = 40

CSP = "; ".join([
    "default-src 'self'",
    "img-src 'self' data: blob: https://tile.openstreetmap.org",  # map tiles; keep in step with ownly.js
    "style-src 'self'",
    "script-src 'self'",
    "connect-src 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "object-src 'none'",
])

_valuer = None


def get_valuer() -> Valuer:
    """The model loads once per process (about a second)."""
    global _valuer
    if _valuer is None:
        _valuer = Valuer()
    return _valuer


def _secret_key(instance: Path) -> str:
    path = instance / "secret_key"
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    return path.read_text().strip()


def create_app(config: dict | None = None) -> Flask:
    instance = Path((config or {}).get("INSTANCE", INSTANCE))
    # The database holds password hashes and private messages: owner-only.
    instance.mkdir(mode=0o700, parents=True, exist_ok=True)
    (instance / "uploads").mkdir(mode=0o700, exist_ok=True)
    os.chmod(instance, 0o700)

    app = Flask(__name__, instance_path=str(instance))
    app.config.update(
        SECRET_KEY=_secret_key(instance),
        DATABASE=str(instance / "ownly.sqlite3"),
        UPLOADS=str(instance / "uploads"),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
        SESSION_COOKIE_NAME="ownly",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Set OWNLY_HTTPS=1 once the site is served over TLS.
        SESSION_COOKIE_SECURE=os.environ.get("OWNLY_HTTPS") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=security.SESSION_DAYS),
    )
    if config:
        app.config.update({k: v for k, v in config.items() if k != "INSTANCE"})
    db.init(app.config["DATABASE"])

    from . import auth, listings, messages, pages
    for module in (pages, auth, listings, messages):
        app.register_blueprint(module.bp)

    app.teardown_appcontext(db.close)

    @app.before_request
    def _load():
        # Never serve hidden files or folders (tools drop state like .claude-flow/ into static/).
        if "/." in request.path:
            abort(404)
        security.load_user()
        security.check_csrf()
        g.unread = messages.unread_count(g.user["id"]) if g.user else 0

    @app.after_request
    def _headers(response):
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if g.get("user") is not None or request.path.startswith(("/messages", "/account", "/my")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.context_processor
    def _globals():
        return {"csrf_token": security.csrf_token, "user": g.get("user"), "unread": g.get("unread", 0),
                "statuses": listings.STATUSES}

    for name, fn in pages.FILTERS.items():
        app.add_template_filter(fn, name)

    def _error(code, title):
        def handler(err):
            detail = getattr(err, "description", "") if code in (400, 429) else ""
            return render_template("error.html", code=code, title=title, detail=detail), code
        return handler

    for code, title in [(400, "That request didn't work"), (403, "That isn't yours to change"),
                        (404, "We can't find that page"), (413, "Those files are too large"),
                        (429, "Slow down a little"), (500, "Something went wrong on our side")]:
        app.register_error_handler(code, _error(code, title))
    return app
