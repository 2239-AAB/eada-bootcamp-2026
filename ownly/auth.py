"""Sign up, sign in, sign out, and the account page."""
import sqlite3
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from . import db, security

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("pages.home"))
    errors, email, name = {}, "", ""
    if request.method == "POST":
        email = security.normalize_email(request.form.get("email"))
        name = (request.form.get("name") or "").strip()[:80]
        password = request.form.get("password") or ""
        if security.limited("register_ip", security.client_ip()):
            abort(429, "Too many new accounts from this connection. Try again in an hour.")
        if problem := security.email_problem(email):
            errors["email"] = problem
        if problem := security.password_problem(password, email):
            errors["password"] = problem
        if password != (request.form.get("confirm") or ""):
            errors["confirm"] = "The two passwords don't match."
        if not name:
            errors["name"] = "Tell people what to call you."
        if not errors:
            try:
                user_id = db.run("INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)",
                                 email, security.hash_password(password), name)
            except sqlite3.IntegrityError:
                errors["email"] = "There's already an account with this email. Log in instead."
            else:
                security.record("register_ip", security.client_ip())
                security.start_session(user_id)
                flash("Welcome to Ownly. Your account is ready.")
                return redirect(security.safe_next(request.form.get("next")) or url_for("pages.home"))
    return render_template("register.html", errors=errors, email=email, name=name,
                           next=security.safe_next(request.values.get("next")) or "")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("pages.home"))
    error, email = None, ""
    if request.method == "POST":
        email = security.normalize_email(request.form.get("email"))
        password = request.form.get("password") or ""
        ip = security.client_ip()
        if security.limited("login_email", email) or security.limited("login_ip", ip):
            abort(429, "Too many sign-in attempts. Wait 15 minutes and try again.")
        user = db.one("SELECT * FROM users WHERE email = ?", email)
        if security.password_matches(user, password):
            security.forget("login_email", email)
            security.start_session(user["id"])
            return redirect(security.safe_next(request.form.get("next")) or url_for("pages.home"))
        security.record("login_email", email)
        security.record("login_ip", ip)
        error = "That email and password don't match an account."
    return render_template("login.html", error=error, email=email,
                           next=security.safe_next(request.values.get("next")) or "")


@bp.post("/logout")
def logout():
    security.end_session()
    flash("You're logged out.")
    return redirect(url_for("pages.home"))


@bp.route("/account", methods=["GET", "POST"])
@security.login_required
def account():
    errors = {}
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            name = (request.form.get("name") or "").strip()[:80]
            phone = (request.form.get("phone") or "").strip()[:40]
            if not name:
                errors["name"] = "Tell people what to call you."
            else:
                db.run("UPDATE users SET name = ?, phone = ? WHERE id = ?", name, phone, g.user["id"])
                flash("Profile saved.")
                return redirect(url_for("auth.account"))
        elif action == "password":
            current = request.form.get("current") or ""
            new = request.form.get("password") or ""
            if not security.password_matches(g.user, current):
                errors["current"] = "That isn't your current password."
            elif problem := security.password_problem(new, g.user["email"]):
                errors["password"] = problem
            elif new != (request.form.get("confirm") or ""):
                errors["confirm"] = "The two passwords don't match."
            else:
                db.run("UPDATE users SET password_hash = ? WHERE id = ?", security.hash_password(new), g.user["id"])
                security.end_other_sessions(g.user["id"])
                flash("Password changed. Other devices have been logged out.")
                return redirect(url_for("auth.account"))
        elif action == "delete":
            if not security.password_matches(g.user, request.form.get("current_delete") or ""):
                errors["current_delete"] = "That isn't your current password."
            else:
                _delete_account(g.user["id"])
                security.end_session()
                flash("Your account, listings and messages have been deleted.")
                return redirect(url_for("pages.home"))
    counts = db.one("SELECT (SELECT COUNT(*) FROM listings WHERE user_id = ?) AS listings, "
                    "(SELECT COUNT(*) FROM conversations WHERE buyer_id = ? OR seller_id = ?) AS conversations",
                    g.user["id"], g.user["id"], g.user["id"])
    return render_template("account.html", errors=errors, counts=counts)


def _delete_account(user_id: int) -> None:
    uploads = Path(current_app.config["UPLOADS"])
    files = [r["filename"] for r in db.all_(
        "SELECT p.filename FROM photos p JOIN listings l ON l.id = p.listing_id WHERE l.user_id = ?", user_id)]
    db.run("DELETE FROM users WHERE id = ?", user_id)  # cascades to listings, photos, sessions, messages
    for name in files:
        (uploads / name).unlink(missing_ok=True)
