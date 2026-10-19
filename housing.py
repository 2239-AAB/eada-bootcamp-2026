"""Load and clean the Ames, Iowa housing data (De Cock 2011, OpenML id 43926).

Every step here is a fixed row-wise rule, so it can run before the train/test
split without leaking anything: nothing is learned from the data.
"""
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data" / "ames_housing.csv"
OPENML_ID = 43926
TARGET = "Sale_Price"

# De Cock's documentation flags five houses above 4,000 sq ft of living area:
# three partial sales of unfinished homes and two very large outliers. He
# recommends dropping them, so the model is scoped to homes up to 4,000 sq ft.
MAX_LIVING_AREA = 4000

QUALITY_5 = {"Poor": 1, "Fair": 2, "Typical": 3, "Good": 4, "Excellent": 5}
QUALITY_10 = {
    "Very_Poor": 1, "Poor": 2, "Fair": 3, "Below_Average": 4, "Average": 5,
    "Above_Average": 6, "Good": 7, "Very_Good": 8, "Excellent": 9, "Very_Excellent": 10,
}
# Ordered categories become numbers; anything absent from a map ("No_Garage",
# "No_Basement", ...) means the feature does not exist and becomes 0.
ORDINAL = {
    "Overall_Qual": QUALITY_10,
    "Overall_Cond": QUALITY_10,
    "Exter_Qual": QUALITY_5,
    "Exter_Cond": QUALITY_5,
    "Bsmt_Qual": QUALITY_5,
    "Bsmt_Cond": QUALITY_5,
    "Heating_QC": QUALITY_5,
    "Kitchen_Qual": QUALITY_5,
    "Fireplace_Qu": QUALITY_5,
    "Garage_Qual": QUALITY_5,
    "Garage_Cond": QUALITY_5,
    "Pool_QC": QUALITY_5,
    "Bsmt_Exposure": {"No": 1, "Mn": 2, "Av": 3, "Gd": 4},
    "BsmtFin_Type_1": {"Unf": 1, "LwQ": 2, "Rec": 3, "BLQ": 4, "ALQ": 5, "GLQ": 6},
    "BsmtFin_Type_2": {"Unf": 1, "LwQ": 2, "Rec": 3, "BLQ": 4, "ALQ": 5, "GLQ": 6},
    "Garage_Finish": {"Unf": 1, "RFn": 2, "Fin": 3},
    "Functional": {"Sal": 0, "Sev": 1, "Maj2": 2, "Maj1": 3, "Mod": 4, "Min2": 5, "Min1": 6, "Typ": 7},
    "Paved_Drive": {"Dirt_Gravel": 0, "Partial_Pavement": 1, "Paved": 2},
    "Lot_Shape": {"Irregular": 0, "Moderately_Irregular": 1, "Slightly_Irregular": 2, "Regular": 3},
    "Land_Slope": {"Sev": 0, "Mod": 1, "Gtl": 2},
    "Central_Air": {"N": 0, "Y": 1},
}

# Square-footage columns: right-skewed, so the linear models and the neural
# network see log1p of them (see models.py). Trees get the raw values.
AREA_COLUMNS = [
    "Lot_Frontage", "Lot_Area", "Mas_Vnr_Area", "BsmtFin_SF_1", "BsmtFin_SF_2",
    "Bsmt_Unf_SF", "Total_Bsmt_SF", "First_Flr_SF", "Second_Flr_SF",
    "Low_Qual_Fin_SF", "Gr_Liv_Area", "Garage_Area", "Wood_Deck_SF",
    "Open_Porch_SF", "Enclosed_Porch", "Three_season_porch", "Screen_Porch",
    "Pool_Area", "Misc_Val", "Total_SF", "Porch_SF", "Qual_x_Living_Area",
]


def download(path: Path = DATA) -> None:
    from sklearn.datasets import fetch_openml

    frame = fetch_openml(data_id=OPENML_ID, as_frame=True, parser="auto").frame
    path.parent.mkdir(exist_ok=True)
    frame.to_csv(path, index=False)


def read_raw(path: Path = DATA) -> pd.DataFrame:
    """The data as exported, one row per sale, before any cleaning."""
    if not path.exists():
        download(path)
    # "None" is a real category here (no masonry veneer, no misc feature),
    # so pandas must not read it as missing.
    return pd.read_csv(path, keep_default_na=False, na_values=[""])


def load(path: Path = DATA) -> tuple[pd.DataFrame, pd.Series, dict]:
    """Return features X, sale price y in USD, and notes on what was changed."""
    df = read_raw(path)
    raw_rows, raw_features = len(df), df.shape[1] - 1

    dropped = df["Gr_Liv_Area"] > MAX_LIVING_AREA
    df = prepare(df.loc[~dropped].reset_index(drop=True))

    y = df.pop(TARGET).astype(float)
    notes = {
        "raw_rows": raw_rows,
        "raw_features": raw_features,
        "dropped_over_4000_sqft": int(dropped.sum()),
        "rows": len(df),
        "years_sold": [int(df["Year_Sold"].min()), int(df["Year_Sold"].max())],
        "neighborhoods": int(df["Neighborhood"].nunique()),
        "features": df.shape[1],
        "engineered": ["Lot_Frontage_Missing", "Total_SF", "Total_Baths", "House_Age",
                       "Years_Since_Remodel", "Porch_SF", "Qual_x_Living_Area"],
        "ordinal_encoded": list(ORDINAL),
    }
    return df, y, notes


def prepare(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn raw rows (same columns as the export) into model inputs."""
    df = raw.copy()
    # In this export BsmtFin_SF_1 holds the BsmtFin_Type_1 category code, not
    # square feet (a known bug in the AmesHousing R package). The real value
    # is what is left of the basement after the other two parts.
    df["BsmtFin_SF_1"] = (df["Total_Bsmt_SF"] - df["BsmtFin_SF_2"] - df["Bsmt_Unf_SF"]).clip(lower=0)

    for col, mapping in ORDINAL.items():
        df[col] = df[col].map(mapping).fillna(0).astype(int)

    # Lot frontage was missing for 490 houses and exported as 0.
    df["Lot_Frontage_Missing"] = (df["Lot_Frontage"] == 0).astype(int)
    df["Total_SF"] = df["Total_Bsmt_SF"] + df["Gr_Liv_Area"]
    df["Total_Baths"] = (df["Full_Bath"] + 0.5 * df["Half_Bath"]
                         + df["Bsmt_Full_Bath"] + 0.5 * df["Bsmt_Half_Bath"])
    df["House_Age"] = (df["Year_Sold"] - df["Year_Built"]).clip(lower=0)
    df["Years_Since_Remodel"] = (df["Year_Sold"] - df["Year_Remod_Add"]).clip(lower=0)
    df["Porch_SF"] = df[["Wood_Deck_SF", "Open_Porch_SF", "Enclosed_Porch",
                         "Three_season_porch", "Screen_Porch"]].sum(axis=1)
    df["Qual_x_Living_Area"] = df["Overall_Qual"] * df["Gr_Liv_Area"]
    return df


def column_types(X: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    """Split columns into (area, other numeric, nominal) groups."""
    numeric = X.select_dtypes(include=np.number).columns.tolist()
    nominal = [c for c in X.columns if c not in numeric]
    area = [c for c in AREA_COLUMNS if c in numeric]
    other = [c for c in numeric if c not in area]
    return area, other, nominal
