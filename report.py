"""Render results/results.json as a self-contained HTML report.

    .venv/bin/python report.py

Writes report.html (open it in any browser) and results/report_artifact.html,
the same page without the <html>/<head>/<body> shell, for publishing.
"""
import html
import json
import math
from pathlib import Path

import calculator

ROOT = Path(__file__).parent
RESULTS = ROOT / "results" / "results.json"

FEATURE_NAMES = {
    "Qual_x_Living_Area": "Quality × living area",
    "Total_SF": "Total floor area incl. basement",
    "Gr_Liv_Area": "Living area above ground",
    "Lot_Area": "Lot size",
    "Lot_Frontage": "Street frontage",
    "Overall_Qual": "Overall quality (1–10)",
    "Overall_Cond": "Overall condition (1–10)",
    "House_Age": "Age at sale",
    "Years_Since_Remodel": "Years since remodel",
    "Year_Built": "Year built",
    "Year_Remod_Add": "Year remodeled",
    "Neighborhood": "Neighborhood",
    "Total_Bsmt_SF": "Basement area",
    "BsmtFin_SF_1": "Finished basement area",
    "BsmtFin_Type_1": "Basement finish quality",
    "Bsmt_Qual": "Basement quality",
    "Bsmt_Exposure": "Basement walkout exposure",
    "First_Flr_SF": "First-floor area",
    "Second_Flr_SF": "Second-floor area",
    "Garage_Cars": "Garage size (cars)",
    "Garage_Area": "Garage area",
    "Garage_Finish": "Garage interior finish",
    "Kitchen_Qual": "Kitchen quality",
    "Exter_Qual": "Exterior quality",
    "Heating_QC": "Heating quality",
    "Fireplace_Qu": "Fireplace quality",
    "Fireplaces": "Fireplaces",
    "Total_Baths": "Bathrooms",
    "MS_Zoning": "Zoning",
    "MS_SubClass": "Dwelling type",
    "Bldg_Type": "Building type",
    "Sale_Condition": "Sale condition",
    "Sale_Type": "Sale type",
    "Central_Air": "Central air",
    "Functional": "Home functionality",
    "Condition_1": "Nearby roads or rail",
    "Foundation": "Foundation type",
    "Exterior_1st": "Exterior cladding",
    "Mas_Vnr_Area": "Masonry veneer area",
    "Porch_SF": "Porch and deck area",
    "Screen_Porch": "Screened porch area",
    "Longitude": "Longitude",
    "Latitude": "Latitude",
}

SHORT_NAMES = {"Linear regression": "Linear", "Neural network": "Neural net",
               "Stacked ensemble": "Stack", "Random forest": "Forest", "Decision tree": "Tree"}

STACK_MEMBER_NAMES = {"enet": "Elastic net", "rf": "Random forest", "xgb": "XGBoost",
                      "mlp": "Neural network"}


# ---------------------------------------------------------------- formatting

def esc(value) -> str:
    return html.escape(str(value), quote=True)


def money(x: float) -> str:
    return f"${x:,.0f}"


def kmoney(x: float) -> str:
    return f"${x / 1000:,.0f}k"


def secs(s: float) -> str:
    if s < 1:
        return f"{s:.2f}\u00a0s"
    if s < 10:
        return f"{s:.1f}\u00a0s"
    if s < 90:
        return f"{s:.0f}\u00a0s"
    return f"{int(s // 60)}\u00a0min {s % 60:.0f}\u00a0s"


def signed(x: float, digits: int = 1) -> str:
    """+2.8 / −0.5 / 0.0, with a real minus sign and no negative zero."""
    text = f"{x:+.{digits}f}"
    if float(text) == 0:
        return f"{0:.{digits}f}"
    return text.replace("-", "\u2212")


def feature_name(col: str) -> str:
    return FEATURE_NAMES.get(col, col.replace("_", " ").capitalize())


def tip(*lines: str) -> str:
    """data-tip attribute: first line is the value, the rest describe it."""
    return f' data-tip="{esc(chr(10).join(lines))}"'


def nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    raw = (hi - lo) / target
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=10 * mag)
    first = math.ceil(lo / step) * step
    ticks = []
    t = first
    while t <= hi + 1e-9:
        ticks.append(round(t, 10))
        t += step
    return ticks


def padded_domain(values, pad: float, step: float) -> tuple[float, float]:
    lo, hi = min(values) - pad, max(values) + pad
    return math.floor(lo / step) * step, math.ceil(hi / step) * step


# ---------------------------------------------------------------- chart parts

def pos(v: float, lo: float, hi: float) -> float:
    return max(0.0, min(100.0, 100 * (v - lo) / (hi - lo)))


def row_chart(rows: list[dict], lo: float, hi: float, ticks: list[float], tick_fmt,
              axis_title: str, value_head: str = "") -> str:
    """Horizontal rows sharing one x scale. Each row: label, sub, marks, value, emph."""
    grid = "".join(f'<span class="gl" style="left:{pos(t, lo, hi):.2f}%"></span>' for t in ticks)
    cells = []
    if value_head:
        cells.append(f'<div class="rc-head rc-lead"></div><div class="rc-head"></div>'
                     f'<div class="rc-head rc-value">{esc(value_head)}</div>')
    for row in rows:
        emph = " is-emph" if row.get("emph") else ""
        sub = f'<span class="rc-sub">{esc(row["sub"])}</span>' if row.get("sub") else ""
        cells.append(
            f'<div class="rc-label{emph}"><span>{esc(row["label"])}</span>{sub}</div>'
            f'<div class="rc-track">{grid}{"".join(row["marks"])}</div>'
            f'<div class="rc-value{emph}">{row["value"]}</div>')
    tick_html = "".join(f'<span class="tk" style="left:{pos(t, lo, hi):.2f}%">{esc(tick_fmt(t))}</span>'
                        for t in ticks)
    cells.append(f'<div class="rc-lead"></div><div class="rc-axis">{tick_html}</div><div></div>'
                 f'<div class="rc-lead"></div><div class="rc-axis-title">{esc(axis_title)}</div><div></div>')
    return f'<div class="rc">{"".join(cells)}</div>'


def dot(v, lo, hi, cls, tip_attr, label="") -> str:
    aria = f' role="img" aria-label="{esc(label)}"' if label else ""
    return f'<span class="mk {cls}" style="left:{pos(v, lo, hi):.2f}%" tabindex="0"{aria}{tip_attr}></span>'


def span(a, b, lo, hi, cls) -> str:
    left, right = pos(a, lo, hi), pos(b, lo, hi)
    return f'<span class="{cls}" style="left:{left:.2f}%;width:{right - left:.2f}%"></span>'


def bar(v, lo, hi, cls, tip_attr) -> str:
    return (f'<span class="bar {cls}" style="width:{pos(v, lo, hi):.2f}%" tabindex="0"'
            f'{tip_attr}></span>')


def legend(items: list[tuple[str, str]]) -> str:
    return '<div class="legend">' + "".join(
        f'<span class="lg"><span class="lg-key {cls}"></span>{esc(text)}</span>'
        for cls, text in items) + "</div>"


def data_table(head: list[str], rows: list[list[str]], caption: str) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return (f'<details class="twin"><summary>Show the numbers</summary>'
            f'<div class="scroll"><table class="plain"><caption>{esc(caption)}</caption>'
            f'<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div></details>')


# ---------------------------------------------------------------- the page

