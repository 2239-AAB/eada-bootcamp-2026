"""Tune, cross-validate and test every model, then write results/results.json.

    .venv/bin/python train.py            # full run, about two minutes
    .venv/bin/python train.py --quick    # fewer tuning draws, for smoke tests

Protocol: 80/20 split stratified by price. All tuning and model selection use
5-fold cross-validation inside the 80%. The 20% hold-out is scored once per
model, after every choice has been made.
"""
import argparse
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import models  # first: it may restart the interpreter to find OpenMP for XGBoost

import joblib
import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.base import clone
from sklearn.inspection import permutation_importance
from sklearn.metrics import r2_score
from sklearn.model_selection import RandomizedSearchCV, cross_validate, train_test_split

import housing

OUT = Path(__file__).parent / "results"
SCORING = "neg_root_mean_squared_log_error"


def kpis(y, p) -> dict:
    y, p = np.asarray(y, float), np.asarray(p, float)
    err = p - y
    pct = err / y
    ape = np.abs(pct)
    return {
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "mae": float(np.mean(np.abs(err))),
        "medae": float(np.median(np.abs(err))),
        "mape": float(100 * ape.mean()),
        "mdape": float(100 * np.median(ape)),
        "r2": float(r2_score(y, p)),
        "rmsle": float(np.sqrt(np.mean((np.log(p) - np.log(y)) ** 2))),
        "within10": float(100 * np.mean(ape <= 0.10)),
        "within20": float(100 * np.mean(ape <= 0.20)),
        "bias": float(100 * np.median(pct)),  # median signed error; + means it overvalues
    }


def plain(value):
    """Make tuned parameters JSON-friendly."""
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, tuple):
        return list(value)
    return value


def tune(spec, estimator, X, y, n_iter_scale: float):
    if not spec.params:
        return estimator, None
    search = RandomizedSearchCV(
        estimator, spec.search_space(), n_iter=max(3, round(spec.n_iter * n_iter_scale)),
        scoring=SCORING, cv=models.cv_folds(), n_jobs=-1, random_state=models.SEED,
    )
    started = time.perf_counter()
    search.fit(X, y)
    info = {
        "seconds": time.perf_counter() - started,
        "candidates": len(search.cv_results_["params"]),
        "best_params": {k.removeprefix("regressor__model__"): plain(v)
                        for k, v in search.best_params_.items()},
    }
    return search.best_estimator_, info


def evaluate(estimator, X_train, y_train, X_test, y_test) -> dict:
    """Out-of-fold scores on the training set, then one score on the hold-out."""
    cv = cross_validate(estimator, X_train, y_train, cv=models.cv_folds(), scoring=SCORING,
                        return_estimator=True, return_indices=True, n_jobs=-1)
    oof = np.empty(len(y_train))
    folds = []
    for fitted, idx in zip(cv["estimator"], cv["indices"]["test"]):
        oof[idx] = fitted.predict(X_train.iloc[idx])
        folds.append(kpis(y_train.iloc[idx], oof[idx]))

    started = time.perf_counter()
    final = clone(estimator).fit(X_train, y_train)
    fit_seconds = time.perf_counter() - started
    started = time.perf_counter()
    p_test = final.predict(X_test)
    predict_seconds = time.perf_counter() - started

    return {
        "final": final,
        "p_test": p_test,
        "cv": {
            "folds": folds,
            "oof": kpis(y_train, oof),
            "rmsle_mean": float(np.mean([f["rmsle"] for f in folds])),
            "rmsle_std": float(np.std([f["rmsle"] for f in folds], ddof=1)),
        },
        "train": kpis(y_train, final.predict(X_train)),
        "test": kpis(y_test, p_test),
        "fit_seconds": fit_seconds,
        "predict_ms_per_1000": predict_seconds / len(X_test) * 1000 * 1000,
    }


def bootstrap(y_test, preds: dict, winner: str, draws: int) -> dict:
    """95% intervals on the hold-out, resampling the same houses for every model."""
    y = np.asarray(y_test, float)
    idx = np.random.default_rng(models.SEED).integers(0, len(y), size=(draws, len(y)))

    def resampled(p):
        log_err = np.log(p) - np.log(y)
        ape = np.abs(p - y) / y
        return (np.sqrt(np.mean(log_err[idx] ** 2, axis=1)),
                100 * np.mean(ape[idx], axis=1),
                100 * np.mean(ape[idx] <= 0.10, axis=1))

    best_rmsle = resampled(preds[winner])[0]
    out = {}
    for key, p in preds.items():
        rmsle, mape, within10 = resampled(p)
        diff = rmsle - best_rmsle
        out[key] = {
            "rmsle_ci": np.percentile(rmsle, [2.5, 97.5]).tolist(),
            "mape_ci": np.percentile(mape, [2.5, 97.5]).tolist(),
            "within10_ci": np.percentile(within10, [2.5, 97.5]).tolist(),
            "rmsle_diff_vs_winner_ci": np.percentile(diff, [2.5, 97.5]).tolist(),
            "share_beating_winner": float(np.mean(diff < 0)),
        }
    return out


