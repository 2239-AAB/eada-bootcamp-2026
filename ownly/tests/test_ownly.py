"""Ownly's flows and its security rules.

    .venv/bin/python -m pytest ownly/tests -q
"""
import re
import sqlite3

import pytest

from ownly import create_app, seed

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")

HOME = {"neighborhood": "North_Ames", "style": "one", "living_area": "1450", "bedrooms": "3", "full_baths": "2",
        "half_baths": "0", "basement_area": "1000", "basement_finished": "400", "lot_area": "9500",
        "year_built": "1973", "year_remodeled": "", "garage_cars": "2", "fireplaces": "1", "overall_quality": "6",
        "overall_condition": "5", "kitchen_quality": "3", "exterior_quality": "3", "central_air": "1"}
LISTING = {**HOME, "title": "Bright ranch near the park", "address": "123 Example St", "price": "289,900",
           "description": "Sunny kitchen.", "contact_name": "Sam", "contact_phone": "515 555 0100",
           "show_phone": "1"}


@pytest.fixture()
def app(tmp_path):
    return create_app({"INSTANCE": tmp_path, "TESTING": True})


@pytest.fixture()
def client(app):
    return app.test_client()


def csrf(client) -> str:
    with client.session_transaction() as s:
        s.setdefault("csrf", "test-token")
        return s["csrf"]


def post(client, path, data=None, **kw):
    return client.post(path, data={**(data or {}), "csrf": csrf(client)}, **kw)


def register(client, email="seller@example.com", password="correct horse", name="Sam"):
    return post(client, "/register", {"email": email, "password": password, "confirm": password, "name": name})


def logout(client):
    return post(client, "/logout")


def list_home(client, **changes):
    r = post(client, "/sell", {**LISTING, **changes}, content_type="multipart/form-data")
    assert r.status_code == 302, r.data[:500]
    return int(re.search(r"/homes/(\d+)", r.headers["Location"]).group(1))


def db(app):
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------- accounts

def test_register_stores_a_password_hash_not_the_password(app, client):
    assert register(client).status_code == 302
    row = db(app).execute("SELECT * FROM users").fetchone()
    assert row["email"] == "seller@example.com"
    assert "correct horse" not in row["password_hash"]
    assert row["password_hash"].startswith("scrypt:")


def test_register_rejects_short_password_mismatch_and_duplicate(client):
    r = post(client, "/register", {"email": "a@example.com", "password": "short", "confirm": "short", "name": "A"})
    assert b"at least 8 characters" in r.data
    r = post(client, "/register", {"email": "a@example.com", "password": "long enough", "confirm": "other one", "name": "A"})
    assert b"don&#39;t match" in r.data
    register(client, email="a@example.com")
    logout(client)
    r = register(client, email="A@Example.com")
    assert b"already an account" in r.data


def test_email_is_only_shape_checked(client):
    assert register(client, email="not-an-email").status_code == 200
    assert register(client, email="made.up@nowhere.example").status_code == 302


def test_login_logout_and_wrong_password(client):
    register(client)
    logout(client)
    r = post(client, "/login", {"email": "seller@example.com", "password": "wrong password"})
    assert b"don&#39;t match an account" in r.data
    r = post(client, "/login", {"email": "SELLER@example.com", "password": "correct horse"})
    assert r.status_code == 302
    assert b"Messages" in client.get("/").data
    logout(client)
    assert client.get("/messages").status_code == 302


def test_logout_revokes_the_session_server_side(app, client):
    register(client)
    with client.session_transaction() as s:
        stolen = dict(s)
    logout(client)
    with client.session_transaction() as s:
        s.update(stolen)
    assert client.get("/messages").status_code == 302


def test_login_is_rate_limited(client):
    register(client)
    logout(client)
    for _ in range(5):
        post(client, "/login", {"email": "seller@example.com", "password": "nope nope"})
    r = post(client, "/login", {"email": "seller@example.com", "password": "correct horse"})
    assert r.status_code == 429


