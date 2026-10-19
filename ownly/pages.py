"""Home page, the estimate page and its JSON endpoint, and shared view helpers."""
from flask import Blueprint, jsonify, render_template, request, url_for

from . import db, forms, get_valuer

bp = Blueprint("pages", __name__)


# ---------------------------------------------------------------- template filters

def money(value) -> str:
    return f"${value:,.0f}" if value is not None else "–"


def money_short(value) -> str:
    if value is None:
        return "–"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M".replace(".00M", "M")
    return f"${value / 1000:,.0f}k"


def number(value) -> str:
    return f"{value:,.0f}"


FILTERS = {"money": money, "money_short": money_short, "number": number}


# ---------------------------------------------------------------- shared helpers

def neighborhoods() -> list[tuple[str, str]]:
    names = get_valuer().templates
    return sorted(((code, code.replace("_", " ")) for code in names), key=lambda pair: pair[1])


def hood_label(code: str) -> str:
    return code.replace("_", " ")


def with_estimates(rows) -> list[dict]:
    """Listing rows as dicts, each with today's Ownly estimate and its first photo."""
    valuer = get_valuer()
    ids = [r["id"] for r in rows]
    covers = {}
    if ids:
        marks = ",".join("?" * len(ids))
        for p in db.all_(f"SELECT listing_id, filename FROM photos WHERE listing_id IN ({marks}) "
                         f"ORDER BY position, id", *ids):
            covers.setdefault(p["listing_id"], p["filename"])
    out = []
    for r in rows:
        item = dict(r)
        est = valuer.estimate(r["model_price"])
        item["estimate"] = est
        item["vs_estimate"] = r["price"] / est["value"] - 1
        item["cover"] = covers.get(r["id"])
        item["hood_label"] = hood_label(r["neighborhood"])
        item["hue"] = sum(map(ord, r["neighborhood"])) % 6
        item["baths"] = f"{r['full_baths'] + 0.5 * r['half_baths']:g}"
        item["lat"], item["lng"], item["exact"] = valuer.place(r)
        out.append(item)
    return out


def map_pins(items: list[dict]) -> list[dict]:
    """What the browse map needs per home. Rendered with |tojson, which escapes < > &."""
    return [{
        "id": i["id"], "lat": round(i["lat"], 6), "lng": round(i["lng"], 6), "exact": i["exact"],
        "price": money_short(i["price"]), "full_price": money(i["price"]), "title": i["title"],
        "facts": f"{i['bedrooms']} bd · {i['baths']} ba · {i['living_area']:,} sq ft", "place": i["hood_label"],
        "url": url_for("listings.detail", listing_id=i["id"]),
        "photo": url_for("listings.photo", name=i["cover"]) if i["cover"] else None,
        "status": i["status"], "example": bool(i["is_example"]),
    } for i in items]


def map_context() -> dict:
    """Neighborhood middles and the covered area, for the location picker."""
    valuer = get_valuer()
    return {"area": valuer.area,
            "centroids": {h: [round(lat, 6), round(lon, 6)] for h, (lat, lon) in valuer.centroids.items()}}


# ---------------------------------------------------------------- pages

@bp.get("/")
def home():
    rows = db.all_("SELECT * FROM listings WHERE status = 'active' ORDER BY is_example, created_at DESC, id DESC LIMIT 6")
    count = db.one("SELECT COUNT(*) AS n FROM listings WHERE status = 'active'")["n"]
    return render_template("home.html", listings=with_estimates(rows), count=count,
                           neighborhoods=neighborhoods(), today=get_valuer().today())


@bp.get("/estimate")
def estimate_page():
    fields = forms.home_fields(neighborhoods(), get_valuer().area)
    submitted = bool(request.args)
    values, errors = forms.parse(fields, request.args) if submitted else ({f.name: f.default for f in fields}, {})
    result = None
    if submitted and not errors:
        result = _estimate(values)
    return render_template("estimate.html", fields=fields, values=values, errors=errors, result=result,
                           valuer=get_valuer(), map_info=map_context())


@bp.get("/api/estimate")
def estimate_api():
    values, errors = forms.parse(forms.home_fields(neighborhoods(), get_valuer().area), request.args)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    return jsonify({"ok": True, **_estimate(values)})


@bp.get("/api/neighborhood")
def neighborhood_api():
    """Which neighborhood a map pin falls in, judged by the nearest recorded sales."""
    try:
        lat, lon = float(request.args["lat"]), float(request.args["lng"])
    except (KeyError, ValueError, OverflowError):
        return jsonify({"ok": False, "error": "Send lat and lng."}), 400
    valuer = get_valuer()
    if not valuer.in_area(lat, lon):
        return jsonify({"ok": False, "error": "Ownly only covers Ames, Iowa."}), 400
    found = valuer.neighborhood_at(lat, lon)
    return jsonify({"ok": True, **found, "label": hood_label(found["neighborhood"])})


def _estimate(values: dict) -> dict:
    valuer = get_valuer()
    inputs = forms.valuer_inputs(values)
    _, notes = valuer.house_row(inputs)
    est = valuer.estimate(valuer.model_prices([inputs])[0])
    return {k: (float(v) if isinstance(v, float) else v) for k, v in est.items()} | {"notes": notes}
