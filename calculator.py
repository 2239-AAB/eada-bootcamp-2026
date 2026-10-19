"""The report's price calculator: XGBoost exported to JavaScript, plus the price index.

The page has no Python, so the trained XGBoost model is written out as plain
trees and walked in the browser. build_spec() re-implements that walk in
Python and refuses to continue unless it reproduces the real model.
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import housing
import models
import price_index

ROOT = Path(__file__).parent
MODEL_KEY = "xgb"

QUALITY_10 = ["Very poor", "Poor", "Fair", "Below average", "Average", "Above average", "Good",
              "Very good", "Excellent", "Very excellent"]
QUALITY_5 = ["Poor", "Fair", "Typical", "Good", "Excellent"]
STYLES = {
    # House_Style, MS_SubClass when built 1946 or later / before, first-floor share of living area
    "one": {"label": "One story", "style": "One_Story", "new": "One_Story_1946_and_Newer_All_Styles",
            "old": "One_Story_1945_and_Older", "first": 1.0},
    "onehalf": {"label": "One and a half stories", "style": "One_and_Half_Fin",
                "new": "One_and_Half_Story_Finished_All_Ages", "old": "One_and_Half_Story_Finished_All_Ages",
                "first": 0.642},
    "two": {"label": "Two stories", "style": "Two_Story", "new": "Two_Story_1946_and_Newer",
            "old": "Two_Story_1945_and_Older", "first": 0.508},
}
DEFAULTS = {"hood": "North_Ames", "style": "one", "qual": 6, "cond": 5, "gla": 1450, "bsmt": 1000,
            "fin": 400, "built": 1973, "remod": 1973, "full": 2, "half": 0, "beds": 3, "cars": 2,
            "lot": 9500, "kitchen": 3, "exter": 3, "fire": 1, "air": 1}


# ---------------------------------------------------------------- model export

def export_model(estimator) -> dict:
    pipe = estimator.regressor_
    prep = pipe.named_steps["prep"]
    booster = pipe.named_steps["model"].get_booster()
    numeric = [c for name, _, cols in prep.transformers_ if name == "num" for c in cols]
    onehot = prep.named_transformers_["cat"]
    categorical = []
    for col, cats, rare in zip(onehot.feature_names_in_, onehot.categories_, onehot.infrequent_categories_):
        rare_set = set(rare) if rare is not None else set()
        categorical.append([col, [c for c in cats if c not in rare_set], rare is not None])

    trees = []
    for text in booster.get_dump(dump_format="json"):
        nodes = {}
        stack = [json.loads(text)]
        while stack:
            node = stack.pop()
            if "leaf" in node:
                nodes[node["nodeid"]] = [node["leaf"]]
            else:
                nodes[node["nodeid"]] = [int(node["split"][1:]), node["split_condition"], node["yes"], node["no"]]
                stack.extend(node["children"])
        trees.append([nodes[i] for i in range(max(nodes) + 1)])

    config = json.loads(booster.save_config())
    scale = estimator.transformer_.named_steps["scale"]
    return {"num": numeric, "cat": categorical, "trees": trees,
            "base": float(config["learner"]["learner_model_param"]["base_score"].strip("[]")),
            "mu": float(scale.mean_[0]), "sd": float(scale.scale_[0])}


def encode(spec: dict, row: dict) -> np.ndarray:
    """Model inputs for one prepared row, exactly as the page builds them."""
    z = [row[c] for c in spec["num"]]
    for col, cats, has_rare in spec["cat"]:
        hit = cats.index(row[col]) if row[col] in cats else -1
        z.extend(1.0 if i == hit else 0.0 for i in range(len(cats)))
        if has_rare:
            z.append(1.0 if hit < 0 else 0.0)
    return np.asarray(z, dtype=np.float32)


def price(spec: dict, row: dict) -> float:
    z = encode(spec, row)
    margin = spec["base"]
    for tree in spec["trees"]:
        node = tree[0]
        while len(node) > 1:
            node = tree[node[2] if z[node[0]] < node[1] else node[3]]
        margin += node[0]
    return float(np.exp(margin * spec["sd"] + spec["mu"]))


# ---------------------------------------------------------------- the spec

def neighborhood_templates(X: pd.DataFrame) -> dict:
    """A typical house per neighborhood: median numbers, most common categories."""
    numeric = X.select_dtypes(include=np.number).columns
    out = {}
    for hood, group in X.groupby("Neighborhood"):
        row = {c: float(np.round(group[c].median())) for c in numeric}
        row.update({c: group[c].mode()[0] for c in X.columns if c not in numeric})
        out[hood] = row
    return out


def build_spec(results: dict) -> dict:
    X, y, _ = housing.load()
    estimator = joblib.load(ROOT / "results" / "models" / f"{MODEL_KEY}.joblib")
    model = export_model(estimator)

    sample = X.sample(300, random_state=models.SEED)
    exported = np.array([price(model, row) for row in sample.to_dict("records")])
    reference = estimator.predict(sample)
    worst = float(np.max(np.abs(exported / reference - 1)))
    if worst > 1e-4:
        raise RuntimeError(f"Exported model drifts from XGBoost by {worst:.2%}")

    tp = results["test_points"]
    actual = np.asarray(tp["actual"], float)
    pct = np.asarray(tp["predicted"][MODEL_KEY], float) / actual - 1
    hpi = price_index.load()
    latest = hpi.index[-1]

    def bounds(col):
        s = X[col]
        return [float(s.min()), float(s.quantile(0.01)), float(s.quantile(0.99)), float(s.max())]

    hood_counts = X["Neighborhood"].value_counts()
    garage = X[X["Garage_Cars"] > 0]
    return {
        "model": model,
        "model_name": results["models"][MODEL_KEY]["name"],
        "parity": worst,
        "templates": neighborhood_templates(X),
        "hoods": sorted([[h, h.replace("_", " "), int(n)] for h, n in hood_counts.items()], key=lambda t: t[1]),
        "styles": STYLES,
        "defaults": DEFAULTS,
        "quality10": QUALITY_10,
        "quality5": QUALITY_5,
        "area_per_car": float(np.round((garage["Garage_Area"] / garage["Garage_Cars"]).median())),
        "bounds": {k: bounds(c) for k, c in {"gla": "Gr_Liv_Area", "bsmt": "Total_Bsmt_SF",
                                             "fin": "BsmtFin_SF_1", "lot": "Lot_Area",
                                             "built": "Year_Built", "beds": "Bedroom_AbvGr"}.items()},
        "error": {"q10": float(np.quantile(pct, 0.10)), "q90": float(np.quantile(pct, 0.90)),
                  "mape": results["models"][MODEL_KEY]["test"]["mape"], "n": int(len(pct))},
        "hpi": {
            "series": price_index.SERIES, "source": price_index.SOURCE,
            "quarters": [str(q) for q in hpi.index], "values": hpi.round(2).tolist(),
            "base": str(price_index.BASE), "base_year": price_index.BASE_YEAR,
            "base_month": price_index.BASE_MONTH, "latest": str(latest),
            "growth": {"1y": price_index.trailing_growth(hpi, 1), "2y": price_index.trailing_growth(hpi, 2),
                       "since_base": (hpi[latest] / hpi[price_index.BASE])
                       ** (4 / (latest - price_index.BASE).n) - 1},
        },
    }


# ---------------------------------------------------------------- page parts

def section(spec: dict, esc) -> str:
    d = spec["defaults"]
    hpi = spec["hpi"]
    g = hpi["growth"]

    def options(pairs, selected):
        return "".join(f'<option value="{esc(v)}"{" selected" if str(v) == str(selected) else ""}>{esc(t)}</option>'
                       for v, t in pairs)

    def number(id_, label, value, lo, hi, step=1, unit=""):
        unit_html = f'<span class="unit">{esc(unit)}</span>' if unit else ""
        return (f'<label class="field" for="{id_}"><span>{esc(label)}</span><span class="input-wrap">'
                f'<input id="{id_}" type="number" inputmode="numeric" value="{value}" min="{lo}" max="{hi}" step="{step}">'
                f'{unit_html}</span></label>')

    def select(id_, label, pairs, selected):
        return (f'<label class="field" for="{id_}"><span>{esc(label)}</span>'
                f'<select id="{id_}">{options(pairs, selected)}</select></label>')

    q10 = [(i + 1, f"{i + 1} · {n}") for i, n in enumerate(spec["quality10"])]
    q5 = [(i + 1, n) for i, n in enumerate(spec["quality5"])]
    hoods = [(h, f"{label}") for h, label, _ in spec["hoods"]]
    styles = [(k, v["label"]) for k, v in spec["styles"].items()]
    b = spec["bounds"]
    years = [(y, y) for y in range(2006, 2031)]
    quarters = [(q, f"Q{q}") for q in range(1, 5)]
    presets = [("1y", f"Last year {100 * g['1y']:.1f}%"), ("2y", f"Last 2 years {100 * g['2y']:.1f}%"),
               ("since_base", f"Since 2010 {100 * g['since_base']:.1f}%"), ("flat", "Flat 0%")]
    preset_html = "".join(
        f'<button type="button" class="chip" data-growth="{100 * (g[k] if k != "flat" else 0):.1f}">{esc(t)}</button>'
        for k, t in presets)

    form = f"""