def build(r: dict) -> tuple[str, str]:
    M, B = r["models"], r["bootstrap"]
    data = r["data"]
    winner = r["winner"]
    W = M[winner]
    order = sorted(M, key=lambda k: M[k]["cv"]["rmsle_mean"])
    order = [k for k in order if k != "baseline"] + ["baseline"]
    contenders = order[:-1]
    runner = contenders[1]
    R = M[runner]
    n_test = data["test_rows"]
    base = M["baseline"]

    def standing(k: str) -> tuple[str, str]:
        if k == winner:
            return "best", "Best on CV"
        if k == "baseline":
            return "ref", "Reference"
        lo, hi = B[k]["rmsle_diff_vs_winner_ci"]
        if hi < 0:
            return "ahead", "Ahead on hold-out"
        if lo <= 0:
            return "tied", "Tied on hold-out"
        return "behind", "Behind"

    def pill(k: str) -> str:
        cls, text = standing(k)
        return f'<span class="pill pill-{cls}">{esc(text)}</span>'

    # ------------------------------------------------------------ header
    years = data.get("years_sold", [2006, 2010])
    title = "Ames House Price Models"
    d_lo, d_hi = B[runner]["rmsle_diff_vs_winner_ci"]
    runner_tied = d_lo <= 0 <= d_hi
    speed = W["fit_seconds"] / max(R["fit_seconds"], 1e-9)
    if runner_tied and speed >= 3:
        headline = (f"{R['name']} matches the {W['name'].lower()} at {R['test']['mape']:.1f}% typical error "
                    f"and trains {speed:.0f}× faster")
    else:
        headline = f"{W['name']} prices unseen houses to within {W['test']['mape']:.1f}% on average"
    lede = (f"Eight models were trained on {data['train_rows']:,} home sales from Ames, Iowa, and each "
            f"was scored once on {n_test} sales it had never seen. This report shows how accurate each "
            f"model is, how long it takes to train, where it goes wrong, and what drives its prices.")
    record = [
        ("Sales", f"{data['rows']:,} houses, {years[0]}–{years[1]}"),
        ("Neighborhoods", f"{data.get('neighborhoods', 28)}"),
        ("Inputs per house", f"{data['features']} columns, {data['model_inputs']['linear']} after encoding"),
        ("Hold-out", f"{n_test} houses, used once"),
        ("Median price", money(data["price"]["median"])),
        ("Full run", f"{secs(r['runtime_seconds'])} on {r['environment']['cpus']} CPU cores"),
    ]
    record_html = "".join(f'<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>' for k, v in record)

    w_ci = B[winner]["mape_ci"]
    tiles = [
        ("Typical error (MAPE)", f"{W['test']['mape']:.1f}%",
         f"95% interval {w_ci[0]:.1f}–{w_ci[1]:.1f}%. Guessing the median price: {base['test']['mape']:.1f}%."),
        ("Priced within ±10%", f"{W['test']['within10']:.0f}%",
         f"of {n_test} hold-out houses; {W['test']['within20']:.0f}% within ±20%."),
        ("Average miss (MAE)", money(W["test"]["mae"]),
         f"Half of all misses are under {money(W['test']['medae'])}."),
        ("Variance explained (R²)", f"{W['test']['r2']:.3f}",
         f"Root mean squared error {money(W['test']['rmse'])}."),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="tile-label">{esc(a)}</div>'
                         f'<div class="tile-value">{esc(b)}</div><div class="tile-sub">{esc(c)}</div></div>'
                         for a, b, c in tiles)

    # ------------------------------------------------------------ takeaways
    takeaways = [
        f"<b>{esc(W['name'])} is the most accurate.</b> It has the lowest cross-validation error "
        f"(RMSLE {W['cv']['rmsle_mean']:.3f}), and the hold-out confirms it: a typical error of "
        f"{W['test']['mape']:.1f}%, with {W['test']['within10']:.0f}% of houses priced within 10% "
        f"of what they sold for."
    ]
    if runner_tied:
        takeaways.append(
            f"<b>{esc(R['name'])} is statistically level with it.</b> On the hold-out the two differ by "
            f"less than the resampling noise ({R['name']} does better in "
            f"{100 * B[runner]['share_beating_winner']:.0f}% of 2,000 bootstrap resamples). "
            f"It trains in {secs(R['fit_seconds'])} instead of {secs(W['fit_seconds'])}"
            + (f", about {speed:.0f}× faster, which makes it the practical choice." if speed >= 3 else "."))
    else:
        takeaways.append(
            f"<b>{esc(R['name'])} is second.</b> Its hold-out error is clearly higher: the 95% interval "
            f"of the gap is {d_lo:+.3f} to {d_hi:+.3f} RMSLE.")
    ols = M["ols"]
    gap = ols["test"]["mape"] - W["test"]["mape"]
    if gap < 2:
        takeaways.append(
            f"<b>Plain linear regression comes within {gap:.1f} points.</b> At {ols['test']['mape']:.1f}% "
            f"it shows that most of the accuracy comes from the inputs: log floor areas, quality scores "
            f"and neighborhood. The more complex models add the last stretch.")
    else:
        takeaways.append(
            f"<b>Linear regression trails by {gap:.1f} points</b> ({ols['test']['mape']:.1f}%). The "
            f"nonlinear models are picking up structure a straight line cannot.")
    worst = max(contenders, key=lambda k: M[k]["test"]["mape"])
    Wo = M[worst]
    takeaways.append(
        f"<b>{esc(Wo['name'])} is the weakest trained model</b> at {Wo['test']['mape']:.1f}%. "
        + ("A single tree predicts in steps, one price per leaf, so it cannot follow a smooth "
           "price-per-square-foot trend."
           if worst == "tree" else "It does not generalise as well as the others."))
    bands = r["price_bands"]
    first_edge = bands["bands"][0]["high"]
    w_bands = bands["models"][winner]["mape"]
    rest = sum(w_bands[1:]) / (len(w_bands) - 1)
    hardest_everywhere = all(max(range(len(bands["models"][k]["mape"])),
                                 key=lambda i: bands["models"][k]["mape"][i]) == 0 for k in contenders)
    takeaways.append(
        f"<b>The cheapest homes are the hardest to price.</b> For houses under {kmoney(first_edge)} the "
        f"winner's error is {w_bands[0]:.1f}%, against {rest:.1f}% across the other price bands"
        + (", and every model shows the same pattern." if hardest_everywhere else "."))
    takeaways_html = "".join(f"<li>{t}</li>" for t in takeaways)

    # ------------------------------------------------------------ leaderboard
    cols = [
        ("Model", None), ("CV RMSLE", "num"), ("Hold-out RMSLE", "num"), ("MAPE", "num"),
        ("Within ±10%", "num"), ("RMSE", "num"), ("MAE", "num"), ("R²", "num"),
        ("Train once", "num"), ("Tuning", "num"), ("Standing", None),
    ]
    head = "".join(
        f'<th scope="col"{" class=num" if kind else ""}><button type="button" data-col="{i}">'
        f'{esc(name)}</button></th>' for i, (name, kind) in enumerate(cols))
    body_rows = []
    for rank, k in enumerate(order, 1):
        m = M[k]
        ci = B[k]["rmsle_ci"]
        tuning = m["tuning"]
        cells = [
            (rank, f'<span class="m-name">{esc(m["name"])}</span><span class="m-fam">{esc(m["family"])}</span>'),
            (m["cv"]["rmsle_mean"], f'{m["cv"]["rmsle_mean"]:.4f}<span class="pm"> ± {m["cv"]["rmsle_std"]:.4f}</span>'),
            (m["test"]["rmsle"], f'{m["test"]["rmsle"]:.4f}<span class="ci">{ci[0]:.3f}–{ci[1]:.3f}</span>'),
            (m["test"]["mape"], f'{m["test"]["mape"]:.2f}%'),
            (m["test"]["within10"], f'{m["test"]["within10"]:.1f}%'),
            (m["test"]["rmse"], money(m["test"]["rmse"])),
            (m["test"]["mae"], money(m["test"]["mae"])),
            (m["test"]["r2"], f'{m["test"]["r2"]:.3f}'.replace("-", "\u2212")),
            (m["fit_seconds"], secs(m["fit_seconds"])),
            (tuning["seconds"] if tuning else 0,
             f'{secs(tuning["seconds"])}<span class="ci">{tuning["candidates"]} settings</span>'
             if tuning else '<span class="muted">none</span>'),
            (["best", "ahead", "tied", "behind", "ref"].index(standing(k)[0]), pill(k)),
        ]
        tds = "".join(f'<td data-sort="{v}"{" class=num" if cols[i][1] else ""}>{h}</td>'
                      for i, (v, h) in enumerate(cells))
        body_rows.append(f'<tr class="{"is-winner" if k == winner else ""}">{tds}</tr>')
    leaderboard = (f'<div class="scroll"><table class="board" id="board"><thead><tr>{head}</tr></thead>'
                   f'<tbody>{"".join(body_rows)}</tbody></table></div>')

    # ------------------------------------------------------------ accuracy chart
    vals = [v for k in contenders for v in (*B[k]["mape_ci"], M[k]["cv"]["oof"]["mape"])]
    lo, hi = padded_domain(vals, 0.3, 1)
    ticks = nice_ticks(lo, hi, 6)
    rows = []
    for k in contenders:
        m, ci = M[k], B[k]["mape_ci"]
        cls = "mk-emph" if k == winner else "mk-base"
        rows.append({
            "label": m["name"], "sub": m["family"], "emph": k == winner,
            "value": f'{m["test"]["mape"]:.1f}%',
            "marks": [
                span(ci[0], ci[1], lo, hi, "ci-line" + (" is-emph" if k == winner else "")),
                dot(m["cv"]["oof"]["mape"], lo, hi, "mk-ring",
                    tip(f'{m["cv"]["oof"]["mape"]:.2f}%', f'{m["name"]}: cross-validation error',
                        f'{data["train_rows"]:,} training houses, out-of-fold'),
                    f'{m["name"]} cross-validation error {m["cv"]["oof"]["mape"]:.2f}%'),
                dot(m["test"]["mape"], lo, hi, cls,
                    tip(f'{m["test"]["mape"]:.2f}%', f'{m["name"]}: hold-out error',
                        f'95% interval {ci[0]:.2f}–{ci[1]:.2f}%'),
                    f'{m["name"]} hold-out error {m["test"]["mape"]:.2f}%'),
            ],
        })
    accuracy_chart = row_chart(rows, lo, hi, ticks, lambda t: f"{t:g}%",
                               "Mean absolute percentage error (lower is better)", "Hold-out")
    accuracy_table = data_table(
        ["Model", "Hold-out MAPE", "95% interval", "Cross-validation MAPE"],
        [[esc(M[k]["name"]), f'{M[k]["test"]["mape"]:.2f}%',
          f'{B[k]["mape_ci"][0]:.2f}–{B[k]["mape_ci"][1]:.2f}%', f'{M[k]["cv"]["oof"]["mape"]:.2f}%']
         for k in order], "Error per model")

    # ------------------------------------------------------------ speed vs accuracy
    pts = [(k, M[k]["fit_seconds"], M[k]["test"]["mape"]) for k in contenders]
    x_lo = 10 ** math.floor(math.log10(min(p[1] for p in pts)))
    x_hi = 10 ** math.ceil(math.log10(max(p[1] for p in pts)))
    y_lo, y_hi = padded_domain([p[2] for p in pts], 0.4, 1)
    x_ticks = [10 ** e for e in range(int(math.log10(x_lo)), int(math.log10(x_hi)) + 1)]
    y_ticks = nice_ticks(y_lo, y_hi, 5)

    def lx(v):
        return 100 * (math.log10(v) - math.log10(x_lo)) / (math.log10(x_hi) - math.log10(x_lo))

    def ly(v):
        return 100 * (v - y_lo) / (y_hi - y_lo)

    sc = []
    for t in x_ticks:
        sc.append(f'<span class="sc-gx" style="left:{lx(t):.2f}%"></span>'
                  f'<span class="sc-tx" style="left:{lx(t):.2f}%">{t:g}\u00a0s</span>')
    for t in y_ticks:
        sc.append(f'<span class="sc-gy" style="bottom:{ly(t):.2f}%"></span>'
                  f'<span class="sc-ty" style="bottom:{ly(t):.2f}%">{t:g}%</span>')
    for k, s, e in pts:
        m = M[k]
        cls = "mk-emph" if k == winner else "mk-base"
        sc.append(
            f'<span class="mk {cls} sc-pt" style="left:{lx(s):.2f}%;bottom:{ly(e):.2f}%" tabindex="0"'
            f' role="img" aria-label="{esc(m["name"])}: {e:.2f}% error, {esc(secs(s))} to train"'
            f'{tip(f"{e:.2f}% error", m["name"], f"Trains once in {secs(s)}", "Tuning: " + (secs(m["tuning"]["seconds"]) if m["tuning"] else "none"))}></span>'
            f'<span class="sc-lb{" is-emph" if k == winner else ""}" data-x="{lx(s):.2f}" data-y="{ly(e):.2f}"'
            f' data-full="{esc(m["name"])}" data-short="{esc(SHORT_NAMES.get(m["name"], m["name"]))}"'
            f' style="left:calc({lx(s):.2f}% + 12px);top:calc({100 - ly(e):.2f}% - 0.6em)">'
            f'{esc(m["name"])}</span>')
    speed_chart = (f'<div class="sc"><div class="sc-plot">{"".join(sc)}</div>'
                   f'<div class="sc-ytitle">Hold-out MAPE</div>'
                   f'<div class="sc-xtitle">Time to train once on {data["train_rows"]:,} houses '
                   f'(log scale, one process, no parallel jobs)</div></div>')
    speed_table = data_table(
        ["Model", "Train once", "Tuning search", "Predict 1,000 houses", "Hold-out MAPE"],
        [[esc(M[k]["name"]), secs(M[k]["fit_seconds"]),
          secs(M[k]["tuning"]["seconds"]) if M[k]["tuning"] else "none",
          f'{M[k]["predict_ms_per_1000"]:.0f} ms', f'{M[k]["test"]["mape"]:.2f}%'] for k in order],
        "Training cost per model")

    # ------------------------------------------------------------ overfitting
    vals = [v for k in contenders for v in (M[k]["train"]["rmsle"], M[k]["test"]["rmsle"])]
    lo, hi = 0.0, math.ceil(max(vals) * 20) / 20
    ticks = nice_ticks(lo, hi, 4)
    rows = []
    for k in contenders:
        m = M[k]
        a, b = m["train"]["rmsle"], m["test"]["rmsle"]
        rows.append({
            "label": m["name"], "emph": k == winner, "value": signed(b - a, 3),
            "marks": [
                span(min(a, b), max(a, b), lo, hi, "db-line"),
                dot(a, lo, hi, "mk-train", tip(f"{a:.3f}", f"{m['name']}: error on its own training data"),
                    f"{m['name']} training error {a:.3f}"),
                dot(b, lo, hi, "mk-test", tip(f"{b:.3f}", f"{m['name']}: error on the hold-out"),
                    f"{m['name']} hold-out error {b:.3f}"),
            ],
        })
    overfit_chart = row_chart(rows, lo, hi, ticks, lambda t: f"{t:g}", "RMSLE (lower is better)", "Gap")

    # ------------------------------------------------------------ fold stability
    vals = [f["rmsle"] for k in contenders for f in M[k]["cv"]["folds"]]
    lo, hi = padded_domain(vals, 0.004, 0.01)
    ticks = nice_ticks(lo, hi, 4)
    rows = []
    for k in contenders:
        m = M[k]
        cls = "mk-emph mk-sm" if k == winner else "mk-base mk-sm"
        marks = [f'<span class="mean-tick" style="left:{pos(m["cv"]["rmsle_mean"], lo, hi):.2f}%"></span>']
        for i, f in enumerate(m["cv"]["folds"], 1):
            marks.append(dot(f["rmsle"], lo, hi, cls,
                             tip(f'{f["rmsle"]:.4f}', f'{m["name"]}: fold {i} of 5',
                                 f'MAPE {f["mape"]:.2f}%'), ""))
        rows.append({"label": m["name"], "emph": k == winner,
                     "value": f'± {m["cv"]["rmsle_std"]:.3f}', "marks": marks})
    folds_chart = row_chart(rows, lo, hi, ticks, lambda t: f"{t:g}", "RMSLE per fold", "Spread")
    folds_table = data_table(
        ["Model", "Train RMSLE", "Hold-out RMSLE", "Fold 1", "Fold 2", "Fold 3", "Fold 4", "Fold 5"],
        [[esc(M[k]["name"]), f'{M[k]["train"]["rmsle"]:.4f}', f'{M[k]["test"]["rmsle"]:.4f}',
          *[f'{f["rmsle"]:.4f}' for f in M[k]["cv"]["folds"]]] for k in order],
        "Training, hold-out and per-fold error")

    # ------------------------------------------------------------ price bands
    edges = bands["bands"]
    band_labels = [f"Under {kmoney(b['high'])}" if i == 0 else
                   f"Over {kmoney(b['low'])}" if i == len(edges) - 1 else
                   f"{kmoney(b['low'])}–{kmoney(b['high'])}" for i, b in enumerate(edges)]
    band_heads = [f'<th scope="col" class="num">{esc(label)}'
                  f'<span class="th-sub">{bands["counts"][i]} houses</span></th>'
                  for i, label in enumerate(band_labels)]
    steps = [5, 7, 9, 12, 16, 22]

    def heat_class(v):
        return f"h{sum(v >= s for s in steps)}"

    heat_rows = []
    for k in order:
        cells = []
        for i, (mape, bias) in enumerate(zip(bands["models"][k]["mape"], bands["models"][k]["bias"])):
            lean = "overvalues" if bias > 0 else "undervalues"
            cells.append(
                f'<td class="hc {heat_class(mape)}" tabindex="0"'
                f'{tip(f"{mape:.1f}% error", M[k]["name"] + " · houses " + band_labels[i][0].lower() + band_labels[i][1:], f"Median error {signed(bias)}%: it {lean} here")}>'
                f'<span class="hv">{mape:.1f}%</span><span class="hb">{signed(bias)}</span></td>')
        heat_rows.append(f'<tr><th scope="row">{esc(M[k]["name"])}</th>{"".join(cells)}</tr>')
    scale = "".join(f'<span class="sk h{i}"></span>' for i in range(len(steps) + 1))
    scale_labels = "".join(f"<span>{s}%</span>" for s in steps)
    heat = (f'<div class="scroll"><table class="heat"><thead><tr><th scope="col">Model</th>'
            f'{"".join(band_heads)}</tr></thead><tbody>{"".join(heat_rows)}</tbody></table></div>'
            f'<div class="heat-key"><span class="hk-title">MAPE</span><div class="hk">'
            f'<div class="hk-swatches">{scale}</div><div class="hk-labels">{scale_labels}</div></div>'
            f'<span class="hk-note">Small number: median signed error in %. '
            f'Positive means the model overvalues houses in that band.</span></div>')

    # ------------------------------------------------------------ predicted vs actual
    tp = r["test_points"]
    actual = tp["actual"]
    lo_p, hi_p = 45_000, 700_000
    size, pad_l, pad_b, pad_t, pad_r = 300, 44, 30, 10, 10
    span_px = size - pad_l - pad_r

    def sx(v):
        v = min(max(v, lo_p), hi_p)
        return pad_l + span_px * (math.log(v) - math.log(lo_p)) / (math.log(hi_p) - math.log(lo_p))

    def sy(v):
        v = min(max(v, lo_p), hi_p)
        return pad_t + span_px * (1 - (math.log(v) - math.log(lo_p)) / (math.log(hi_p) - math.log(lo_p)))

    price_ticks = [50_000, 100_000, 200_000, 400_000]
    points_js = {}
    panels = []
    for k in order:
        m = M[k]
        p = tp["predicted"][k]
        coords = [[round(sx(a), 1), round(sy(q), 1)] for a, q in zip(actual, p)]
        points_js[k] = coords
        circles = "".join(f'<circle cx="{x}" cy="{y}" r="2.8"/>' for x, y in coords)
        band = (f'<polygon class="pv-band" points="{sx(lo_p):.1f},{sy(lo_p * 1.1):.1f} '
                f'{sx(hi_p / 1.1):.1f},{sy(hi_p):.1f} {sx(hi_p):.1f},{sy(hi_p * 0.9):.1f} '
                f'{sx(lo_p / 0.9):.1f},{sy(lo_p):.1f}"/>')
        diag = f'<line class="pv-diag" x1="{sx(lo_p)}" y1="{sy(lo_p)}" x2="{sx(hi_p)}" y2="{sy(hi_p)}"/>'
        axes = "".join(
            f'<line class="pv-grid" x1="{sx(t):.1f}" y1="{pad_t}" x2="{sx(t):.1f}" y2="{pad_t + span_px}"/>'
            f'<line class="pv-grid" x1="{pad_l}" y1="{sy(t):.1f}" x2="{pad_l + span_px}" y2="{sy(t):.1f}"/>'
            f'<text class="pv-tick" x="{sx(t):.1f}" y="{pad_t + span_px + 16}" text-anchor="middle">{kmoney(t)}</text>'
            f'<text class="pv-tick" x="{pad_l - 6}" y="{sy(t) + 4:.1f}" text-anchor="end">{kmoney(t)}</text>'
            for t in price_ticks)
        frame = (f'<rect class="pv-frame" x="{pad_l}" y="{pad_t}" width="{span_px}" height="{span_px}"/>'
                 f'<text class="pv-title" x="{pad_l + 8}" y="{pad_t + 16}">Predicted ↑</text>'
                 f'<text class="pv-title" x="{pad_l + span_px - 8}" y="{pad_t + span_px - 8}" '
                 f'text-anchor="end">Sold for →</text>')
        chip = '<span class="pill pill-best">Best on CV</span>' if k == winner else ""
        panels.append(
            f'<figure class="pv-panel"><figcaption><span class="pv-name">{esc(m["name"])}</span>{chip}'
            f'<span class="pv-stats">MAPE {m["test"]["mape"]:.1f}% · within ±10%: {m["test"]["within10"]:.0f}%</span>'
            f'</figcaption><svg class="pv" data-key="{esc(k)}" viewBox="0 0 {size} {pad_t + span_px + pad_b}"'
            f' role="img" aria-label="{esc(m["name"])}: predicted against actual price for {n_test} hold-out houses">'
            f'{frame}{axes}{band}{diag}<g class="pv-pts{" is-emph" if k == winner else ""}">{circles}</g>'
            f'<circle class="pv-hi" r="5" cx="-20" cy="-20"/></svg></figure>')
    scatter = f'<div class="pv-grid-wrap">{"".join(panels)}</div>'

    # ------------------------------------------------------------ importance
    feats = r["importance"]["features"]
    imp_model = M[r["importance"]["model"]]
    base_err = imp_model["test"]["rmsle"]
    hi = max(f["mean"] for f in feats) * 1.08
    ticks = nice_ticks(0, hi, 4)
    rows = []
    for f in feats:
        name = feature_name(f["feature"])
        rows.append({
            "label": name, "value": f'+{f["mean"]:.3f}',
            "marks": [bar(f["mean"], 0, hi, "bar-1",
                          tip(f'+{f["mean"]:.3f} RMSLE', f'{name} ({f["feature"]})',
                              f'Error rises from {base_err:.3f} to {base_err + f["mean"]:.3f} when shuffled',
                              f'± {f["std"]:.3f} across 5 shuffles'))],
        })
    importance_chart = row_chart(rows, 0, hi, ticks, lambda t: f"{t:g}",
                                 "Increase in hold-out RMSLE when the column is shuffled", "Impact")
    weights_html = ""
    if "weights" in M.get("stack", {}):
        wts = M["stack"]["weights"]
        hi_w = max(1.0, max(wts.values()))
        w_rows = [{"label": STACK_MEMBER_NAMES.get(k, k), "value": f"{v:.2f}",
                   "marks": [bar(v, 0, hi_w, "bar-1", tip(f"{v:.2f}", f"Weight on {STACK_MEMBER_NAMES.get(k, k)}"))]}
                  for k, v in sorted(wts.items(), key=lambda kv: -kv[1])]
        zero = [STACK_MEMBER_NAMES.get(k, k) for k, v in wts.items() if v < 1e-6]
        weights_html = (
            f'<div class="card"><h3>How the stacked ensemble blends its members</h3>'
            f'<p class="note">Weights the blender learned from out-of-fold predictions. '
            + (f'{", ".join(zero)} got zero weight: what it knows, the others already cover.'
               if zero else "Every member contributes.")
            + f'</p>{row_chart(w_rows, 0, hi_w, [0, 0.25, 0.5, 0.75, 1.0], lambda t: f"{t:.2f}", "Blending weight", "Weight")}</div>')

    # ------------------------------------------------------------ method
    params_rows = []
    for k in order:
        t = M[k]["tuning"]
        if not t:
            continue
        pretty = ", ".join(f"{p} = {v:.4g}" if isinstance(v, float) else f"{p} = {v}"
                           for p, v in t["best_params"].items())
        params_rows.append([esc(M[k]["name"]), f'{t["candidates"]}', esc(pretty)])
    params_table = data_table(["Model", "Settings tried", "Chosen settings"], params_rows,
                              "Hyperparameters chosen by 5-fold cross-validation")
    env = r["environment"]
    blurbs = "".join(f'<li><b>{esc(M[k]["name"])}.</b> {esc(M[k]["blurb"])}</li>' for k in order)

    try:
        calc_spec = calculator.build_spec(r)
    except OSError as err:  # the price index comes from FRED; skip the calculator when offline
        print(f"Skipping the price calculator: {err}")
        calc_spec = None
    calc_html = calculator.section(calc_spec, esc) if calc_spec else ""
    calc_link = '<a href="#calculator">Price calculator</a>' if calc_spec else ""

    body = f"""
<div class="page">
<header class="masthead">
  <p class="eyebrow">Model comparison · residential sales · Ames, Iowa</p>
  <h1>{esc(headline)}</h1>
  <p class="lede">{esc(lede)}</p>
  <dl class="record">{record_html}</dl>
  <nav class="toc" aria-label="Sections">
    {calc_link}<a href="#leaderboard">Leaderboard</a><a href="#accuracy">Accuracy</a><a href="#cost">Training cost</a>
    <a href="#overfitting">Overfitting</a><a href="#bands">Price bands</a><a href="#scatter">Predictions</a>
    <a href="#drivers">Price drivers</a><a href="#method">Method</a>
  </nav>
</header>

<section class="verdict" aria-labelledby="verdict-h">
  <h2 id="verdict-h" class="eyebrow">{esc(W['name'])} on the {n_test} hold-out houses</h2>
  <div class="tiles">{tiles_html}</div>
  <ol class="takeaways">{takeaways_html}</ol>
</section>
{calc_html}

<section id="leaderboard">
  <h2>Leaderboard</h2>
  <p class="note">Ranked by cross-validation error, the score used to pick the winner. Hold-out columns are
  the one-time exam on {n_test} unseen houses; small grey numbers are 95% bootstrap intervals.
  Click a column to sort.</p>
  {leaderboard}
  <p class="note">“Tied on hold-out” means the 95% interval of the error gap to {esc(W['name'])} includes
  zero, so the hold-out alone cannot separate the two.</p>
</section>

<section id="accuracy">
  <h2>How far off is each model?</h2>
  <p class="note">Filled dot: error on the hold-out, with its 95% interval. Ring: the same measure from
  cross-validation on the training houses. When the two agree, the score is not a lucky split.
  The median-price baseline sits far off the scale at {base['test']['mape']:.1f}%.</p>
  {legend([("lk-dot", "Hold-out error and 95% interval"), ("lk-ring", "Cross-validation error")])}
  {accuracy_chart}
  {accuracy_table}
</section>

<section id="cost">
  <h2>Accuracy against training time</h2>
  <p class="note">Time for one training run on all {data['train_rows']:,} houses with the chosen settings.
  Finding those settings (the tuning search) took longer; see the leaderboard.
  {"Every model here trains in under a minute." if max(M[k]["fit_seconds"] for k in contenders) < 60 else ""}</p>
  {speed_chart}
  {speed_table}
</section>

<section id="overfitting">
  <h2>Memorizing or learning?</h2>
  <div class="stack">
    <div class="card">
      <h3>Error on training data against the hold-out</h3>
      <p class="note">A large gap means the model memorized its training houses. Tree ensembles always fit
      their training data closely; what matters is the hold-out dot.</p>
      {legend([("lk-train", "Training data"), ("lk-test", "Hold-out")])}
      {overfit_chart}
    </div>
    <div class="card">
      <h3>Stable across the five cross-validation folds?</h3>
      <p class="note">Each dot is one fold of about {data['train_rows'] // 5} houses; the bar marks the mean.
      Tight clusters mean the score does not depend on which houses were held back.</p>
      {folds_chart}
    </div>
  </div>
  {folds_table}
</section>

<section id="bands">
  <h2>Where the errors are</h2>
  <p class="note">Hold-out houses split into five equal-sized price bands. Darker cells mean larger errors.</p>
  {heat}
</section>

<section id="scatter">
  <h2>Predicted against actual price</h2>
  <p class="note">Each dot is one of the {n_test} hold-out houses (log scales). The diagonal is a perfect
  prediction and the shaded strip is ±10% of the sale price, a common tolerance for appraisals.
  Point at a dot to see the house.</p>
  {scatter}
</section>

<section id="drivers">
  <h2>What drives the winner's prices</h2>
  <div class="stack">
    <div class="card">
      <h3>Most important inputs for {esc(imp_model['name'])}</h3>
      <p class="note">Permutation importance on the hold-out: shuffle one column, measure how much worse the
      predictions get. Related columns share credit, so floor-area measures split their importance.</p>
      {importance_chart}
    </div>
    {weights_html}
  </div>
</section>

<section id="method" class="method">
  <h2>How the test was run</h2>
  <div class="method-grid">
    <div>
      <h3>Data</h3>
      <p>The Ames Housing data set (Dean De Cock, 2011; OpenML id 43926): {data['raw_rows']:,} residential
      sales in Ames, Iowa, from {years[0]} to {years[1]}, with {data['raw_features']} descriptive columns.
      Following De Cock's own advice, the {data['dropped_over_4000_sqft']} houses above 4,000 sq ft of living area
      were removed, so the results apply to homes up to that size. Quality ratings were turned into ordered
      scores (Poor = 1 to Excellent = 5), and seven columns were added: total floor area, bathroom count,
      age at sale, years since remodel, porch area, quality × living area, and a flag for missing street
      frontage. Prices are not adjusted for inflation.</p>
      <h3>Protocol</h3>
      <p>An 80/20 split, stratified by price, gave {data['train_rows']:,} training and {n_test} hold-out houses.
      Each model was tuned by random search with 5-fold cross-validation on the training houses only
      (the number of settings tried is in the table below). The winner was chosen on cross-validation alone.
      Only then was each model scored on the hold-out, once. All models learn log(price), so the training
      objective treats a 10% miss the same at any price.</p>
      <h3>The models</h3>
      <ul class="blurbs">{blurbs}</ul>
    </div>
    <div>
      <h3>What the numbers mean</h3>
      <dl class="glossary">
        <div><dt>MAPE</dt><dd>Mean absolute percentage error: the typical miss as a share of the sale price.</dd></div>
        <div><dt>Within ±10%</dt><dd>Share of houses whose prediction lands within 10% of the sale price.</dd></div>
        <div><dt>RMSLE</dt><dd>Root mean squared error of log price. Roughly a percentage error that punishes
        big misses more. It was the selection metric, and the Kaggle house-price competition uses it too.</dd></div>
        <div><dt>MAE</dt><dd>Mean absolute error in dollars: the average miss.</dd></div>
        <div><dt>RMSE</dt><dd>Root mean squared error in dollars. Dominated by the largest misses, which are mostly on
        expensive houses.</dd></div>
        <div><dt>R²</dt><dd>Share of the variation in sale prices the model explains. 1.0 is perfect; 0 is no better than
        the average price.</dd></div>
        <div><dt>CV</dt><dd>Cross-validation: train on four fifths of the training houses, score on the last fifth,
        five times over.</dd></div>
        <div><dt>95% interval</dt><dd>From 2,000 bootstrap resamples of the hold-out houses. The same resamples are used
        for every model, so gaps between models are compared fairly.</dd></div>
      </dl>
      <h3>Limits</h3>
      <ul class="blurbs">
        <li>One town and five years of sales. Expect larger errors on other markets or recent prices.</li>
        <li>Sale type and condition (for example foreclosures, or new homes sold before completion) are inputs.
        They are known at sale time, but not when valuing a house that is not on the market.</li>
        <li>Cross-validation scores of tuned models are slightly optimistic, because the same folds chose the
        settings. The hold-out numbers do not have this bias.</li>
        <li>Timings are fits without parallel jobs (n_jobs=1) on one {esc(env['machine'])} machine with
        scikit-learn {esc(env['sklearn'])}, XGBoost {esc(env['xgboost'])} and Python {esc(env['python'])}.
        They show relative cost, not what a tuned production setup would take.</li>
      </ul>
      <h3>Reproduce</h3>
      <pre><code>.venv/bin/python train.py    # about {secs(r['runtime_seconds'])}
.venv/bin/python report.py   # writes report.html</code></pre>
    </div>
  </div>
  {params_table}
  <p class="footer">Generated {esc(r['generated'][:10])}{' · quick run, not for conclusions' if r.get('quick') else ''}.</p>
</section>
</div>
<div id="tip" class="tip" role="status" aria-live="polite" hidden></div>
<script type="application/json" id="pv-data">{json.dumps({"points": points_js, "actual": actual, "predicted": tp["predicted"], "hood": tp["neighborhood"], "area": tp["living_area"], "built": tp["year_built"]}, separators=(",", ":")).replace("</", "<\\/")}</script>
<script>{SCRIPT}</script>
{"<script>" + calculator.SCRIPT + "</script>" if calc_spec else ""}
"""
    head = (f"<title>{esc(title)}</title>\n"
            '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,500..800'
            '&family=IBM+Plex+Mono:wght@400;500&family=Public+Sans:wght@400..700&display=swap">\n'
            f"<style>{STYLE}{calculator.STYLE}</style>")
    return head, body


