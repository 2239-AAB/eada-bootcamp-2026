"""The Ownly estimate: XGBoost's mid-2010 price, moved to today with the Ames price index.

house_row() builds the model's inputs the same way the report's calculator
does in JavaScript (calculator.py), so both give the same price for a house.
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import models  # noqa: E402,F401  first: it may restart Python so XGBoost finds OpenMP
import calculator  # noqa: E402
import housing  # noqa: E402
import price_index  # noqa: E402

MODEL_YEAR_LIMIT = 2010  # the newest house the model has seen


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)  # JavaScript's Math.round


class Valuer:
    def __init__(self, model_key: str = calculator.MODEL_KEY):
        X, _, _ = housing.load()
        self.columns = list(X.columns)
        self.templates = calculator.neighborhood_templates(X)
        self.neighborhood_sales = X["Neighborhood"].value_counts().to_dict()
        garage = X[X["Garage_Cars"] > 0]
        self.area_per_car = float(np.round((garage["Garage_Area"] / garage["Garage_Cars"]).median()))
        self.typical = {k: (float(X[c].quantile(0.01)), float(X[c].quantile(0.99))) for k, c in
                        {"gla": "Gr_Liv_Area", "bsmt": "Total_Bsmt_SF", "lot": "Lot_Area"}.items()}
        self.limits = {k: (float(X[c].min()), float(X[c].max())) for k, c in
                       {"gla": "Gr_Liv_Area", "bsmt": "Total_Bsmt_SF", "fin": "BsmtFin_SF_1",
                        "lot": "Lot_Area"}.items()}
        self.model = joblib.load(ROOT / "results" / "models" / f"{model_key}.joblib")
        results = json.loads((ROOT / "results" / "results.json").read_text())
        tp = results["test_points"]
        pct = np.asarray(tp["predicted"][model_key], float) / np.asarray(tp["actual"], float) - 1
        self.q10, self.q90 = float(np.quantile(pct, 0.10)), float(np.quantile(pct, 0.90))
        self.model_name = results["models"][model_key]["name"]
        self.hpi = price_index.load()

        # Where the 2,925 sales were: for placing homes and naming the neighborhood of a pin.
        self._lat = X["Latitude"].to_numpy(float)
        self._lon = X["Longitude"].to_numpy(float)
        self._hood = X["Neighborhood"].to_numpy()
        self.centroids = {h: (float(g["Latitude"].median()), float(g["Longitude"].median()))
                          for h, g in X.groupby("Neighborhood")}
        pad = 0.015  # about 1.5 km around the outermost sale
        self.area = {"south": float(self._lat.min()) - pad, "north": float(self._lat.max()) + pad,
                     "west": float(self._lon.min()) - pad, "east": float(self._lon.max()) + pad}

    # ------------------------------------------------------------ places
    def in_area(self, lat: float, lon: float) -> bool:
        a = self.area
        return a["south"] <= lat <= a["north"] and a["west"] <= lon <= a["east"]

    def neighborhood_at(self, lat: float, lon: float, k: int = 9) -> dict:
        """The neighborhood most of the nearest recorded sales belong to."""
        # Metres on a local flat projection; plenty accurate across one town.
        dy = (self._lat - lat) * 111_320
        dx = (self._lon - lon) * 111_320 * math.cos(math.radians(lat))
        dist = np.hypot(dx, dy)
        nearest = np.argsort(dist)[:k]
        names, counts = np.unique(self._hood[nearest], return_counts=True)
        return {"neighborhood": str(names[np.argmax(counts)]), "nearest_m": float(dist[nearest[0]]),
                "covered": bool(dist[nearest[0]] < 800)}

    def place(self, listing) -> tuple[float, float, bool]:
        """(lat, lon, exact): the seller's pin, or a stable spot near the neighborhood's middle."""
        if listing["latitude"] is not None and listing["longitude"] is not None:
            return float(listing["latitude"]), float(listing["longitude"]), True
        lat, lon = self.centroids[listing["neighborhood"]]
        # Spread unpinned homes a little so they don't sit on top of each other.
        angle = (listing["id"] * 2.399963) % (2 * math.pi)  # golden angle
        radius = 0.0012 + 0.0004 * (listing["id"] % 5)
        return lat + radius * math.sin(angle), lon + radius * math.cos(angle) * 1.35, False

    # ------------------------------------------------------------ the model
    def house_row(self, v: dict) -> tuple[dict, list[str]]:
        """Model inputs for one house, plus notes on anything clamped or unusual."""
        notes = []
        v = dict(v)
        if v["built"] > MODEL_YEAR_LIMIT:
            notes.append(f"Built after {MODEL_YEAR_LIMIT}: valued like a house built in {MODEL_YEAR_LIMIT}.")
        v["built"] = min(v["built"], MODEL_YEAR_LIMIT)
        v["remod"] = min(max(v["remod"], v["built"]), MODEL_YEAR_LIMIT)
        for key, label in (("gla", "living area"), ("bsmt", "basement area"), ("lot", "lot size")):
            lo, hi = self.typical[key]
            if v[key] < lo or v[key] > hi:
                notes.append(f"Few sales in the data have a {label} like this.")
        for key in ("gla", "bsmt", "lot"):
            lo, hi = self.limits[key]
            v[key] = min(max(v[key], lo), hi)
        v["fin"] = min(max(v["fin"], 0), v["bsmt"])
        if self.neighborhood_sales.get(v["hood"], 0) < 20:
            notes.append("Fewer than 20 sales in this neighborhood.")

        r = dict(self.templates[v["hood"]])
        style = calculator.STYLES[v["style"]]
        r["Neighborhood"] = v["hood"]
        r["House_Style"] = style["style"]
        r["MS_SubClass"] = style["new"] if v["built"] >= 1946 else style["old"]
        r["Gr_Liv_Area"] = v["gla"]
        r["First_Flr_SF"] = _round_half_up(v["gla"] * style["first"])
        r["Second_Flr_SF"] = v["gla"] - r["First_Flr_SF"]
        r["Low_Qual_Fin_SF"] = 0
        r["Total_Bsmt_SF"] = v["bsmt"]
        r["BsmtFin_SF_2"] = 0
        r["Bsmt_Unf_SF"] = v["bsmt"] - v["fin"]
        if v["bsmt"] == 0:
            r.update(Bsmt_Qual=0, Bsmt_Cond=0, Bsmt_Exposure=0, BsmtFin_Type_1=0, BsmtFin_Type_2=0,
                     Bsmt_Full_Bath=0, Bsmt_Half_Bath=0)
        else:
            r["Bsmt_Qual"] = r["Bsmt_Qual"] or 3
            r["Bsmt_Cond"] = r["Bsmt_Cond"] or 3
            r["Bsmt_Exposure"] = r["Bsmt_Exposure"] or 1
            r["BsmtFin_Type_1"] = (r["BsmtFin_Type_1"] if r["BsmtFin_Type_1"] >= 2 else 5) if v["fin"] > 0 else 1
            r["BsmtFin_Type_2"] = 1
        r["Lot_Area"] = v["lot"]
        r["Year_Built"] = v["built"]
        r["Year_Remod_Add"] = max(v["remod"], v["built"], 1950)
        r["Overall_Qual"], r["Overall_Cond"] = v["qual"], v["cond"]
        r["Kitchen_Qual"], r["Exter_Qual"] = v["kitchen"], v["exter"]
        r["Bedroom_AbvGr"] = v["beds"]
        r["TotRms_AbvGrd"] = min(14, max(v["beds"] + 2, _round_half_up(v["gla"] / 240)))
        r["Full_Bath"], r["Half_Bath"] = v["full"], v["half"]
        r["Garage_Cars"] = v["cars"]
        r["Garage_Area"] = v["cars"] * self.area_per_car
        if v["cars"] == 0:
            r.update(Garage_Type="No_Garage", Garage_Finish=0, Garage_Qual=0, Garage_Cond=0)
        elif r["Garage_Type"] == "No_Garage":
            r.update(Garage_Type="Attchd", Garage_Finish=1, Garage_Qual=3, Garage_Cond=3)
        r["Fireplaces"] = v["fire"]
        r["Fireplace_Qu"] = (r["Fireplace_Qu"] or 4) if v["fire"] > 0 else 0
        r["Central_Air"] = v["air"]
        if v.get("lat") is not None and v.get("lon") is not None:
            r["Latitude"], r["Longitude"] = v["lat"], v["lon"]
        r["Sale_Type"], r["Sale_Condition"] = "WD ", "Normal"
        r["Year_Sold"], r["Mo_Sold"] = price_index.BASE_YEAR, price_index.BASE_MONTH

        # The derived columns, as in housing.prepare().
        r["BsmtFin_SF_1"] = max(0, r["Total_Bsmt_SF"] - r["BsmtFin_SF_2"] - r["Bsmt_Unf_SF"])
        r["Lot_Frontage_Missing"] = 1 if r["Lot_Frontage"] == 0 else 0
        r["Total_SF"] = r["Total_Bsmt_SF"] + r["Gr_Liv_Area"]
        r["Total_Baths"] = r["Full_Bath"] + 0.5 * r["Half_Bath"] + r["Bsmt_Full_Bath"] + 0.5 * r["Bsmt_Half_Bath"]
        r["House_Age"] = max(0, r["Year_Sold"] - r["Year_Built"])
        r["Years_Since_Remodel"] = max(0, r["Year_Sold"] - r["Year_Remod_Add"])
        r["Porch_SF"] = (r["Wood_Deck_SF"] + r["Open_Porch_SF"] + r["Enclosed_Porch"]
                         + r["Three_season_porch"] + r["Screen_Porch"])
        r["Qual_x_Living_Area"] = r["Overall_Qual"] * r["Gr_Liv_Area"]
        return r, notes

    def model_prices(self, houses: list[dict]) -> list[float]:
        """Mid-2010 prices for several houses in one model call."""
        if not houses:
            return []
        frame = pd.DataFrame([self.house_row(v)[0] for v in houses], columns=self.columns)
        return [float(p) for p in self.model.predict(frame)]

    # ------------------------------------------------------------ the index
    def today(self) -> dict:
        """Index factor for the current quarter, worked out once a day."""
        today = date.today()
        if getattr(self, "_today", (None,))[0] != today:
            quarter = pd.Period(today, freq="Q")
            f = price_index.factor(str(quarter), self.hpi)
            f = {k: (float(v) if isinstance(v, float) else v) for k, v in f.items() if k != "growth_rates"}
            f["label"] = f"Q{quarter.quarter} {quarter.year}"
            f["latest_label"] = f"Q{f['latest'][-1]} {f['latest'][:4]}"
            f["growth"] = price_index.trailing_growth(self.hpi, 2)
            self._today = (today, f)
        return self._today[1]

    def estimate(self, model_price: float) -> dict:
        f = self.today()
        value = float(model_price) * f["factor"]
        return {"value": value, "low": value / (1 + self.q90), "high": value / (1 + self.q10),
                "model_price": float(model_price), "factor": f["factor"], "quarter": f["label"],
                "projected": f["projected"], "latest": f["latest_label"]}