def test_login_does_not_redirect_off_site(client):
    register(client)
    logout(client)
    r = post(client, "/login", {"email": "seller@example.com", "password": "correct horse", "next": "//evil.example/x"})
    assert r.headers["Location"] == "/"


def test_posts_without_csrf_token_are_refused(client):
    r = client.post("/register", data={"email": "x@example.com", "password": "long enough", "confirm": "long enough", "name": "X"})
    assert r.status_code == 400
    register(client)
    r = client.post("/sell", data=LISTING)
    assert r.status_code == 400


def test_change_password_and_delete_account(app, client):
    register(client)
    list_home(client)
    r = post(client, "/account", {"action": "password", "current": "correct horse", "password": "new password 1",
                                  "confirm": "new password 1"})
    assert r.status_code == 302
    r = post(client, "/account", {"action": "delete", "current_delete": "wrong"})
    assert b"isn&#39;t your current password" in r.data
    r = post(client, "/account", {"action": "delete", "current_delete": "new password 1"})
    assert r.status_code == 302
    conn = db(app)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0] == 0


# ---------------------------------------------------------------- listings

def test_listing_needs_an_account(client):
    r = client.get("/sell")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_list_a_home_with_photo_and_estimate(app, client):
    register(client)
    data = {**LISTING, "photos": [(__import__("io").BytesIO(PNG), "front.png")]}
    r = post(client, "/sell", data, content_type="multipart/form-data")
    listing_id = int(re.search(r"/homes/(\d+)", r.headers["Location"]).group(1))
    page = client.get(f"/homes/{listing_id}").data.decode()
    assert "$289,900" in page and "Ownly estimate" in page
    photo = db(app).execute("SELECT filename FROM photos").fetchone()["filename"]
    r = client.get(f"/photos/{photo}")
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_fake_image_is_rejected(app, client):
    register(client)
    data = {**LISTING, "photos": [(__import__("io").BytesIO(b"<script>alert(1)</script>"), "evil.jpg")]}
    post(client, "/sell", data, content_type="multipart/form-data")
    assert db(app).execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 0


def test_invalid_listing_shows_errors(client):
    register(client)
    r = post(client, "/sell", {**LISTING, "price": "lots", "basement_finished": "5000"},
             content_type="multipart/form-data")
    assert r.status_code == 200
    assert b"Enter a whole number" in r.data and b"larger than the basement" in r.data


def test_only_the_owner_can_edit_or_delete(client):
    register(client)
    listing_id = list_home(client)
    logout(client)
    register(client, email="other@example.com", name="Alex")
    assert client.get(f"/homes/{listing_id}/edit").status_code == 403
    assert post(client, f"/homes/{listing_id}/delete").status_code == 403
    assert post(client, f"/homes/{listing_id}/status", {"status": "sold"}).status_code == 403


def test_owner_edits_status_and_deletes(app, client):
    register(client)
    listing_id = list_home(client)
    r = post(client, f"/homes/{listing_id}/edit", {**LISTING, "price": "279,900"}, content_type="multipart/form-data")
    assert r.status_code == 302
    assert post(client, f"/homes/{listing_id}/status", {"status": "under_offer"}).status_code == 302
    row = db(app).execute("SELECT price, status FROM listings").fetchone()
    assert (row["price"], row["status"]) == (279900, "under_offer")
    post(client, f"/homes/{listing_id}/delete")
    assert client.get(f"/homes/{listing_id}").status_code == 404


def test_user_text_is_escaped(client):
    register(client, name="<b>Sam</b>")
    listing_id = list_home(client, title="<script>alert(1)</script> home", description="<img src=x onerror=alert(1)>")
    page = client.get(f"/homes/{listing_id}").data.decode()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "<img src=x" not in page


def test_security_headers(client):
    r = client.get("/")
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"