STYLE = r"""
/* Layout: one reading column with full-width figures; record-card header like an assessor's sheet. */
:root {
  --bg: #f3f5f4; --surface: #fcfcfb; --ink: #121719; --ink-2: #4a5359; --muted: #737d84;
  --rule: #dce1de; --grid: #e6e9e7; --axis: #c3c9c6;
  --accent: #2a78d6; --accent-ink: #1c5cab; --accent-wash: rgba(42, 120, 214, 0.10);
  --mark: #a3acb2; --train: #9ec5f4; --test: #2a78d6; --tip-bg: #121719; --tip-fg: #f4f6f5; --tip-2: #b9c2c7;
  --warn: #c98500; --warn-wash: rgba(250, 178, 25, 0.18);
  --h0-bg: #e4eefb; --h0-fg: #121719; --h1-bg: #cde2fb; --h1-fg: #121719; --h2-bg: #9ec5f4; --h2-fg: #121719;
  --h3-bg: #6da7ec; --h3-fg: #0b1a2b; --h4-bg: #3987e5; --h4-fg: #ffffff; --h5-bg: #256abf; --h5-fg: #ffffff;
  --h6-bg: #184f95; --h6-fg: #ffffff;
  --display: "Archivo", "Arial Narrow", system-ui, sans-serif;
  --body: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0e1113; --surface: #161a1d; --ink: #eef1f2; --ink-2: #bcc4c9; --muted: #87919a;
    --rule: #2a3136; --grid: #22282c; --axis: #3a4247;
    --accent: #3987e5; --accent-ink: #86b6ef; --accent-wash: rgba(57, 135, 229, 0.16);
    --mark: #5d676e; --train: #1c5cab; --test: #6da7ec; --tip-bg: #eef1f2; --tip-fg: #121719; --tip-2: #4a5359; --warn: #fab219; --warn-wash: rgba(250, 178, 25, 0.14);
    --h0-bg: #13253a; --h0-fg: #eef1f2; --h1-bg: #0d366b; --h1-fg: #eef1f2; --h2-bg: #104281; --h2-fg: #ffffff;
    --h3-bg: #184f95; --h3-fg: #ffffff; --h4-bg: #256abf; --h4-fg: #ffffff; --h5-bg: #5598e7; --h5-fg: #0b1a2b;
    --h6-bg: #9ec5f4; --h6-fg: #0b1a2b;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #0e1113; --surface: #161a1d; --ink: #eef1f2; --ink-2: #bcc4c9; --muted: #87919a;
  --rule: #2a3136; --grid: #22282c; --axis: #3a4247;
  --accent: #3987e5; --accent-ink: #86b6ef; --accent-wash: rgba(57, 135, 229, 0.16);
  --mark: #5d676e; --train: #1c5cab; --test: #6da7ec; --tip-bg: #eef1f2; --tip-fg: #121719; --tip-2: #4a5359; --warn: #fab219; --warn-wash: rgba(250, 178, 25, 0.14);
  --h0-bg: #13253a; --h0-fg: #eef1f2; --h1-bg: #0d366b; --h1-fg: #eef1f2; --h2-bg: #104281; --h2-fg: #ffffff;
  --h3-bg: #184f95; --h3-fg: #ffffff; --h4-bg: #256abf; --h4-fg: #ffffff; --h5-bg: #5598e7; --h5-fg: #0b1a2b;
  --h6-bg: #9ec5f4; --h6-fg: #0b1a2b;
  color-scheme: dark;
}

* { box-sizing: border-box; }
body { background: var(--bg); color: var(--ink); font: 400 16px/1.55 var(--body); margin: 0; }
.page { max-width: 1120px; margin: 0 auto; padding-inline: clamp(16px, 4vw, 40px); padding-block: 40px 72px;
        display: grid; gap: 56px; }
section { display: grid; gap: 16px; min-width: 0; }
h1, h2, h3 { font-family: var(--display); text-wrap: balance; margin: 0; letter-spacing: -0.01em; }
h1 { font-size: clamp(2rem, 1.2rem + 3.2vw, 3.25rem); line-height: 1.05; font-weight: 750;
     font-stretch: 78%; font-variation-settings: "wdth" 78; max-width: 22ch; }
h2 { font-size: 1.6rem; line-height: 1.15; font-weight: 700; font-stretch: 82%; font-variation-settings: "wdth" 82; }
h3 { font-size: 1.05rem; font-weight: 650; line-height: 1.3; }
p { margin: 0; }
a { color: var(--accent-ink); }
.eyebrow { font: 500 0.75rem/1.4 var(--mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-2);
           margin: 0; }
.lede { font-size: 1.125rem; color: var(--ink-2); max-width: 64ch; }
.note { color: var(--ink-2); font-size: 0.9375rem; max-width: 72ch; }
.muted { color: var(--muted); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.masthead { display: grid; gap: 20px; }
.record { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin: 4px 0 0;
          border-top: 1px solid var(--ink); border-bottom: 1px solid var(--rule); }
.record > div { padding: 10px 12px 12px 0; border-right: 1px solid var(--rule); min-width: 0; }
.record > div + div { padding-left: 12px; }
.record > div:last-child { border-right: 0; }
.record dt { font: 500 0.6875rem/1.3 var(--mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
.record dd { margin: 4px 0 0; font-weight: 600; font-size: 0.9375rem; }
.toc { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 0.875rem; }
.toc a { color: var(--ink-2); text-decoration: none; border-bottom: 1px solid var(--rule); padding-bottom: 1px; }
.toc a:hover { color: var(--accent-ink); border-color: var(--accent); }

.verdict { gap: 20px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
.tile { background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; padding: 16px 18px 18px;
        display: grid; gap: 6px; align-content: start; }
.tile-label { font-size: 0.8125rem; font-weight: 600; color: var(--ink-2); }
.tile-value { font: 650 2.5rem/1 var(--body); letter-spacing: -0.02em; }
.tile-sub { font-size: 0.8125rem; color: var(--muted); }
.takeaways { margin: 0; padding-left: 1.4em; display: grid; gap: 10px; max-width: 76ch; }
.takeaways li::marker { font: 500 0.875rem var(--mono); color: var(--muted); }
.takeaways b { font-weight: 650; }

.scroll { overflow-x: auto; min-width: 0; }
table { border-collapse: collapse; font-variant-numeric: tabular-nums; }
.board { width: 100%; min-width: 900px; font-size: 0.875rem; background: var(--surface);
         border: 1px solid var(--rule); border-radius: 10px; overflow: hidden; }
.board th { text-align: left; font-weight: 600; color: var(--ink-2); border-bottom: 1px solid var(--axis);
            padding: 0; white-space: nowrap; vertical-align: bottom; }
.board th button { all: unset; cursor: pointer; display: block; padding: 10px 8px 8px; font: inherit; color: inherit; }
.board th button:hover { color: var(--accent-ink); }
.board th button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.board th[aria-sort] button::after { content: " ↓"; color: var(--accent-ink); }
.board th[aria-sort="ascending"] button::after { content: " ↑"; }
.board td { padding: 9px 8px; border-bottom: 1px solid var(--grid); vertical-align: top; white-space: nowrap; }
.board tbody tr:last-child td { border-bottom: 0; }
.board .num { text-align: right; }
.board th.num button { text-align: right; }
.board tr.is-winner td { background: var(--accent-wash); }
.board tr.is-winner .m-name { color: var(--accent-ink); }
.m-name { display: block; font-weight: 650; }
.m-fam, .ci { display: block; font-size: 0.75rem; color: var(--muted); }
.pm { color: var(--muted); }
.pill { display: inline-block; font: 500 0.6875rem/1 var(--mono); letter-spacing: 0.04em; text-transform: uppercase;
        padding: 4px 7px; border-radius: 999px; border: 1px solid var(--rule); color: var(--ink-2); white-space: nowrap; }
.pill-best { background: var(--accent); border-color: var(--accent); color: #fff; }
.pill-tied, .pill-ahead { border-color: var(--accent); color: var(--accent-ink); }
.pill-ref { border-style: dashed; color: var(--muted); }

/* Row charts: label | track | value, all rows on one x scale. */
.rc { display: grid; grid-template-columns: fit-content(15rem) minmax(0, 1fr) max-content; column-gap: 16px; }
.rc-head { font: 500 0.6875rem/1.2 var(--mono); letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted);
           padding-bottom: 6px; }
.rc-label { display: flex; flex-direction: column; justify-content: center; min-height: 40px; font-size: 0.875rem;
            font-weight: 550; line-height: 1.2; min-width: 0; }
.rc-sub { font-size: 0.75rem; font-weight: 400; color: var(--muted); }
.rc-label.is-emph, .rc-value.is-emph { color: var(--accent-ink); font-weight: 700; }
.rc-track { position: relative; min-height: 40px; }
.rc-value { display: flex; align-items: center; justify-content: flex-end; font-size: 0.875rem; min-width: 3.5rem;
            font-variant-numeric: tabular-nums; color: var(--ink-2); }
.rc-head.rc-value { justify-content: flex-end; }
.gl { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--grid); }
.rc-axis { position: relative; height: 22px; border-top: 1px solid var(--axis); }
.tk { position: absolute; top: 4px; transform: translateX(-50%); font-size: 0.75rem; color: var(--muted);
      font-variant-numeric: tabular-nums; white-space: nowrap; }
.rc-axis-title { font-size: 0.75rem; color: var(--muted); padding-top: 4px; }
.mk { position: absolute; top: 50%; width: 12px; height: 12px; border-radius: 50%; transform: translate(-50%, -50%);
      box-shadow: 0 0 0 2px var(--surface); cursor: default; z-index: 2; }
.mk::before { content: ""; position: absolute; inset: -8px; border-radius: 50%; }
.mk:hover, .mk:focus-visible { box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px var(--ink); }
.mk-sm { width: 9px; height: 9px; }
.mk-emph { background: var(--accent); z-index: 3; }
.mk-base { background: var(--mark); }
.mk-ring { background: var(--surface); border: 2px solid var(--ink-2); width: 12px; height: 12px; }
.mk-train { background: var(--train); }
.mk-test { background: var(--test); z-index: 3; }
.ci-line { position: absolute; top: 50%; height: 2px; margin-top: -1px; background: var(--mark); border-radius: 1px; }
.ci-line.is-emph { background: var(--accent); }
.db-line { position: absolute; top: 50%; height: 2px; margin-top: -1px; background: var(--axis); }
.mean-tick { position: absolute; top: 50%; width: 2px; height: 20px; margin-top: -10px; margin-left: -1px;
             background: var(--ink); border-radius: 1px; z-index: 4; pointer-events: none; }
.bar { position: absolute; left: 0; top: 50%; height: 14px; margin-top: -7px; border-radius: 0 4px 4px 0; }
.bar::before { content: ""; position: absolute; inset: -12px 0; }
.bar-1 { background: var(--accent); }
.bar:hover, .bar:focus-visible { filter: brightness(1.12); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 0.8125rem; color: var(--ink-2); }
.lg { display: inline-flex; align-items: center; gap: 8px; }
.lg-key { display: inline-block; width: 12px; height: 12px; border-radius: 50%; }
.lk-dot { width: 28px; border-radius: 0; position: relative;
          background: linear-gradient(var(--accent), var(--accent)) center / 100% 2px no-repeat; }
.lk-dot::after { content: ""; position: absolute; left: 8px; top: 0; width: 12px; height: 12px; border-radius: 50%;
                 background: var(--accent); }
.lk-ring { border: 2px solid var(--ink-2); background: var(--surface); }
.lk-train { background: var(--train); }
.lk-test { background: var(--test); }

/* Speed scatter: HTML marks on a log-x, linear-y plane. */
.sc { display: grid; grid-template-columns: 3.25rem minmax(0, 1fr); grid-template-rows: auto auto auto;
      padding-right: 22px !important; }
.sc-ytitle { grid-row: 1; grid-column: 1 / 3; font-size: 0.75rem; color: var(--muted); padding-bottom: 8px; }
.sc-plot { grid-row: 2; grid-column: 2; position: relative; height: 320px; border-left: 1px solid var(--axis);
           border-bottom: 1px solid var(--axis); margin-bottom: 26px; }
.sc-xtitle { grid-row: 3; grid-column: 2; font-size: 0.75rem; color: var(--muted); }
.sc-gx { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--grid); }
.sc-gy { position: absolute; left: 0; right: 0; height: 1px; background: var(--grid); }
.sc-tx { position: absolute; top: calc(100% + 6px); transform: translateX(-50%); font-size: 0.75rem; color: var(--muted);
         white-space: nowrap; font-variant-numeric: tabular-nums; }
.sc-ty { position: absolute; right: calc(100% + 8px); transform: translateY(50%); font-size: 0.75rem; color: var(--muted);
         font-variant-numeric: tabular-nums; }
.sc-pt { top: auto; transform: translate(-50%, 50%); }
.sc-lb { position: absolute; font-size: 0.8125rem; font-weight: 550; white-space: nowrap; color: var(--ink-2);
         pointer-events: none; line-height: 1.2; }
.sc-lb.is-emph { color: var(--accent-ink); font-weight: 700; }
.sc-leader { position: absolute; height: 1px; background: var(--muted); transform-origin: 0 50%; pointer-events: none; }

.stack { display: grid; gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; padding: 18px 18px 14px;
        display: grid; gap: 12px; align-content: start; min-width: 0; }
#accuracy > .rc, #cost > .sc { background: var(--surface); border: 1px solid var(--rule); border-radius: 10px;
                              padding: 16px 18px 12px; }

/* Price-band heat table. */
.heat { width: 100%; min-width: 640px; font-size: 0.875rem; border-collapse: separate; border-spacing: 3px; }
.heat th { font-weight: 600; text-align: left; color: var(--ink-2); padding: 6px 10px; white-space: nowrap; }
.heat thead th { border-bottom: 1px solid var(--axis); vertical-align: bottom; }
.heat thead th.num { text-align: center; }
.th-sub { display: block; font-weight: 400; font-size: 0.75rem; color: var(--muted); }
.heat tbody th { font-weight: 550; color: var(--ink); }
.hc { text-align: center; padding: 8px 6px; border-radius: 6px; min-width: 88px; }
.hc:hover, .hc:focus-visible { outline: 2px solid var(--ink); outline-offset: -2px; }
.hv { display: block; font-weight: 650; }
.hb { display: block; font-size: 0.6875rem; opacity: 0.8; }
.h0 { background: var(--h0-bg); color: var(--h0-fg); } .h1 { background: var(--h1-bg); color: var(--h1-fg); }
.h2 { background: var(--h2-bg); color: var(--h2-fg); } .h3 { background: var(--h3-bg); color: var(--h3-fg); }
.h4 { background: var(--h4-bg); color: var(--h4-fg); } .h5 { background: var(--h5-bg); color: var(--h5-fg); }
.h6 { background: var(--h6-bg); color: var(--h6-fg); }
.heat-key { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 8px 16px; font-size: 0.75rem; color: var(--muted); }
.hk-title { font: 500 0.6875rem/1.6 var(--mono); letter-spacing: 0.06em; }
.hk-swatches { display: flex; gap: 2px; }
.sk { width: 34px; height: 10px; border-radius: 2px; }
.hk-labels { display: flex; padding-left: 34px; }
.hk-labels span { width: 36px; transform: translateX(-50%); text-align: center; margin-left: 0; font-variant-numeric: tabular-nums; }
.hk-labels span + span { margin-left: 0; }
.hk-note { max-width: 46ch; }

/* Predicted vs actual small multiples. */
.pv-grid-wrap { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 250px), 1fr)); gap: 12px; }
.pv-panel { margin: 0; background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; padding: 12px 12px 6px;
            display: grid; gap: 6px; min-width: 0; }
.pv-panel figcaption { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; }
.pv-name { font-weight: 650; font-size: 0.9375rem; }
.pv-stats { flex-basis: 100%; font-size: 0.75rem; color: var(--muted); font-variant-numeric: tabular-nums; }
svg.pv { width: 100%; height: auto; display: block; touch-action: pan-y; }
.pv-frame { fill: none; stroke: var(--axis); stroke-width: 1; }
.pv-grid { stroke: var(--grid); stroke-width: 1; }
.pv-tick { fill: var(--muted); font: 10px var(--body); }
.pv-title { fill: var(--ink-2); font: 500 10.5px var(--body); }
.pv-band { fill: var(--accent-wash); }
.pv-diag { stroke: var(--ink-2); stroke-width: 1; opacity: 0.6; }
.pv-pts circle { fill: var(--accent); fill-opacity: 0.42; }
.pv-hi { fill: var(--accent); stroke: var(--surface); stroke-width: 2; pointer-events: none; }

.method { gap: 20px; }
.method-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: 24px 40px; }
.method-grid > div { display: grid; gap: 12px; align-content: start; min-width: 0; }
.method p, .method li, .method dd { font-size: 0.9375rem; color: var(--ink-2); }
.method h3 { margin-top: 8px; }
.blurbs { margin: 0; padding-left: 1.1em; display: grid; gap: 6px; }
.blurbs b { color: var(--ink); font-weight: 600; }
.glossary { margin: 0; display: grid; gap: 8px; }
.glossary > div { display: grid; grid-template-columns: 7.5rem minmax(0, 1fr); gap: 12px; }
.glossary dt { font: 500 0.8125rem/1.6 var(--mono); color: var(--ink); }
.glossary dd { margin: 0; }
pre { margin: 0; background: var(--surface); border: 1px solid var(--rule); border-radius: 8px; padding: 12px 14px;
      overflow-x: auto; font: 0.8125rem/1.6 var(--mono); color: var(--ink); }
.twin summary { cursor: pointer; font-size: 0.8125rem; color: var(--accent-ink); width: max-content; }
.twin[open] summary { margin-bottom: 10px; }
.plain { font-size: 0.8125rem; min-width: 100%; background: var(--surface); border: 1px solid var(--rule); }
.plain caption { text-align: left; font-weight: 600; padding: 0 0 6px; color: var(--ink-2); }
.plain th, .plain td { padding: 6px 10px; border-bottom: 1px solid var(--grid); text-align: left; white-space: nowrap; }
.plain th { color: var(--ink-2); font-weight: 600; border-bottom-color: var(--axis); }
.plain td { white-space: normal; }
.footer { font: 0.75rem var(--mono); color: var(--muted); }

.tip { position: fixed; z-index: 50; pointer-events: none; background: var(--tip-bg); color: var(--tip-fg);
       border-radius: 8px; padding: 8px 10px; font-size: 0.8125rem; line-height: 1.4; max-width: 280px;
       box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18); }
.tip strong { display: block; font-size: 0.9375rem; font-variant-numeric: tabular-nums; }
.tip span { display: block; color: var(--tip-2); }

@media (max-width: 640px) {
  /* Phones: each label sits on its own line above a full-width track. */
  .rc { grid-template-columns: minmax(0, 1fr) max-content; column-gap: 12px; }
  .rc-lead { display: none; }
  .rc-label { grid-column: 1 / -1; min-height: 0; padding-top: 8px; flex-direction: row; gap: 8px;
              justify-content: flex-start; align-items: baseline; }
  .rc-track, .rc-value { min-height: 30px; }
  .rc-sub { display: none; }
  .sc-plot { height: 260px; }
  .tile-value { font-size: 2.1rem; }
  .record > div { border-right: 0; padding-left: 0 !important; border-bottom: 1px solid var(--grid); }
}
@media (prefers-reduced-motion: no-preference) {
  .mk, .bar { transition: box-shadow 120ms ease, filter 120ms ease; }
}
"""

