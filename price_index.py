"""Move model prices from 2010 to a later quarter with the local house price index.

The models learned 2006-2010 prices, so a prediction answers "what would this
house have sold for then?". The FHFA all-transactions index for the Ames
metro area tracks repeat sales of the same houses, so the ratio between two
quarters is how much a typical Ames home's value changed in between.
"""
from pathlib import Path

import pandas as pd

SERIES = "ATNHPIUS11180Q"  # FHFA All-Transactions House Price Index, Ames, IA (MSA)
SOURCE = f"https://fred.stlouisfed.org/series/{SERIES}"
URL = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES}"
CACHE = Path(__file__).parent / "data" / "ames_hpi.csv"

# Predictions are made as if the house sold in June 2010, the last month the
# data covers well, so the index ratio starts from that quarter.
BASE_YEAR, BASE_MONTH = 2010, 6
BASE = pd.Period(year=BASE_YEAR, quarter=2, freq="Q")


def load(refresh: bool = False) -> pd.Series:
    """Quarterly index values, from FRED on first use and from the cache after."""
    if refresh or not CACHE.exists():
        frame = pd.read_csv(URL)
        CACHE.parent.mkdir(exist_ok=True)
        frame.to_csv(CACHE, index=False)
    frame = pd.read_csv(CACHE).dropna()
    return pd.Series(frame[SERIES].astype(float).values,
                     index=pd.PeriodIndex(frame["observation_date"], freq="Q"), name=SERIES)


def trailing_growth(hpi: pd.Series, years: int) -> float:
    latest = hpi.index[-1]
    return (hpi[latest] / hpi[latest - 4 * years]) ** (1 / years) - 1


def factor(quarter: str | None = None, hpi: pd.Series | None = None) -> dict:
    """How much to multiply a June-2010 price by to get a price in `quarter`.

    Published quarters use the index as is. Later quarters extend the recent
    trend: the central value uses the two-year growth rate, and the range spans
    the one- and two-year rates. Projections are guesses, not measurements.
    """
    hpi = load() if hpi is None else hpi
    latest = hpi.index[-1]
    target = pd.Period(quarter, freq="Q") if quarter else latest
    base = hpi[BASE]
    if target <= latest:
        value = hpi[target]
        return {"quarter": str(target), "factor": value / base, "low": value / base,
                "high": value / base, "projected": False, "latest": str(latest)}
    quarters_ahead = (target - latest).n
    rates = [trailing_growth(hpi, 1), trailing_growth(hpi, 2)]
    grow = [(1 + r) ** (quarters_ahead / 4) for r in rates]
    return {"quarter": str(target), "factor": hpi[latest] * grow[1] / base,
            "low": hpi[latest] * min(grow) / base, "high": hpi[latest] * max(grow) / base,
            "projected": True, "latest": str(latest), "growth_rates": rates}