<form class="calc-form" id="calc-form" autocomplete="off">
  <fieldset>
    <legend>The house</legend>
    <div class="fields">
      {select("calc-hood", "Neighborhood", hoods, d["hood"])}
      {select("calc-style", "Stories", styles, d["style"])}
      {number("calc-gla", "Living area above ground", d["gla"], int(b["gla"][0]), int(b["gla"][3]), 10, "sq ft")}
      {number("calc-bsmt", "Basement area", d["bsmt"], 0, int(b["bsmt"][3]), 10, "sq ft")}
      {number("calc-fin", "Finished part of basement", d["fin"], 0, int(b["fin"][3]), 10, "sq ft")}
      {number("calc-lot", "Lot size", d["lot"], int(b["lot"][0]), int(b["lot"][3]), 100, "sq ft")}
      {number("calc-built", "Year built", d["built"], int(b["built"][0]), 2010, 1)}
      {number("calc-remod", "Year remodeled (= built if never)", d["remod"], int(b["built"][0]), 2010, 1)}
      {select("calc-qual", "Overall quality", q10, d["qual"])}
      {select("calc-cond", "Overall condition", q10, d["cond"])}
      {select("calc-kitchen", "Kitchen quality", q5, d["kitchen"])}
      {select("calc-exter", "Exterior quality", q5, d["exter"])}
      {number("calc-beds", "Bedrooms", d["beds"], 0, 8, 1)}
      {number("calc-full", "Full bathrooms", d["full"], 0, 4, 1)}
      {number("calc-half", "Half bathrooms", d["half"], 0, 2, 1)}
      {number("calc-cars", "Garage (cars)", d["cars"], 0, 5, 1)}
      {number("calc-fire", "Fireplaces", d["fire"], 0, 4, 1)}
      {select("calc-air", "Central air", [(1, "Yes"), (0, "No")], d["air"])}
    </div>
  </fieldset>
  <fieldset>
    <legend>When</legend>
    <div class="fields fields-when">
      {select("calc-year", "Year", years, 2026)}
      {select("calc-quarter", "Quarter", quarters, 4)}
      <label class="field field-wide" for="calc-growth"><span>Growth after {esc(_quarter_label(hpi["latest"]))}, the latest published index</span>
        <span class="input-wrap"><input id="calc-growth" type="number" inputmode="decimal" value="{100 * g['2y']:.1f}" min="-10" max="15" step="0.1"><span class="unit">% a year</span></span></label>
    </div>
    <div class="chips" role="group" aria-label="Growth presets">{preset_html}</div>
  </fieldset>
