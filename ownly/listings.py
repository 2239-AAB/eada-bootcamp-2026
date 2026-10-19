"""Browsing, listing a home, editing it, its photos, and contacting the seller."""
import re
import secrets
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   send_from_directory, url_for)

from . import db, forms, get_valuer, security
from .messages import MESSAGE_MAX, post_message
from .pages import map_context, map_pins, neighborhoods, with_estimates

bp = Blueprint("listings", __name__)

STATUSES = forms.STATUSES
PAGE_SIZE = 24
MAX_PHOTOS = 8
MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_NAME = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")
MIMETYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
SORTS = {"newest": "Newest", "price_asc": "Price, low to high", "price_desc": "Price, high to low",
         "value": "Furthest below estimate"}


# ---------------------------------------------------------------- browsing

@bp.get("/homes")
def browse():
    args = request.args
    where, params = ["status IN ('active', 'under_offer')"], []
    hood = args.get("neighborhood", "")
    if hood in dict(neighborhoods()):
        where.append("neighborhood = ?")
        params.append(hood)
    for key, column, op in (("min_price", "price", ">="), ("max_price", "price", "<="),
                            ("beds", "bedrooms", ">="), ("baths", "full_baths", ">=")):
        value = _int(args.get(key))
        if value is not None:
            where.append(f"{column} {op} ?")
            params.append(value)
    sort = args.get("sort") if args.get("sort") in SORTS else "newest"
    order = {"price_asc": "price ASC", "price_desc": "price DESC"}.get(sort, "is_example, created_at DESC, id DESC")
    rows = db.all_(f"SELECT * FROM listings WHERE {' AND '.join(where)} ORDER BY {order}", *params)
    items = with_estimates(rows)
    if sort == "value":
        items.sort(key=lambda item: item["vs_estimate"])
    page = max(1, _int(args.get("page")) or 1)
    pages = max(1, -(-len(items) // PAGE_SIZE))
    shown = items[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    filters = {k: args.get(k, "") for k in ("neighborhood", "min_price", "max_price", "beds", "baths")}
    return render_template("browse.html", listings=shown, total=len(items), page=page, pages=pages,
                           filters=filters, sort=sort, sorts=SORTS, neighborhoods=neighborhoods(),
                           pins=map_pins(items), area=get_valuer().area)


def _int(raw) -> int | None:
    """A filter number, or None when it is empty, malformed or too large for SQLite."""
    try:
        value = int(str(raw).replace(",", "").replace("$", "")) if raw not in (None, "") else None
    except ValueError:
        return None
    return value if value is None or abs(value) < 10**12 else None


@bp.get("/homes/<int:listing_id>")
def detail(listing_id: int):
    row = db.one("SELECT l.*, u.email AS owner_email FROM listings l JOIN users u ON u.id = l.user_id "
                 "WHERE l.id = ?", listing_id)
    if row is None:
        abort(404)
    item = with_estimates([row])[0]
    photos = db.all_("SELECT * FROM photos WHERE listing_id = ? ORDER BY position, id", listing_id)
    conversation = None
    if g.user and g.user["id"] != row["user_id"]:
        conversation = db.one("SELECT id FROM conversations WHERE listing_id = ? AND buyer_id = ?",
                              listing_id, g.user["id"])
    enquiries = 0
    if g.user and g.user["id"] == row["user_id"]:
        enquiries = db.one("SELECT COUNT(*) AS n FROM conversations WHERE listing_id = ?", listing_id)["n"]
    _, notes = get_valuer().house_row(forms.listing_inputs(row))
    return render_template("listing.html", listing=item, photos=photos, conversation=conversation,
                           enquiries=enquiries, notes=notes, forms=forms)


# ---------------------------------------------------------------- listing a home

@bp.route("/sell", methods=["GET", "POST"])
@security.login_required
def sell():
    fields = forms.listing_fields(neighborhoods(), get_valuer().area)
    values = {f.name: f.default for f in fields}
    values.update(contact_name=g.user["name"], contact_phone=g.user["phone"])
    errors = {}
    if request.method == "POST":
        if security.limited("listing", str(g.user["id"])):
            abort(429, "You've listed a lot of homes today. Try again tomorrow.")
        values, errors = forms.parse(fields, request.form)
        if not errors:
            model_price = get_valuer().model_prices([forms.valuer_inputs(values)])[0]
            columns = [f.name for f in fields]
            listing_id = db.run(
                f"INSERT INTO listings (user_id, model_price, {', '.join(columns)}) "
                f"VALUES (?, ?, {', '.join('?' * len(columns))})",
                g.user["id"], model_price, *[values[c] for c in columns])
            security.record("listing", str(g.user["id"]))
            problems = _save_photos(listing_id, request.files.getlist("photos"))
            flash("Your home is listed." + (" " + " ".join(problems) if problems else ""))
            return redirect(url_for("listings.detail", listing_id=listing_id))
    return render_template("listing_form.html", fields=fields, values=values, errors=errors, listing=None,
                           photos=[], max_photos=MAX_PHOTOS, map_info=map_context())


def _own(listing_id: int):
    row = db.one("SELECT * FROM listings WHERE id = ?", listing_id)
    if row is None:
        abort(404)
    if row["user_id"] != g.user["id"]:
        abort(403)
    return row


@bp.route("/homes/<int:listing_id>/edit", methods=["GET", "POST"])
@security.login_required
def edit(listing_id: int):
    row = _own(listing_id)
    fields = forms.listing_fields(neighborhoods(), get_valuer().area)
    values, errors = {f.name: row[f.name] for f in fields}, {}
    if request.method == "POST":
        values, errors = forms.parse(fields, request.form)
        if not errors:
            model_price = get_valuer().model_prices([forms.valuer_inputs(values)])[0]
            columns = [f.name for f in fields]
            db.run(f"UPDATE listings SET {', '.join(c + ' = ?' for c in columns)}, model_price = ?, "
                   f"updated_at = datetime('now') WHERE id = ?",
                   *[values[c] for c in columns], model_price, listing_id)
            problems = _save_photos(listing_id, request.files.getlist("photos"))
            flash("Changes saved." + (" " + " ".join(problems) if problems else ""))
            return redirect(url_for("listings.detail", listing_id=listing_id))
    photos = db.all_("SELECT * FROM photos WHERE listing_id = ? ORDER BY position, id", listing_id)
    return render_template("listing_form.html", fields=fields, values=values, errors=errors, listing=row,
                           photos=photos, max_photos=MAX_PHOTOS, map_info=map_context())


@bp.post("/homes/<int:listing_id>/status")
@security.login_required
def set_status(listing_id: int):
    _own(listing_id)
    status = request.form.get("status")
    if status not in STATUSES:
        abort(400, "Unknown status.")
    db.run("UPDATE listings SET status = ?, updated_at = datetime('now') WHERE id = ?", status, listing_id)
    flash(f"Marked as {STATUSES[status].lower()}.")
    return redirect(security.safe_next(request.form.get("next")) or url_for("listings.detail", listing_id=listing_id))


@bp.post("/homes/<int:listing_id>/delete")
@security.login_required
def delete(listing_id: int):
    _own(listing_id)
    files = [r["filename"] for r in db.all_("SELECT filename FROM photos WHERE listing_id = ?", listing_id)]
    db.run("DELETE FROM listings WHERE id = ?", listing_id)
    uploads = Path(current_app.config["UPLOADS"])
    for name in files:
        (uploads / name).unlink(missing_ok=True)
    flash("Listing deleted.")
    return redirect(url_for("listings.mine"))


@bp.get("/my/listings")
@security.login_required
def mine():
    rows = db.all_("SELECT * FROM listings WHERE user_id = ? ORDER BY created_at DESC, id DESC", g.user["id"])
    counts = {r["listing_id"]: r["n"] for r in db.all_(
        "SELECT listing_id, COUNT(*) AS n FROM conversations WHERE seller_id = ? GROUP BY listing_id", g.user["id"])}
    return render_template("my_listings.html", listings=with_estimates(rows), counts=counts)


# ---------------------------------------------------------------- photos

def _photo_kind(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _save_photos(listing_id: int, files) -> list[str]:
    """Store uploaded photos under random names; returns a note for each one skipped."""
    problems = []
    count = db.one("SELECT COUNT(*) AS n FROM photos WHERE listing_id = ?", listing_id)["n"]
    uploads = Path(current_app.config["UPLOADS"])
    for upload in files:
        if not upload or not upload.filename:
            continue
        label = Path(upload.filename).name[:60]
        if count >= MAX_PHOTOS:
            problems.append(f"Skipped {label}: a listing can have {MAX_PHOTOS} photos.")
            continue
        data = upload.read(MAX_PHOTO_BYTES + 1)
        if len(data) > MAX_PHOTO_BYTES:
            problems.append(f"Skipped {label}: photos can be up to {MAX_PHOTO_BYTES // 1024 // 1024} MB.")
            continue
        kind = _photo_kind(data[:16])
        if kind is None:
            problems.append(f"Skipped {label}: only JPEG, PNG and WebP images can be uploaded.")
            continue
        name = f"{secrets.token_hex(16)}.{kind}"
        (uploads / name).write_bytes(data)
        db.run("INSERT INTO photos (listing_id, filename, position) VALUES (?, ?, ?)", listing_id, name, count)
        count += 1
    return problems


@bp.post("/homes/<int:listing_id>/photos/<int:photo_id>/delete")
@security.login_required
def delete_photo(listing_id: int, photo_id: int):
    _own(listing_id)
    photo = db.one("SELECT * FROM photos WHERE id = ? AND listing_id = ?", photo_id, listing_id)
    if photo is None:
        abort(404)
    db.run("DELETE FROM photos WHERE id = ?", photo_id)
    (Path(current_app.config["UPLOADS"]) / photo["filename"]).unlink(missing_ok=True)
    flash("Photo removed.")
    return redirect(url_for("listings.edit", listing_id=listing_id))


@bp.get("/photos/<name>")
def photo(name: str):
    match = PHOTO_NAME.match(name)
    if not match:
        abort(404)
    response = send_from_directory(current_app.config["UPLOADS"], name, mimetype=MIMETYPES[match.group(1)],
                                   max_age=86400)
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


# ---------------------------------------------------------------- contacting the seller

@bp.post("/homes/<int:listing_id>/contact")
@security.login_required
def contact(listing_id: int):
    row = db.one("SELECT * FROM listings WHERE id = ?", listing_id)
    if row is None:
        abort(404)
    if row["user_id"] == g.user["id"]:
        abort(400, "This is your own listing.")
    if row["is_example"]:
        abort(400, "Example listings can't be contacted.")
    if row["status"] == "sold":
        abort(400, "This home has been sold.")
    body = (request.form.get("body") or "").strip()
    if not body or len(body) > MESSAGE_MAX:
        flash(f"Write a message of up to {MESSAGE_MAX:,} characters.")
        return redirect(url_for("listings.detail", listing_id=listing_id))
    if security.limited("message", str(g.user["id"])):
        abort(429, "You've sent a lot of messages in the last hour. Try again later.")
    db.run("INSERT OR IGNORE INTO conversations (listing_id, buyer_id, seller_id) VALUES (?, ?, ?)",
           listing_id, g.user["id"], row["user_id"])
    conversation = db.one("SELECT id FROM conversations WHERE listing_id = ? AND buyer_id = ?",
                          listing_id, g.user["id"])
    post_message(conversation["id"], body)
    flash("Message sent. You'll find the seller's replies in Messages.")
    return redirect(url_for("messages.thread", conversation_id=conversation["id"]))

