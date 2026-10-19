-- Ownly's database. Every statement is idempotent so it runs on each start.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    name          TEXT    NOT NULL DEFAULT '',
    phone         TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- The cookie carries a random token; only its SHA-256 is stored, so a copy of
-- the database cannot be used to sign in.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS listings (
    id                INTEGER PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status            TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'under_offer', 'sold')),
    is_example        INTEGER NOT NULL DEFAULT 0,
    title             TEXT    NOT NULL,
    address           TEXT    NOT NULL,
    neighborhood      TEXT    NOT NULL,
    price             INTEGER NOT NULL,
    style             TEXT    NOT NULL,
    bedrooms          INTEGER NOT NULL,
    full_baths        INTEGER NOT NULL,
    half_baths        INTEGER NOT NULL,
    living_area       INTEGER NOT NULL,
    basement_area     INTEGER NOT NULL,
    basement_finished INTEGER NOT NULL,
    lot_area          INTEGER NOT NULL,
    year_built        INTEGER NOT NULL,
    year_remodeled    INTEGER NOT NULL,
    garage_cars       INTEGER NOT NULL,
    overall_quality   INTEGER NOT NULL,
    overall_condition INTEGER NOT NULL,
    kitchen_quality   INTEGER NOT NULL,
    exterior_quality  INTEGER NOT NULL,
    fireplaces        INTEGER NOT NULL,
    central_air       INTEGER NOT NULL,
    latitude          REAL,                     -- the seller's pin; NULL means "somewhere in the neighborhood"
    longitude         REAL,
    description       TEXT    NOT NULL DEFAULT '',
    contact_name      TEXT    NOT NULL DEFAULT '',
    contact_phone     TEXT    NOT NULL DEFAULT '',
    show_phone        INTEGER NOT NULL DEFAULT 0,
    show_email        INTEGER NOT NULL DEFAULT 0,
    model_price       REAL    NOT NULL,          -- the model's mid-2010 price; the index moves it to today
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS listings_user ON listings(user_id);
CREATE INDEX IF NOT EXISTS listings_browse ON listings(status, created_at);

CREATE TABLE IF NOT EXISTS photos (
    id         INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    filename   TEXT    NOT NULL UNIQUE,
    position   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS photos_listing ON photos(listing_id, position);

-- One conversation per buyer per listing.
CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    buyer_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    seller_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (listing_id, buyer_id)
);
CREATE INDEX IF NOT EXISTS conversations_buyer ON conversations(buyer_id, updated_at);
CREATE INDEX IF NOT EXISTS conversations_seller ON conversations(seller_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body            TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    read_at         TEXT
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);

-- Recent attempts, for rate limits (sign-in failures, sign-ups, messages, listings).
CREATE TABLE IF NOT EXISTS attempts (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    key        TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS attempts_lookup ON attempts(kind, key, created_at);