</form>"""

    result = """
<div class="calc-result" aria-live="polite">
  <div class="calc-label" id="calc-when">Estimated price</div>
  <div class="calc-price" id="calc-price">–</div>
  <div class="calc-range" id="calc-range"></div>
  <dl class="calc-steps">
    <div><dt>Model price, as if sold mid-2010</dt><dd id="calc-base">–</dd></div>
    <div><dt id="calc-factor-label">Index change since mid-2010</dt><dd id="calc-factor">–</dd></div>
    <div><dt>Price per sq ft of living area</dt><dd id="calc-ppsf">–</dd></div>
  </dl>
  <p class="calc-flag" id="calc-flag" hidden></p>
  <p class="calc-basis" id="calc-basis"></p>
</div>"""

    chart = """
<figure class="hpi" id="hpi-figure">
  <figcaption><span class="hpi-title">Ames house price index</span>
    <span class="hpi-sub">FHFA all-transactions index, 1995 Q1 = 100. Dashed: projection at your growth rate.</span></figcaption>
  <div class="hpi-chart">
    <div class="hpi-y" id="hpi-y"></div>
    <div class="hpi-plot" id="hpi-plot" role="img" aria-label="Ames house price index by quarter">
      <div class="hpi-band" id="hpi-band"><span>Training sales<br>2006–2010</span></div>
      <svg viewBox="0 0 1000 300" preserveAspectRatio="none" aria-hidden="true">
        <path class="hpi-area" id="hpi-area"/><path class="hpi-line" id="hpi-line"/><path class="hpi-proj" id="hpi-proj"/>
        <line class="hpi-cross" id="hpi-cross" x1="-10" x2="-10" y1="0" y2="300"/>
      </svg>
      <span class="hpi-dot hpi-dot-base" id="hpi-dot-base"></span>
      <span class="hpi-dot hpi-dot-target" id="hpi-dot-target"></span>
      <span class="hpi-lab" id="hpi-lab-base"></span>
      <span class="hpi-lab hpi-lab-target" id="hpi-lab-target"></span>
    </div>
    <div class="hpi-x" id="hpi-x"></div>
  </div>
