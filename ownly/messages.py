"""Conversations between a buyer and a seller about one listing."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import db, security

bp = Blueprint("messages", __name__)

MESSAGE_MAX = 2000


def unread_count(user_id: int) -> int:
    return db.one(
        "SELECT COUNT(*) AS n FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE (c.buyer_id = ? OR c.seller_id = ?) AND m.sender_id != ? AND m.read_at IS NULL",
        user_id, user_id, user_id)["n"]


def post_message(conversation_id: int, body: str) -> None:
    security.record("message", str(g.user["id"]))
    db.run("INSERT INTO messages (conversation_id, sender_id, body) VALUES (?, ?, ?)",
           conversation_id, g.user["id"], body)
    db.run("UPDATE conversations SET updated_at = datetime('now') WHERE id = ?", conversation_id)


def _participant(conversation_id: int):
    """The conversation, if the signed-in user is in it. Everyone else gets a 404."""
    row = db.one(
        "SELECT c.*, l.title, l.price, l.status, l.neighborhood, "
        "b.name AS buyer_name, s.name AS seller_name FROM conversations c "
        "JOIN listings l ON l.id = c.listing_id JOIN users b ON b.id = c.buyer_id JOIN users s ON s.id = c.seller_id "
        "WHERE c.id = ? AND (c.buyer_id = ? OR c.seller_id = ?)",
        conversation_id, g.user["id"], g.user["id"])
    if row is None:
        abort(404)
    return row


@bp.get("/messages")
@security.login_required
def inbox():
    uid = g.user["id"]
    rows = db.all_(
        "SELECT c.id, c.listing_id, c.buyer_id, c.updated_at, l.title, l.price, l.status, "
        "CASE WHEN c.buyer_id = ? THEN s.name ELSE b.name END AS other_name, "
        "(SELECT body FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_body, "
        "(SELECT sender_id FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_sender, "
        "(SELECT COUNT(*) FROM messages WHERE conversation_id = c.id AND sender_id != ? AND read_at IS NULL) AS unread "
        "FROM conversations c JOIN listings l ON l.id = c.listing_id "
        "JOIN users b ON b.id = c.buyer_id JOIN users s ON s.id = c.seller_id "
        "WHERE c.buyer_id = ? OR c.seller_id = ? ORDER BY c.updated_at DESC, c.id DESC",
        uid, uid, uid, uid)
    return render_template("inbox.html", conversations=rows)


@bp.get("/messages/<int:conversation_id>")
@security.login_required
def thread(conversation_id: int):
    convo = _participant(conversation_id)
    db.run("UPDATE messages SET read_at = datetime('now') WHERE conversation_id = ? AND sender_id != ? "
           "AND read_at IS NULL", conversation_id, g.user["id"])
    g.unread = unread_count(g.user["id"])
    messages = db.all_("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", conversation_id)
    role = "buyer" if convo["buyer_id"] == g.user["id"] else "seller"
    return render_template("thread.html", convo=convo, messages=messages, role=role, max_length=MESSAGE_MAX)


@bp.post("/messages/<int:conversation_id>")
@security.login_required
def reply(conversation_id: int):
    _participant(conversation_id)
    body = (request.form.get("body") or "").strip()
    if not body or len(body) > MESSAGE_MAX:
        flash(f"Write a message of up to {MESSAGE_MAX:,} characters.")
    elif security.limited("message", str(g.user["id"])):
        abort(429, "You've sent a lot of messages in the last hour. Try again later.")
    else:
        post_message(conversation_id, body)
    return redirect(url_for("messages.thread", conversation_id=conversation_id) + "#latest")