def test_browse_filters(client):
    register(client)
    list_home(client, price="150000", neighborhood="Old_Town")
    list_home(client, price="450000", neighborhood="Stone_Brook")
    page = client.get("/homes?max_price=200000").data.decode()
    assert "$150,000" in page and "$450,000" not in page
    page = client.get("/homes?neighborhood=Stone_Brook").data.decode()
    assert "$450,000" in page and "$150,000" not in page


# ---------------------------------------------------------------- contacting a seller

def test_buyer_contacts_seller_and_seller_replies(app, client):
    register(client)
    listing_id = list_home(client)
    logout(client)

    page = client.get(f"/homes/{listing_id}").data.decode()
    assert "515 555 0100" not in page  # contact details only for signed-in users
    register(client, email="buyer@example.com", name="Alex")
    assert "515 555 0100" in client.get(f"/homes/{listing_id}").data.decode()
    assert "seller@example.com" not in client.get(f"/homes/{listing_id}").data.decode()  # show_email is off

    r = post(client, f"/homes/{listing_id}/contact", {"body": "Is it still available?"})
    thread = r.headers["Location"]
    logout(client)

    post(client, "/login", {"email": "seller@example.com", "password": "correct horse"})
    assert b'aria-label="1 unread"' in client.get("/messages").data
    assert b"Is it still available?" in client.get(thread).data
    post(client, thread, {"body": "Yes, come by on Saturday."})
    assert b"unread" not in client.get("/").data
    logout(client)

    register(client, email="snoop@example.com", name="Snoop")
    assert client.get(thread).status_code == 404
    assert post(client, thread, {"body": "hi"}).status_code == 404


def test_cannot_contact_own_example_or_sold_listing(app, client):
    register(client)
    listing_id = list_home(client)
    assert post(client, f"/homes/{listing_id}/contact", {"body": "me"}).status_code == 400
    post(client, f"/homes/{listing_id}/status", {"status": "sold"})
    logout(client)
    register(client, email="buyer@example.com")
    assert post(client, f"/homes/{listing_id}/contact", {"body": "hi"}).status_code == 400
    with app.app_context():
        seed.add_examples(2)
    example = db(app).execute("SELECT id FROM listings WHERE is_example = 1").fetchone()["id"]
    assert post(client, f"/homes/{example}/contact", {"body": "hi"}).status_code == 400


# ---------------------------------------------------------------- the estimate

def test_estimate_matches_the_report_calculator(client):
    r = client.get("/api/estimate", query_string=HOME)
    data = r.get_json()
    assert data["ok"]
    assert round(data["model_price"]) == 148_880  # what the report's in-page calculator gives for this house
    assert data["low"] < data["value"] < data["high"]


def test_estimate_rejects_bad_input(client):
    r = client.get("/api/estimate", query_string={**HOME, "living_area": "-5"})
    assert r.status_code == 400 and "living_area" in r.get_json()["errors"]


def test_newer_and_unusual_homes_get_notes(client):
    data = client.get("/api/estimate", query_string={**HOME, "year_built": "2019", "living_area": "6000"}).get_json()
    assert any("2010" in n for n in data["notes"]) and any("living area" in n for n in data["notes"])


def test_hostile_numbers_do_not_crash(client):
    assert client.get("/api/estimate", query_string={**HOME, "living_area": "inf"}).status_code == 400
    assert client.get("/api/estimate", query_string={**HOME, "living_area": "nan"}).status_code == 400
    assert client.get("/homes?min_price=99999999999999999999999&page=99999").status_code == 200
    assert client.get("/homes?beds=abc&sort=';drop table listings").status_code == 200


# ---------------------------------------------------------------- the map

def test_pin_is_stored_and_sets_the_estimate_location(app, client):
    register(client)
    listing_id = list_home(client, latitude="42.0400", longitude="-93.6500")
    row = db(app).execute("SELECT latitude, longitude FROM listings WHERE id = ?", (listing_id,)).fetchone()
    assert (row["latitude"], row["longitude"]) == (42.04, -93.65)
    page = client.get(f"/homes/{listing_id}").data.decode()
    assert 'data-lat="42.04"' in page and 'data-exact="1"' in page


