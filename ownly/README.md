# Ownly

Homes sold by their owners in Ames, Iowa. Sellers list a home with its details, photos and how
buyers can reach them; buyers browse, filter, and message sellers. Every listing shows the
**Ownly estimate**: the XGBoost model from `../train.py`, moved from 2010 to today with the
Ames house price index (`../price_index.py`).

## Run it

From `house-price-models/`:

```bash
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m ownly seed      # optional: 12 example listings built from real Ames sales
.venv/bin/python -m ownly           # http://127.0.0.1:8720
```

Data lives in `ownly/instance/` (owner-only permissions, not in git): the SQLite database,
uploaded photos, and the session secret. Delete the folder to start over.

Tests: `.venv/bin/python -m pytest` (34 tests: accounts, CSRF, rate limits, ownership, messaging,
uploads, escaping, the estimate, the map).

## Deploy to DigitalOcean

On a $6/month Droplet (Ubuntu 24.04, 1 GB) with your SSH key, from `house-price-models/` on your computer:

```bash
ssh root@SERVER_IP 'bash -s' -- SITE < deploy/setup.sh
```

`SITE` is the name for the HTTPS certificate: your own domain pointed at the Droplet, or the IP with
dashes plus `.sslip.io` (for `164.92.1.2` that is `164-92-1-2.sslip.io`). The script installs Caddy
(HTTPS, renewed automatically), Python 3.13 and the packages, runs Ownly under gunicorn as an unprivileged
`ownly` user with systemd hardening, turns on the firewall (SSH, HTTP, HTTPS only) and automatic security
updates, and adds the example listings on the first run. Run the same command again to update after a push;
the data in `/var/lib/ownly` is kept.

Useful on the server: `journalctl -u ownly -f` (app log), `systemctl restart ownly`,
`sqlite3 /var/lib/ownly/ownly.sqlite3` (data).

## What it does

| Page | Who | What |
|---|---|---|
| `/` | everyone | Search, newest listings, link to the estimate |
| `/homes` | everyone | Browse with neighborhood, price, bedroom and bathroom filters; sort by price or by how far below the estimate a home is priced; a map with every home as a price tag |
| `/homes/<id>` | everyone | Photos, details, the Ownly estimate against the asking price, a map, contact box |
| `/estimate` | everyone | "What is my home worth?", live as you type (`/api/estimate` returns JSON) |
| `/register`, `/login` | everyone | Email and password. The email is only checked for its shape, as asked |
| `/sell`, `/homes/<id>/edit` | signed in | List or edit a home with a live estimate beside the form; a map pin that also sets the neighborhood; up to 8 photos; status (for sale, under offer, sold) |
| `/messages` | signed in | One conversation per buyer and listing, unread counts in the bar |
| `/account` | signed in | Name and phone, change password, delete the account and everything in it |

**The map.** Sellers can drop a pin; Ownly names the neighborhood from the nearest recorded sales
(`/api/neighborhood`) and the estimate uses the pin's coordinates. Homes without a pin appear near the
middle of their neighborhood, drawn as outlined tags on the browse map and as a circle on the listing page.
Leaflet is served from `static/vendor/`; the street map comes from OpenStreetMap's tile server.

One account does both: anyone signed in can list a home and contact sellers. A seller's phone
and email show only to signed-in buyers, and only if the seller ticks the box; otherwise buyers
reach them through Ownly messages.

## Security

- Passwords are hashed with scrypt (Werkzeug). Failed sign-ins take the same time whether or
  not the email exists.
- Sessions: the cookie holds a random token, the database only its SHA-256. A new token on every
  sign-in; logging out deletes it server-side; changing the password logs out other devices.
  Cookies are `HttpOnly` and `SameSite=Lax`.
- Every POST needs the per-session CSRF token.
- Rate limits: 5 failed sign-ins per email and 30 per IP in 15 minutes, 10 sign-ups per IP per
  hour, 30 messages per user per hour, 20 listings per user per day.
- Only owners can edit, change the status of, or delete a listing; only the two people in a
  conversation can read it (others get a 404).
- Photos must really be JPEG, PNG or WebP (checked from the file's bytes, not its name), at most
  8 MB each, stored under random names and served with `nosniff` and a sandbox CSP.
- All pages send a strict Content-Security-Policy (no inline scripts or styles), `X-Frame-Options:
  DENY`, `nosniff`, and `Referrer-Policy: same-origin`. Templates escape all user text.
- SQL is parameterised throughout.

## Before putting it on the internet

These are deliberately left for the launch step:

- **TLS, proxy and server** are handled by `deploy/` (Caddy, `OWNLY_HTTPS=1`, `OWNLY_PROXIES=1`,
  gunicorn). Anywhere else, set those two variables the same way.
- **Email.** Addresses are not verified (as requested), so anyone can sign up with someone else's
  address, and there is no password reset by email.
- **Photos** keep their EXIF metadata, which can include where a photo was taken.
- **The estimate endpoint** is open and takes about 25 ms per call; rate-limit it at the proxy.
- **Map tiles.** OpenStreetMap's own tile server is for light use only. A public site needs a tile
  provider with an account (for example MapTiler, Stadia Maps or Thunderforest) or self-hosted tiles;
  change `TILES` in `static/ownly.js` and the `img-src` host in `__init__.py`. Tile requests also tell
  the provider the visitor's IP address.
- **Backups** of `ownly/instance/`.
