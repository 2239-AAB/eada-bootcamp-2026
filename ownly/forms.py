"""Field definitions and validation for listings and the estimate form."""
import re
from dataclasses import dataclass
from datetime import date

import calculator

QUALITY_10 = [(i + 1, f"{i + 1} · {name}") for i, name in enumerate(calculator.QUALITY_10)]
QUALITY_5 = [(i + 1, name) for i, name in enumerate(calculator.QUALITY_5)]
STYLES = [(key, s["label"]) for key, s in calculator.STYLES.items()]
STATUSES = {"active": "For sale", "under_offer": "Under offer", "sold": "Sold"}
PHONE_SHAPE = re.compile(r"^[0-9+()\-.\s]{0,40}$")


@dataclass
class Field:
    name: str
    label: str
    kind: str = "int"        # int, float, text, longtext, choice, bool, hidden
    lo: float = 0
    hi: float = 0
    default: object = None
    choices: list | None = None
    required: bool = True
    hint: str = ""
    unit: str = ""


def _year() -> int:
    return date.today().year


def location_fields(area: dict) -> list[Field]:
    """The map pin. Optional: without it a home is shown somewhere in its neighborhood."""
    return [
        Field("latitude", "Latitude", "float", lo=area["south"], hi=area["north"], required=False),
        Field("longitude", "Longitude", "float", lo=area["west"], hi=area["east"], required=False),
    ]


def home_fields(neighborhoods: list[tuple[str, str]], area: dict | None = None) -> list[Field]:
    """What the model needs to price a house; shared by listings and the estimate page."""
    d = calculator.DEFAULTS
    return [*(location_fields(area) if area else []),
        Field("neighborhood", "Neighborhood", "choice", default=d["hood"], choices=neighborhoods),
        Field("style", "Stories", "choice", default=d["style"], choices=STYLES),
        Field("living_area", "Living area above ground", lo=200, hi=20_000, default=d["gla"], unit="sq ft"),
        Field("bedrooms", "Bedrooms", lo=0, hi=20, default=d["beds"]),
        Field("full_baths", "Full bathrooms", lo=0, hi=10, default=d["full"]),
        Field("half_baths", "Half bathrooms", lo=0, hi=10, default=d["half"]),
        Field("basement_area", "Basement area", lo=0, hi=20_000, default=d["bsmt"], unit="sq ft",
              hint="0 if there is no basement"),
        Field("basement_finished", "Finished part of the basement", lo=0, hi=20_000, default=d["fin"], unit="sq ft"),
        Field("lot_area", "Lot size", lo=500, hi=2_000_000, default=d["lot"], unit="sq ft"),
        Field("year_built", "Year built", lo=1800, hi=_year(), default=d["built"]),
        Field("year_remodeled", "Year remodeled", lo=1800, hi=_year(), default=None, required=False,
              hint="Leave empty if never remodeled"),
        Field("garage_cars", "Garage spaces", lo=0, hi=10, default=d["cars"], unit="cars"),
        Field("fireplaces", "Fireplaces", lo=0, hi=10, default=d["fire"]),
        Field("overall_quality", "Overall quality", "choice", default=d["qual"], choices=QUALITY_10),
        Field("overall_condition", "Overall condition", "choice", default=d["cond"], choices=QUALITY_10),
        Field("kitchen_quality", "Kitchen", "choice", default=d["kitchen"], choices=QUALITY_5),
        Field("exterior_quality", "Exterior", "choice", default=d["exter"], choices=QUALITY_5),
        Field("central_air", "Central air conditioning", "bool", default=1),
    ]


def listing_fields(neighborhoods: list[tuple[str, str]], area: dict) -> list[Field]:
    return [
        Field("title", "Headline", "text", lo=5, hi=100, hint="For example: Bright ranch near the park"),
        Field("address", "Street address", "text", lo=3, hi=160),
        Field("price", "Asking price", lo=1_000, hi=50_000_000, unit="USD"),
        *home_fields(neighborhoods, area),
        Field("description", "Description", "longtext", lo=0, hi=5_000, required=False, default=""),
        Field("contact_name", "Your name as buyers see it", "text", lo=1, hi=80),
        Field("contact_phone", "Phone", "text", lo=0, hi=40, required=False, default=""),
        Field("show_phone", "Show my phone number to signed-in buyers", "bool", default=0),
        Field("show_email", "Show my email address to signed-in buyers", "bool", default=0),
    ]


