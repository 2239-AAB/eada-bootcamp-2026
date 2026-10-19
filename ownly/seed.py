"""Example listings built from real hold-out sales, so a new Ownly isn't empty.

Each one is marked as an example on every page and can't be contacted. The
asking price is the house's real 2006-2010 sale price moved to today with the
Ames price index, so the gap to the Ownly estimate is the model's real error.
"""
import secrets

import pandas as pd
from sklearn.model_selection import train_test_split

import housing
import models

from . import db, forms, get_valuer, security

EXAMPLE_EMAIL = "examples@ownly.invalid"  # .invalid can never be a real mailbox
STYLE_OF = {"One_Story": "one", "One_and_Half_Fin": "onehalf", "Two_Story": "two"}
STYLE_WORD = {"one": "one-story", "onehalf": "1½-story", "two": "two-story"}


def _holdout() -> pd.DataFrame:
    X, y, _ = housing.load()
    _, X_test, _, y_test = train_test_split(X, y, test_size=0.2, stratify=pd.qcut(y, 5, labels=False),
                                            random_state=models.SEED)
    return X_test.assign(Sale_Price=y_test)


def _pick(frame: pd.DataFrame, count: int) -> pd.DataFrame:
    """Spread the examples over the price range, one per neighborhood where possible."""
    frame = frame[frame["House_Style"].isin(list(STYLE_OF))].sort_values("Sale_Price")
    edges = [round(i * len(frame) / count) for i in range(count + 1)]
    picked, seen = [], set()
    for lo, hi in zip(edges, edges[1:]):
        for idx, row in frame.iloc[lo:hi].sample(frac=1, random_state=models.SEED).iterrows():
            if row["Neighborhood"] not in seen:
                picked.append(idx)
                seen.add(row["Neighborhood"])
                break
    return frame.loc[picked[:count]]


def _listing(row, factor: float) -> dict:
    style = STYLE_OF[row["House_Style"]]
    hood = row["Neighborhood"].replace("_", " ")
    built, remod = int(row["Year_Built"]), int(row["Year_Remod_Add"])
    if remod <= built or (remod == 1950 and built < 1950):  # 1950 is the data's floor for "never"
        remod = built
    price = max(5_000, round(row["Sale_Price"] * factor / 5_000) * 5_000 - 100)
    return {
        "title": f"{int(row['Bedroom_AbvGr'])}-bed {STYLE_WORD[style]} home in {hood}",
        "address": f"{hood}, Ames, IA (example)",
        "neighborhood": row["Neighborhood"], "price": int(price), "style": style,
        "bedrooms": int(row["Bedroom_AbvGr"]), "full_baths": int(row["Full_Bath"]),
        "half_baths": int(row["Half_Bath"]), "living_area": int(row["Gr_Liv_Area"]),
        "basement_area": int(row["Total_Bsmt_SF"]),
        "basement_finished": int(row["BsmtFin_SF_1"] + row["BsmtFin_SF_2"]),
        "lot_area": int(row["Lot_Area"]), "year_built": built, "year_remodeled": remod,
        "garage_cars": int(row["Garage_Cars"]), "fireplaces": int(row["Fireplaces"]),
        "overall_quality": int(row["Overall_Qual"]), "overall_condition": int(row["Overall_Cond"]),
        "kitchen_quality": max(1, int(row["Kitchen_Qual"])), "exterior_quality": max(1, int(row["Exter_Qual"])),
        "central_air": int(row["Central_Air"]),
        "description": (f"An example listing made from a home that sold in Ames in {int(row['Year_Sold'])} "
                         f"for ${row['Sale_Price']:,.0f}. Its details come from the Ames housing data. The asking "
                         f"price is that sale price moved to today with the Ames house price index, so the gap to "
                         f"the Ownly estimate shows how far off the model was for this house."),
        "contact_name": "Ownly examples", "contact_phone": "", "show_phone": 0, "show_email": 0,
    }


def add_examples(count: int = 12) -> int:
    """Replace any existing examples with `count` new ones."""
    user = db.one("SELECT id FROM users WHERE email = ?", EXAMPLE_EMAIL)
    if user is None:
        # A password nobody knows: the examples account can never be signed into.
        user_id = db.run("INSERT INTO users (email, password_hash, name) VALUES (?, ?, ?)", EXAMPLE_EMAIL,
                         security.hash_password(secrets.token_urlsafe(32)), "Ownly examples")
    else:
        user_id = user["id"]
    db.run("DELETE FROM listings WHERE is_example = 1")

    valuer = get_valuer()
    factor = valuer.today()["factor"]
    listings = [_listing(row, factor) for _, row in _pick(_holdout(), count).iterrows()]
    prices = valuer.model_prices([forms.valuer_inputs(item) for item in listings])
    for item, model_price in zip(listings, prices):
        columns = list(item)
        db.run(f"INSERT INTO listings (user_id, is_example, model_price, {', '.join(columns)}) "
               f"VALUES (?, 1, ?, {', '.join('?' * len(columns))})", user_id, model_price, *item.values())
    return len(listings)