SCRIPT = r"""
(() => {
  const tipEl = document.getElementById('tip');
  function showTip(lines, x, y) {
    tipEl.replaceChildren();
    lines.forEach((line, i) => {
      const el = document.createElement(i === 0 ? 'strong' : 'span');
      el.textContent = line;
      tipEl.appendChild(el);
    });
    tipEl.hidden = false;
    const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    let left = x + 14, top = y + 14;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (top + h > window.innerHeight - 8) top = y - h - 14;
    tipEl.style.left = Math.max(8, left) + 'px';
    tipEl.style.top = Math.max(8, top) + 'px';
  }
  function hideTip() { tipEl.hidden = true; }

  document.addEventListener('pointermove', (e) => {
    const t = e.target.closest && e.target.closest('[data-tip]');
    if (t) showTip(t.dataset.tip.split('\n'), e.clientX, e.clientY);
    else if (!e.target.closest('svg.pv, .hpi-plot')) hideTip();
  });
  document.addEventListener('focusin', (e) => {
    const t = e.target.closest && e.target.closest('[data-tip]');
    if (!t) return;
    const r = t.getBoundingClientRect();
    showTip(t.dataset.tip.split('\n'), r.right, r.top);
  });
  document.addEventListener('focusout', hideTip);
  window.addEventListener('scroll', hideTip, { passive: true });

  // Predicted-vs-actual panels: snap to the nearest house.
  const data = JSON.parse(document.getElementById('pv-data').textContent);
  const usd = (v) => '$' + Math.round(v).toLocaleString('en-US');
  document.querySelectorAll('svg.pv').forEach((svg) => {
    const key = svg.dataset.key;
    const pts = data.points[key];
    const hi = svg.querySelector('.pv-hi');
    const pt = svg.createSVGPoint();
    svg.addEventListener('pointermove', (e) => {
      pt.x = e.clientX; pt.y = e.clientY;
      const p = pt.matrixTransform(svg.getScreenCTM().inverse());
      let best = -1, bestD = 14 * 14;
      for (let i = 0; i < pts.length; i++) {
        const dx = pts[i][0] - p.x, dy = pts[i][1] - p.y, d = dx * dx + dy * dy;
        if (d < bestD) { bestD = d; best = i; }
      }
      if (best < 0) { hi.setAttribute('cx', -20); hideTip(); return; }
      hi.setAttribute('cx', pts[best][0]); hi.setAttribute('cy', pts[best][1]);
      const a = data.actual[best], q = data.predicted[key][best];
      const err = 100 * (q - a) / a;
      showTip([
        'Predicted ' + usd(q),
        'Sold for ' + usd(a) + ' (' + (err > 0 ? '+' : '') + err.toFixed(1) + '%)',
        data.hood[best] + ' · ' + data.area[best].toLocaleString('en-US') + ' sq ft · built ' + data.built[best],
      ], e.clientX, e.clientY);
    });
    svg.addEventListener('pointerleave', () => { hi.setAttribute('cx', -20); hideTip(); });
  });

  // Speed scatter: give each label the nearby spot that overlaps the least.
  function placeLabels() {
    document.querySelectorAll('.sc-plot').forEach((plot) => {
      const box = plot.getBoundingClientRect();
      const dots = [...plot.querySelectorAll('.sc-pt')].map((d) => {
        const r = d.getBoundingClientRect();
        return { left: r.left - box.left - 3, right: r.right - box.left + 3,
                 top: r.top - box.top - 3, bottom: r.bottom - box.top + 3 };
      });
      plot.querySelectorAll('.sc-leader').forEach((l) => l.remove());
      const narrow = box.width < 420;
      const placed = [];
      const overlap = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) *
                                Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
      plot.querySelectorAll('.sc-lb').forEach((lb) => {
        lb.textContent = narrow ? lb.dataset.short : lb.dataset.full;
        const x = parseFloat(lb.dataset.x) / 100 * box.width;
        const y = (1 - parseFloat(lb.dataset.y) / 100) * box.height;
        const w = lb.offsetWidth, h = lb.offsetHeight;
        const options = [[12, -h / 2], [-w - 12, -h / 2], [-w / 2, -h - 10], [-w / 2, 10],
                         [10, -h - 4], [10, 4], [-w - 10, -h - 4], [-w - 10, 4],
                         [-w / 2, -2 * h - 12], [-w / 2, h + 12]];
        let best = null, bestScore = Infinity;
        for (const [dx, dy] of options) {
          const r = { left: x + dx - 2, right: x + dx + w + 2, top: y + dy - 2, bottom: y + dy + h + 2 };
          const outside = (r.left < 0 || r.right > box.width || r.top < -6 || r.bottom > box.height + 6) ? 1e6 : 0;
          const score = outside + [...placed, ...dots].reduce((sum, s) => sum + overlap(r, s), 0);
          if (score < bestScore) { bestScore = score; best = r; }
          if (score === 0) break;
        }
        placed.push(best);
        lb.style.left = (best.left + 2) + 'px';
        lb.style.top = (best.top + 2) + 'px';
        // A label pushed away from its dot gets a hairline back to it.
        const nx = Math.max(best.left + 2, Math.min(x, best.right - 2));
        const ny = Math.max(best.top + 2, Math.min(y, best.bottom - 2));
        const len = Math.hypot(nx - x, ny - y);
        if (len > 16) {
          const line = document.createElement('span');
          line.className = 'sc-leader';
          line.style.left = x + 'px';
          line.style.top = y + 'px';
          line.style.width = (len - 2) + 'px';
          line.style.transform = 'rotate(' + Math.atan2(ny - y, nx - x) + 'rad)';
          plot.appendChild(line);
        }
      });
    });
  }
  placeLabels();
  window.addEventListener('resize', placeLabels);
  if (document.fonts) document.fonts.ready.then(placeLabels);

  // Leaderboard sorting.
  const board = document.getElementById('board');
  if (board) {
    const heads = [...board.querySelectorAll('th')];
    heads.forEach((th, col) => th.querySelector('button').addEventListener('click', () => {
      const asc = th.getAttribute('aria-sort') !== 'ascending';
      heads.forEach((h) => h.removeAttribute('aria-sort'));
      th.setAttribute('aria-sort', asc ? 'ascending' : 'descending');
      const body = board.tBodies[0];
      const rows = [...body.rows];
      rows.sort((a, b) => {
        const va = a.cells[col].dataset.sort, vb = b.cells[col].dataset.sort;
        const na = parseFloat(va), nb = parseFloat(vb);
        const cmp = isNaN(na) || isNaN(nb) ? va.localeCompare(vb) : na - nb;
        return asc ? cmp : -cmp;
      });
      rows.forEach((r) => body.appendChild(r));
    }));
  }
})();
"""


def main() -> None:
    results = json.loads(RESULTS.read_text())
    head, body = build(results)
    page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f'{head}\n</head>\n<body>{body}</body>\n</html>\n')
    (ROOT / "report.html").write_text(page)
    (ROOT / "results" / "report_artifact.html").write_text(f"{head}\n{body}")
    print(f"Wrote {ROOT / 'report.html'} ({len(page) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