def parse(fields: list[Field], form) -> tuple[dict, dict]:
    """Clean values and per-field error messages."""
    values, errors = {}, {}
    for f in fields:
        raw = form.get(f.name, "")
        raw = raw.strip() if isinstance(raw, str) else raw
        if f.kind == "bool":
            values[f.name] = 1 if raw in ("1", "on", "true", "yes") else 0
            continue
        if raw == "" or raw is None:
            if f.required:
                errors[f.name] = "Required."
            values[f.name] = f.default if not f.required else raw
            continue
        if f.kind == "int":
            try:
                number = int(float(str(raw).replace(",", "")))
            except (ValueError, OverflowError):  # OverflowError: "inf"
                errors[f.name] = "Enter a whole number."
                values[f.name] = raw
                continue
            if not f.lo <= number <= f.hi:
                errors[f.name] = f"Enter a number from {f.lo:,} to {f.hi:,}."
            values[f.name] = number
        elif f.kind == "float":
            try:
                number = float(str(raw))
            except (ValueError, OverflowError):
                number = float("nan")
            if not (f.lo <= number <= f.hi):  # also false for nan and inf
                errors[f.name] = "Place the pin inside Ames."
                values[f.name] = None
            else:
                values[f.name] = number
        elif f.kind == "choice":
            allowed = {str(k): k for k, _ in f.choices}
            if str(raw) not in allowed:
                errors[f.name] = "Pick one of the options."
                values[f.name] = f.default
            else:
                values[f.name] = allowed[str(raw)]
        else:
            text = str(raw).replace("\r\n", "\n")
            if len(text) < f.lo:
                errors[f.name] = f"Use at least {f.lo} characters."
            elif len(text) > f.hi:
                errors[f.name] = f"Use at most {f.hi:,} characters."
            values[f.name] = text

    # Rules that involve two fields.
    if "basement_finished" in values and not errors.get("basement_finished") and not errors.get("basement_area"):
        if isinstance(values["basement_finished"], int) and values["basement_finished"] > values["basement_area"]:
            errors["basement_finished"] = "Can't be larger than the basement."
    if "year_remodeled" in values and isinstance(values.get("year_built"), int):
        remod = values["year_remodeled"]
        if remod in (None, ""):
            values["year_remodeled"] = values["year_built"]
        elif isinstance(remod, int) and remod < values["year_built"]:
            errors["year_remodeled"] = "Can't be before the year it was built."
    if "latitude" in values and (values["latitude"] is None) != (values.get("longitude") is None):
        errors["latitude"] = "Place the pin again."
        values["latitude"] = values["longitude"] = None
    if "contact_phone" in values and not PHONE_SHAPE.match(values["contact_phone"] or ""):
        errors["contact_phone"] = "Use digits, spaces and + ( ) - only."
    if values.get("show_phone") and not values.get("contact_phone"):
        errors["contact_phone"] = "Add a phone number, or untick “Show my phone number”."
    return values, errors


def valuer_inputs(values: dict) -> dict:
    """Map form values onto the estimator's short keys."""
    return {
        "hood": values["neighborhood"], "style": values["style"], "qual": values["overall_quality"],
        "cond": values["overall_condition"], "gla": values["living_area"], "bsmt": values["basement_area"],
        "fin": values["basement_finished"], "built": values["year_built"],
        "remod": values.get("year_remodeled") or values["year_built"], "full": values["full_baths"],
        "half": values["half_baths"], "beds": values["bedrooms"], "cars": values["garage_cars"],
        "lot": values["lot_area"], "kitchen": values["kitchen_quality"], "exter": values["exterior_quality"],
        "fire": values["fireplaces"], "air": values["central_air"],
        "lat": values.get("latitude"), "lon": values.get("longitude"),
    }


def listing_inputs(row) -> dict:
    """The estimator's inputs for a stored listing."""
    return valuer_inputs({k: row[k] for k in row.keys()})