def test_pin_outside_ames_or_half_a_pin_is_rejected(client):
    register(client)
    r = post(client, "/sell", {**LISTING, "latitude": "48.85", "longitude": "2.35"}, content_type="multipart/form-data")
    assert r.status_code == 200 and b"Place the pin inside Ames" in r.data
    r = post(client, "/sell", {**LISTING, "latitude": "42.04", "longitude": ""}, content_type="multipart/form-data")
    assert r.status_code == 200 and b"Place the pin again" in r.data


def test_unpinned_homes_sit_near_their_neighborhood(client):
    register(client)
    listing_id = list_home(client, neighborhood="Stone_Brook")
    page = client.get(f"/homes/{listing_id}").data.decode()
    assert 'data-exact="0"' in page and "Somewhere in Stone Brook" in page


def test_neighborhood_lookup_from_a_pin():
    import housing
    from ownly import get_valuer
    X, _, _ = housing.load()
    valuer = get_valuer()
    for hood in ("North_Ames", "College_Creek", "Old_Town", "Northridge_Heights"):
        houses = X[X["Neighborhood"] == hood]
        lat, lon = houses["Latitude"].median(), houses["Longitude"].median()
        assert valuer.neighborhood_at(lat, lon)["neighborhood"] == hood


def test_neighborhood_api(client):
    assert client.get("/api/neighborhood?lat=42.03&lng=-93.64").get_json()["ok"]
    assert client.get("/api/neighborhood?lat=40.7&lng=-74.0").status_code == 400
    assert client.get("/api/neighborhood?lat=nan&lng=1").status_code == 400


def test_map_data_cannot_break_out_of_its_script_tag(client):
    register(client)
    list_home(client, title="</script><script>alert(1)</script>")
    page = client.get("/homes").data.decode()
    assert "</script><script>alert(1)" not in page
    assert '"title": "\\u003c/script\\u003e' in page


def test_old_database_gets_the_location_columns(tmp_path):
    import sqlite3 as sq
    from ownly.db import SCHEMA
    path = tmp_path / "ownly.sqlite3"
    first_release = "\n".join(line for line in SCHEMA.read_text().splitlines()
                               if not line.strip().startswith(("latitude", "longitude")))
    conn = sq.connect(path)
    conn.executescript(first_release)
    conn.close()
    assert "latitude" not in {r[1] for r in sq.connect(path).execute("PRAGMA table_info(listings)")}
    create_app({"INSTANCE": tmp_path, "TESTING": True})
    columns = {r[1] for r in sq.connect(path).execute("PRAGMA table_info(listings)")}
    assert {"latitude", "longitude"} <= columns


def test_csp_allows_the_map_tiles_only(client):
    csp = client.get("/homes").headers["Content-Security-Policy"]
    assert "https://tile.openstreetmap.org" in csp and "script-src 'self';" in csp


def test_hidden_files_are_never_served(app, client):
    from pathlib import Path
    hidden = Path(app.static_folder) / ".hidden-test"
    hidden.mkdir(exist_ok=True)
    (hidden / "state.json").write_text("{}")
    try:
        assert client.get("/static/.hidden-test/state.json").status_code == 404
        assert client.get("/static/ownly.css").status_code == 200
    finally:
        (hidden / "state.json").unlink()
        hidden.rmdir()


def test_server_settings_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OWNLY_INSTANCE", str(tmp_path / "data"))
    monkeypatch.setenv("OWNLY_HTTPS", "1")
    monkeypatch.setenv("OWNLY_PROXIES", "1")
    app = create_app({"TESTING": True})
    assert app.config["DATABASE"].startswith(str(tmp_path / "data"))
    assert app.config["SESSION_COOKIE_SECURE"]
    client = app.test_client()
    r = client.get("/", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["Strict-Transport-Security"] == "max-age=31536000"
    from werkzeug.middleware.proxy_fix import ProxyFix
    assert isinstance(app.wsgi_app, ProxyFix) and app.wsgi_app.x_for == 1