</figure>"""

    return f"""
<section id="calculator">
  <h2>Price a house in 2026</h2>
  <p class="note">Describe a house and pick a quarter. {esc(spec['model_name'])} prices it as if it sold in mid-2010,
  the end of the training data. The Ames house price index then moves that price to the quarter you chose.
  Quarters after {esc(_quarter_label(hpi['latest']))} are not published yet, so they extend the index at the growth
  rate you set. Everything you do not enter comes from a typical house in the chosen neighborhood.</p>
  <div class="calc">
    {form}
    {result}
  </div>
  {chart}
  <p class="note">The range covers 80% of the model's errors on the {spec['error']['n']} hold-out houses. It does not include
  the index adjustment, whose error cannot be measured without recent sales; expect the real uncertainty to be wider,
  more so the further the quarter is from 2010.</p>
</section>
<script type="application/json" id="calc-spec">{json.dumps(spec, separators=(",", ":")).replace("</", "<\\/")}</script>
"""


def _quarter_label(q: str) -> str:
    return f"Q{q[-1]} {q[:4]}"


STYLE = r"""
.calc { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 16px; align-items: start; }
.calc-form { display: grid; gap: 16px; background: var(--surface); border: 1px solid var(--rule); border-radius: 10px;
             padding: 18px; min-width: 0; }
.calc-form fieldset { border: 0; margin: 0; padding: 0; display: grid; gap: 12px; min-width: 0; }
.calc-form legend { font: 500 0.6875rem/1.4 var(--mono); letter-spacing: 0.08em; text-transform: uppercase;
                    color: var(--muted); padding: 0 0 10px; }
.fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px 14px; }
.field { display: grid; gap: 4px; font-size: 0.8125rem; color: var(--ink-2); min-width: 0; }
.field > span:first-child { line-height: 1.25; }
.field-wide { grid-column: 1 / -1; }
.input-wrap { display: flex; align-items: center; gap: 6px; }
.unit { font-size: 0.75rem; color: var(--muted); white-space: nowrap; }
.calc-form input, .calc-form select { font: 500 0.9375rem var(--body); color: var(--ink); background: var(--bg);
       border: 1px solid var(--axis); border-radius: 6px; padding: 7px 9px; width: 100%; min-width: 0;
       font-variant-numeric: tabular-nums; }
.calc-form input:focus-visible, .calc-form select:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.calc-form input[aria-invalid="true"] { border-color: var(--warn); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font: 500 0.8125rem var(--body); color: var(--accent-ink); background: transparent; border: 1px solid var(--rule);
        border-radius: 999px; padding: 5px 10px; cursor: pointer; }