def price_bands(y_test, preds: dict, n_bands: int = 5) -> dict:
    bands = pd.qcut(y_test, n_bands)
    labels = [{"low": float(b.left), "high": float(b.right)} for b in bands.cat.categories]
    rows = {}
    for key, p in preds.items():
        frame = pd.DataFrame({"y": y_test.values, "p": p, "band": bands.cat.codes.values})
        frame["pct"] = 100 * (frame.p - frame.y) / frame.y
        grouped = frame.groupby("band")["pct"]
        rows[key] = {"mape": grouped.apply(lambda s: s.abs().mean()).tolist(),
                     "bias": grouped.median().tolist()}
    counts = bands.value_counts(sort=False).tolist()
    return {"bands": labels, "counts": counts, "models": rows}


def main(quick: bool) -> None:
    started = time.perf_counter()
    X, y, data_notes = housing.load()
    area, other, nominal = housing.column_types(X)
    strata = pd.qcut(y, 5, labels=False)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=strata, random_state=models.SEED)
    print(f"{len(X_train)} train / {len(X_test)} test houses, {X.shape[1]} input columns")

    results, tuned, fitted, preds = {}, {}, {}, {}
    entries = [(s.key, s.name, s.family, s.blurb, s) for s in models.SPECS]
    entries.append((models.STACK_KEY, models.STACK_NAME, "Ensemble", models.STACK_BLURB, None))
    for key, name, family, blurb, spec in entries:
        t0 = time.perf_counter()
        if spec is None:
            estimator, search_info = models.build_stack(tuned), None
        else:
            estimator, search_info = tune(spec, spec.build(area, other, nominal), X_train,
                                          y_train, 0.25 if quick else 1.0)
        tuned[key] = estimator
        scored = evaluate(estimator, X_train, y_train, X_test, y_test)
        preds[key] = scored.pop("p_test")
        fitted[key] = scored.pop("final")
        results[key] = {"key": key, "name": name, "family": family, "blurb": blurb,
                        "tuning": search_info, **scored}
        if key == models.STACK_KEY:
            blender = fitted[key].regressor_.final_estimator_
            results[key]["weights"] = dict(zip(models.STACK_MEMBERS, blender.coef_.tolist()))
        if not quick:
            joblib.dump(fitted[key], OUT / "models" / f"{key}.joblib")
        print(f"  {name:20s} CV RMSLE {scored['cv']['rmsle_mean']:.4f} ± {scored['cv']['rmsle_std']:.4f}"
              f"  test MAPE {scored['test']['mape']:5.2f}%  ({time.perf_counter() - t0:5.1f}s)")

    # Pick the winner on cross-validation only, so the hold-out stays an honest check.
    contenders = [k for k in results if k != "baseline"]
    winner = min(contenders, key=lambda k: results[k]["cv"]["rmsle_mean"])
    print(f"Winner by CV: {results[winner]['name']}")

    importance = permutation_importance(
        fitted[winner], X_test, y_test, scoring=SCORING, n_repeats=5 if not quick else 2,
        random_state=models.SEED, n_jobs=-1)
    order = np.argsort(importance.importances_mean)[::-1]
    top_features = [{"feature": X.columns[i], "mean": float(importance.importances_mean[i]),
                     "std": float(importance.importances_std[i])} for i in order[:15]]

    widths = {kind: models.preprocessor(area, other, nominal, kind).fit(X_train).transform(
        X_train.head(1)).shape[1] for kind in ("linear", "tree")}

    test_rows = X_test[["Neighborhood", "Gr_Liv_Area", "Year_Built"]].assign(actual=y_test.values)
    report = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runtime_seconds": time.perf_counter() - started,
        "quick": quick,
        "environment": {"python": platform.python_version(), "sklearn": sklearn.__version__,
                        "xgboost": xgboost.__version__, "machine": platform.machine(),
                        "cpus": os.cpu_count()},
        "data": {**data_notes, "train_rows": len(X_train), "test_rows": len(X_test),
                 "area_columns": len(area), "numeric_columns": len(other),
                 "nominal_columns": len(nominal), "model_inputs": widths,
                 "price": {q: float(y.quantile(v)) for q, v in
                           {"min": 0, "p25": .25, "median": .5, "p75": .75, "max": 1}.items()},
                 "price_mean": float(y.mean())},
        "winner": winner,
        "models": results,
        "bootstrap": bootstrap(y_test, preds, winner, 500 if quick else 2000),
        "price_bands": price_bands(y_test, preds),
        "importance": {"model": winner, "features": top_features},
        "test_points": {
            "actual": y_test.round().astype(int).tolist(),
            "neighborhood": test_rows["Neighborhood"].str.replace("_", " ").tolist(),
            "living_area": test_rows["Gr_Liv_Area"].astype(int).tolist(),
            "year_built": test_rows["Year_Built"].astype(int).tolist(),
            "predicted": {k: np.round(p).astype(int).tolist() for k, p in preds.items()},
        },
    }
    (OUT / "results.json").write_text(json.dumps(report, indent=1))
    print(f"Wrote {OUT / 'results.json'} in {report['runtime_seconds']:.0f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="fewer tuning draws and bootstrap samples")
    args = parser.parse_args()
    (OUT / "models").mkdir(parents=True, exist_ok=True)
    main(args.quick)
