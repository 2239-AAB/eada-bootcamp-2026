# EADA Bootcamp 2026: house prices

Two parts, built on the same data:

1. **Model comparison.** Eight regression models predict house prices for 2,925 sales in Ames, Iowa
   (2006–2010). An HTML report (`report.html`) compares them on accuracy, training time, overfitting
   and errors by price band, and includes a calculator that moves prices to any quarter up to 2030
   with the local house price index.
2. **Ownly** (`ownly/`). A website for homes sold by their owners: sign up, list a home with photos and
   a map pin, browse on a map, and message sellers. Every listing shows the Ownly estimate from the
   winning model. See [ownly/README.md](ownly/README.md).

## Results

Scored once on 585 houses the models never saw, after tuning with 5-fold cross-validation on the rest:

| Model | Typical error (MAPE) | Within ±10% | Time to train once |
|---|---|---|---|
| Stacked ensemble | 6.9% | 81% | 26 s |
| **XGBoost** | **6.9%** | **82%** | **0.7 s** |
| Neural network (small MLP) | 7.5% | 77% | 0.8 s |
| Elastic net | 7.7% | 76% | 0.3 s |
| Linear regression | 7.7% | 75% | 0.05 s |
| Random forest | 8.1% | 76% | 3.6 s |
| Decision tree | 12.0% | 55% | 0.05 s |
| Median price (baseline) | 31.4% | 21% | – |

XGBoost matches the stacked ensemble on unseen houses and trains about 35 times faster, so Ownly uses it.
The prices are 2006–2010 prices; the FHFA index for the Ames metro roughly doubles them to today.

## Run

Python 3.13 and [uv](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python train.py     # tunes, cross-validates and tests every model (about 2 minutes)
.venv/bin/python report.py    # writes report.html
.venv/bin/python -m ownly     # the website, on http://127.0.0.1:8720
.venv/bin/python -m pytest    # Ownly's tests
```

`train.py --quick` runs a smaller tuning search for a quick check. The repository includes the trained
XGBoost model (`results/models/xgb.joblib`) so Ownly runs without training first; `train.py` rebuilds it
and the other seven.

On macOS, XGBoost needs an OpenMP runtime. If Homebrew's `libomp` is missing, `models.py` restarts
Python once and points it at the copy scikit-learn ships. An interactive session (Jupyter, the Python
prompt) cannot restart itself: run `brew install libomp`, or start it with
`DYLD_FALLBACK_LIBRARY_PATH=.venv/lib/python3.13/site-packages/sklearn/.dylibs`.

## Files

| File | What it does |
|---|---|
| `housing.py` | Loads the data (downloads it from OpenML on first run), fixes known export bugs, adds features |
| `models.py` | Preprocessing, the eight models and their tuning ranges |
| `train.py` | 80/20 split, 5-fold CV tuning, hold-out scoring, bootstrap intervals → `results/results.json` |
| `report.py` | Turns `results/results.json` into `report.html` |
| `price_index.py` | The FHFA house price index for the Ames metro, from FRED (cached in `data/ames_hpi.csv`); `factor("2026Q4")` moves a mid-2010 price to that quarter |
| `calculator.py` | Writes XGBoost into the report as JavaScript for the in-page calculator, and checks it matches |
| `ownly/` | The website (Flask + SQLite) |

## Data and credits

- **Ames Housing** by Dean De Cock, *Journal of Statistics Education* 19(3), 2011, via
  [OpenML dataset 43926](https://www.openml.org/d/43926). Five houses over 4,000 sq ft are dropped, as De Cock recommends.
- **House price index:** FHFA All-Transactions House Price Index for Ames, IA, via
  [FRED](https://fred.stlouisfed.org/series/ATNHPIUS11180Q).
- **Maps:** [Leaflet](https://leafletjs.com) 1.9.4 (BSD-2-Clause, bundled in `ownly/static/vendor/leaflet/`) and
  map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