.chip:hover { border-color: var(--accent); }
.chip[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
.chip:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.calc-form input:disabled { opacity: 0.5; }
.calc-result { position: sticky; top: calc(env(safe-area-inset-top, 0px) + 16px); background: var(--surface);
               border: 1px solid var(--rule); border-radius: 10px; padding: 20px; display: grid; gap: 10px; min-width: 0; }
.calc-label { font-size: 0.875rem; font-weight: 600; color: var(--ink-2); }
.calc-price { font: 650 clamp(2.25rem, 1.6rem + 2vw, 3.25rem)/1 var(--body); letter-spacing: -0.02em; color: var(--ink); }
.calc-range { font-size: 0.875rem; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.calc-steps { margin: 6px 0 0; display: grid; border-top: 1px solid var(--rule); }
.calc-steps > div { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--grid);
                    font-size: 0.8125rem; }
.calc-steps dt { color: var(--ink-2); }
.calc-steps dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.calc-flag { margin: 0; font-size: 0.8125rem; color: var(--ink); background: var(--warn-wash); border-radius: 6px;
             padding: 8px 10px; }
.calc-flag b { font-weight: 650; }
.calc-basis { margin: 0; font-size: 0.75rem; color: var(--muted); }

.hpi { margin: 0; background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; padding: 16px 18px 12px;
       display: grid; gap: 10px; min-width: 0; }
.hpi figcaption { display: grid; gap: 2px; }
.hpi-title { font-weight: 650; font-size: 0.9375rem; }
.hpi-sub { font-size: 0.8125rem; color: var(--muted); }
.hpi-chart { display: grid; grid-template-columns: 2.75rem minmax(0, 1fr); grid-template-rows: 240px auto; }
.hpi-y { position: relative; grid-row: 1; grid-column: 1; }
.hpi-y span { position: absolute; right: 8px; transform: translateY(50%); font-size: 0.75rem; color: var(--muted);
              font-variant-numeric: tabular-nums; }
.hpi-plot { position: relative; grid-row: 1; grid-column: 2; border-left: 1px solid var(--axis);
            border-bottom: 1px solid var(--axis); touch-action: pan-y; }
.hpi-plot svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.hpi-x { position: relative; grid-row: 2; grid-column: 2; height: 22px; }
.hpi-x span { position: absolute; top: 5px; transform: translateX(-50%); font-size: 0.75rem; color: var(--muted);
              font-variant-numeric: tabular-nums; white-space: nowrap; }
.hpi-grid { position: absolute; left: 0; right: 0; height: 1px; background: var(--grid); }
.hpi-band { position: absolute; top: 0; bottom: 0; background: var(--accent-wash); border-radius: 2px; }
.hpi-band span { position: absolute; top: 6px; left: 50%; transform: translateX(-50%); font-size: 0.6875rem; line-height: 1.2;
                 color: var(--ink-2); text-align: center; white-space: nowrap; }
.hpi-area { fill: var(--accent); fill-opacity: 0.08; stroke: none; }
.hpi-line { fill: none; stroke: var(--accent); stroke-width: 2; vector-effect: non-scaling-stroke; stroke-linejoin: round; }
.hpi-proj { fill: none; stroke: var(--accent); stroke-width: 2; stroke-dasharray: 5 4; vector-effect: non-scaling-stroke; }
.hpi-cross { stroke: var(--ink-2); stroke-width: 1; vector-effect: non-scaling-stroke; opacity: 0.6; }
.hpi-dot { position: absolute; width: 10px; height: 10px; border-radius: 50%; transform: translate(-50%, -50%);
           box-shadow: 0 0 0 2px var(--surface); background: var(--accent); pointer-events: none; }
.hpi-dot-base { background: var(--surface); border: 2px solid var(--accent); }
.hpi-lab { position: absolute; font-size: 0.75rem; font-weight: 600; color: var(--ink-2); white-space: nowrap;
           pointer-events: none; transform: translate(-50%, -100%); margin-top: -10px; }
.hpi-lab-target { color: var(--ink); }

@media (max-width: 820px) {
  .calc { grid-template-columns: minmax(0, 1fr); }
  .calc-result { position: static; order: -1; }
}
@media (max-width: 640px) {
  .fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .hpi-chart { grid-template-rows: 200px auto; }
}
"""

SCRIPT = r"""
(() => {
  const specEl = document.getElementById('calc-spec');
  if (!specEl) return;
  const S = JSON.parse(specEl.textContent);
  const M = S.model;
  const $ = (id) => document.getElementById(id);
  const usd = (v) => '$' + Math.round(v).toLocaleString('en-US');
  const usdK = (v) => '$' + (Math.round(v / 1000)).toLocaleString('en-US') + 'k';
  const qLabel = (q) => 'Q' + q.slice(-1) + ' ' + q.slice(0, 4);

  // ---- the model: same steps as housing.prepare() and calculator.price()
  function derive(r) {
    r.BsmtFin_SF_1 = Math.max(0, r.Total_Bsmt_SF - r.BsmtFin_SF_2 - r.Bsmt_Unf_SF);
    r.Lot_Frontage_Missing = r.Lot_Frontage === 0 ? 1 : 0;
    r.Total_SF = r.Total_Bsmt_SF + r.Gr_Liv_Area;
    r.Total_Baths = r.Full_Bath + 0.5 * r.Half_Bath + r.Bsmt_Full_Bath + 0.5 * r.Bsmt_Half_Bath;
    r.House_Age = Math.max(0, r.Year_Sold - r.Year_Built);
    r.Years_Since_Remodel = Math.max(0, r.Year_Sold - r.Year_Remod_Add);
    r.Porch_SF = r.Wood_Deck_SF + r.Open_Porch_SF + r.Enclosed_Porch + r.Three_season_porch + r.Screen_Porch;
    r.Qual_x_Living_Area = r.Overall_Qual * r.Gr_Liv_Area;
    return r;
  }
  function encode(r) {
    const z = M.num.map((c) => Math.fround(r[c]));
    for (const [col, cats, hasRare] of M.cat) {
      const hit = cats.indexOf(r[col]);
      for (let i = 0; i < cats.length; i++) z.push(i === hit ? 1 : 0);
      if (hasRare) z.push(hit < 0 ? 1 : 0);
    }
    return z;
  }
  function priceRow(r) {
    const z = encode(r);
    let margin = M.base;
    for (const tree of M.trees) {
      let node = tree[0];
      while (node.length > 1) node = tree[z[node[0]] < node[1] ? node[2] : node[3]];
      margin += node[0];
    }
    return Math.exp(margin * M.sd + M.mu);
  }
  window.housePrice = { priceRow, derive };

  // ---- form -> one prepared row
  const num = (id) => parseFloat($(id).value);
  function readInputs() {
    const v = {};
    for (const k of ['gla', 'bsmt', 'fin', 'lot', 'built', 'remod', 'beds', 'full', 'half', 'cars', 'fire'])
      v[k] = num('calc-' + k);
    for (const k of ['qual', 'cond', 'kitchen', 'exter', 'air']) v[k] = parseInt($('calc-' + k).value, 10);
    v.hood = $('calc-hood').value;
    v.style = $('calc-style').value;
    return v;
  }
  function clampInputs(v) {
    const notes = [];
    const fix = (k, lo, hi) => {
      const el = $('calc-' + k);
      const bad = !Number.isFinite(v[k]) || v[k] < lo || v[k] > hi;
      el.setAttribute('aria-invalid', bad ? 'true' : 'false');
      if (!Number.isFinite(v[k])) v[k] = parseFloat(el.defaultValue);
      v[k] = Math.min(hi, Math.max(lo, v[k]));
    };
    const B = S.bounds;
    fix('gla', B.gla[0], B.gla[3]); fix('bsmt', 0, B.bsmt[3]); fix('fin', 0, v.bsmt);
    fix('lot', B.lot[0], B.lot[3]); fix('built', B.built[0], 2010); fix('remod', v.built, 2010);
    fix('beds', 0, 8); fix('full', 0, 4); fix('half', 0, 2); fix('cars', 0, 5); fix('fire', 0, 4);
    const unusual = (k, label) => { if (v[k] < B[k][1] || v[k] > B[k][2]) notes.push(label); };
    unusual('gla', 'living area'); unusual('bsmt', 'basement area'); unusual('lot', 'lot size');
    return notes;
  }
  function houseRow(v) {
    const r = Object.assign({}, S.templates[v.hood]);
    const st = S.styles[v.style];
    r.Neighborhood = v.hood;
    r.House_Style = st.style;
    r.MS_SubClass = v.built >= 1946 ? st.new : st.old;
    r.Gr_Liv_Area = v.gla;
    r.First_Flr_SF = Math.round(v.gla * st.first);
    r.Second_Flr_SF = v.gla - r.First_Flr_SF;
    r.Low_Qual_Fin_SF = 0;
    r.Total_Bsmt_SF = v.bsmt;
    r.BsmtFin_SF_2 = 0;
    r.Bsmt_Unf_SF = v.bsmt - v.fin;
    if (v.bsmt === 0) {
      Object.assign(r, { Bsmt_Qual: 0, Bsmt_Cond: 0, Bsmt_Exposure: 0, BsmtFin_Type_1: 0, BsmtFin_Type_2: 0,
                         Bsmt_Full_Bath: 0, Bsmt_Half_Bath: 0 });
    } else {
      r.Bsmt_Qual = r.Bsmt_Qual || 3; r.Bsmt_Cond = r.Bsmt_Cond || 3; r.Bsmt_Exposure = r.Bsmt_Exposure || 1;
      r.BsmtFin_Type_1 = v.fin > 0 ? (r.BsmtFin_Type_1 >= 2 ? r.BsmtFin_Type_1 : 5) : 1;
      r.BsmtFin_Type_2 = 1;
    }
    r.Lot_Area = v.lot;
    r.Year_Built = v.built;
    r.Year_Remod_Add = Math.max(v.remod, v.built, 1950);
    r.Overall_Qual = v.qual; r.Overall_Cond = v.cond; r.Kitchen_Qual = v.kitchen; r.Exter_Qual = v.exter;
    r.Bedroom_AbvGr = v.beds;
    r.TotRms_AbvGrd = Math.min(14, Math.max(v.beds + 2, Math.round(v.gla / 240)));
    r.Full_Bath = v.full; r.Half_Bath = v.half;
    r.Garage_Cars = v.cars;
    r.Garage_Area = v.cars * S.area_per_car;
    if (v.cars === 0) Object.assign(r, { Garage_Type: 'No_Garage', Garage_Finish: 0, Garage_Qual: 0, Garage_Cond: 0 });
    else if (r.Garage_Type === 'No_Garage') Object.assign(r, { Garage_Type: 'Attchd', Garage_Finish: 1, Garage_Qual: 3, Garage_Cond: 3 });
    r.Fireplaces = v.fire;
    r.Fireplace_Qu = v.fire > 0 ? (r.Fireplace_Qu || 4) : 0;
    r.Central_Air = v.air;
    r.Sale_Type = 'WD '; r.Sale_Condition = 'Normal';
    r.Year_Sold = S.hpi.base_year; r.Mo_Sold = S.hpi.base_month;
    return derive(r);
  }

  // ---- the index, extended past the latest published quarter
  const H = S.hpi;
  const quarters = H.quarters, values = H.values;
  const firstYear = parseInt(quarters[0].slice(0, 4), 10), firstQ = parseInt(quarters[0].slice(-1), 10);
  const qIndex = (y, q) => (y - firstYear) * 4 + (q - firstQ);
  const qName = (i) => { const k = i + firstQ - 1; return (firstYear + Math.floor(k / 4)) + 'Q' + ((k % 4) + 1); };
  const latestI = quarters.length - 1;
  const baseI = quarters.indexOf(H.base);
  function indexAt(i, growth) {
    if (i <= latestI) return values[Math.max(0, i)];
    return values[latestI] * Math.pow(1 + growth, (i - latestI) / 4);
  }

  // ---- chart
  const plot = $('hpi-plot');
  function niceStep(span) {
    const raw = span / 5, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    return [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  }
  function drawChart(targetI, growth) {
    const endI = Math.max(targetI, latestI) + 2;
    const series = [];
    for (let i = 0; i <= endI; i++) series.push(indexAt(i, growth));
    const yMax = Math.max(...series) * 1.12;
    const step = niceStep(yMax);
    const top = Math.ceil(yMax / step) * step;
    const X = (i) => (i / endI) * 1000, Y = (v) => 300 - (v / top) * 300;
    const xp = (i) => (i / endI) * 100, yp = (v) => 100 - (v / top) * 100;
    let d = '';
    for (let i = 0; i <= latestI; i++) d += (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(values[i]).toFixed(1);
    $('hpi-line').setAttribute('d', d);
    $('hpi-area').setAttribute('d', d + 'L' + X(latestI).toFixed(1) + ' 300L0 300Z');
    let p = '';
    if (targetI > latestI) {
      p = 'M' + X(latestI).toFixed(1) + ' ' + Y(values[latestI]).toFixed(1);
      for (let i = latestI + 1; i <= targetI; i++) p += 'L' + X(i).toFixed(1) + ' ' + Y(indexAt(i, growth)).toFixed(1);
    }
    $('hpi-proj').setAttribute('d', p);
    // grid and axes
    plot.querySelectorAll('.hpi-grid').forEach((g) => g.remove());
    const yAxis = $('hpi-y'); yAxis.replaceChildren();
    for (let v = 0; v <= top + 1e-9; v += step) {
      const g = document.createElement('span'); g.className = 'hpi-grid'; g.style.top = yp(v) + '%';
      plot.insertBefore(g, plot.firstChild);
      const t = document.createElement('span'); t.textContent = String(Math.round(v)); t.style.bottom = (100 - yp(v)) + '%';
      yAxis.appendChild(t);
    }
    const xAxis = $('hpi-x'); xAxis.replaceChildren();
    const lastYear = parseInt(qName(endI).slice(0, 4), 10);
    const yearStep = plot.clientWidth < 420 ? 10 : 5;
    for (let y = Math.ceil((firstYear + 1) / 5) * 5; y <= lastYear; y += yearStep) {
      const t = document.createElement('span'); t.textContent = String(y); t.style.left = xp(qIndex(y, 1)) + '%';
      xAxis.appendChild(t);
    }
    const band = $('hpi-band');
    band.style.left = xp(qIndex(2006, 1)) + '%';
    band.style.width = (xp(qIndex(2010, 3)) - xp(qIndex(2006, 1))) + '%';
    const place = (el, i, v) => { el.style.left = xp(i) + '%'; el.style.top = yp(v) + '%'; };
    place($('hpi-dot-base'), baseI, values[baseI]);
    place($('hpi-dot-target'), targetI, indexAt(targetI, growth));
    const lb = $('hpi-lab-base'), lt = $('hpi-lab-target');
    lb.textContent = 'Mid-2010: ' + values[baseI].toFixed(0);
    lt.textContent = qLabel(qName(targetI)) + ': ' + indexAt(targetI, growth).toFixed(0) + (targetI > latestI ? ' (projected)' : '');
    place(lb, baseI, values[baseI]); place(lt, targetI, indexAt(targetI, growth));
    // keep the target label inside the plot
    lt.style.transform = 'translate(-50%, -100%)';
    const pr = plot.getBoundingClientRect(), r = lt.getBoundingClientRect();
    if (r.right > pr.right) lt.style.transform = 'translate(-100%, -100%)';
    lb.style.transform = 'translate(-50%, 0)'; lb.style.marginTop = '12px';
    plot._state = { endI, top, growth };
  }
  plot.addEventListener('pointermove', (e) => {
    const st = plot._state; if (!st) return;
    const rect = plot.getBoundingClientRect();
    const i = Math.max(0, Math.min(st.endI, Math.round((e.clientX - rect.left) / rect.width * st.endI)));
    const projected = i > latestI;
    const v = indexAt(i, st.growth);
    const cross = $('hpi-cross');
    cross.setAttribute('x1', (i / st.endI) * 1000); cross.setAttribute('x2', (i / st.endI) * 1000);
    const tipEl = document.getElementById('tip');
    if (!tipEl) return;
    tipEl.replaceChildren();
    const a = document.createElement('strong'); a.textContent = v.toFixed(1) + (projected ? ' (projected)' : '');
    const b = document.createElement('span'); b.textContent = qLabel(qName(i));
    const c = document.createElement('span'); c.textContent = '×' + (v / values[baseI]).toFixed(2) + ' vs mid-2010';
    tipEl.append(a, b, c);
    tipEl.hidden = false;
    tipEl.style.left = Math.min(window.innerWidth - tipEl.offsetWidth - 8, e.clientX + 14) + 'px';
    tipEl.style.top = Math.max(8, e.clientY - tipEl.offsetHeight - 14) + 'px';
  });
  plot.addEventListener('pointerleave', () => {
    $('hpi-cross').setAttribute('x1', -10); $('hpi-cross').setAttribute('x2', -10);
    const tipEl = document.getElementById('tip'); if (tipEl) tipEl.hidden = true;
  });

  // ---- tie it together
  function update() {
    const v = readInputs();
    const notes = clampInputs(v);
    const row = houseRow(v);
    const base = priceRow(row);
    const year = parseInt($('calc-year').value, 10), q = parseInt($('calc-quarter').value, 10);
    const targetI = qIndex(year, q);
    const projected = targetI > latestI;
    const growthEl = $('calc-growth');
    growthEl.disabled = !projected;
    let growth = parseFloat(growthEl.value);
    if (!Number.isFinite(growth)) growth = 0;
    growth = Math.min(15, Math.max(-10, growth)) / 100;
    document.querySelectorAll('.chip').forEach((c) =>
      c.setAttribute('aria-pressed', String(projected && Math.abs(parseFloat(c.dataset.growth) / 100 - growth) < 5e-4)));
    const factor = indexAt(targetI, growth) / values[baseI];
    const est = base * factor;
    const lo = est / (1 + S.error.q90), hi = est / (1 + S.error.q10);
    $('calc-when').textContent = 'Estimated price, ' + qLabel(qName(targetI)) + (projected ? ' (projected)' : '');
    $('calc-price').textContent = usd(Math.round(est / 1000) * 1000);
    $('calc-range').textContent = '80% range ' + usdK(lo) + ' – ' + usdK(hi);
    $('calc-base').textContent = usd(base);
    $('calc-factor-label').textContent = 'Index change, mid-2010 to ' + qLabel(qName(targetI));
    $('calc-factor').textContent = '×' + factor.toFixed(3);
    $('calc-ppsf').textContent = usd(est / v.gla);
    $('calc-basis').textContent = projected
      ? 'Index after ' + qLabel(H.latest) + ' projected at ' + (growth * 100).toFixed(1) + '% a year.'
      : 'Uses the published index for ' + qLabel(qName(targetI)) + '.';
    const flag = $('calc-flag');
    const flags = [];
    if (notes.length) flags.push('Few training houses have a ' + notes.join(', ') + ' like this, so this price is less reliable.');
    if (S.hoods.find((h) => h[0] === v.hood)[2] < 20) flags.push('Fewer than 20 sales in this neighborhood.');
    flag.hidden = !flags.length;
    flag.replaceChildren();
    if (flags.length) { const b = document.createElement('b'); b.textContent = 'Unusual input. '; flag.append(b, flags.join(' ')); }
    drawChart(targetI, growth);
  }

  $('calc-form').addEventListener('input', update);
  $('calc-form').addEventListener('change', update);
  $('calc-form').addEventListener('submit', (e) => e.preventDefault());
  document.querySelectorAll('.chip').forEach((c) => c.addEventListener('click', () => {
    $('calc-growth').value = c.dataset.growth; update();
  }));
  window.addEventListener('resize', () => update());
  update();
})();
"""
