"""The models under comparison, their preprocessing, and their tuning ranges.

Every model predicts log(price), standardised, and is wrapped so that
.predict() returns dollars. Working in log space makes the loss care about
percentage error, so a $20k miss on a $100k house counts more than the same
miss on a $500k house.
"""
import os
import sys
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import loguniform, randint, uniform
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor, StackingRegressor
from sklearn.linear_model import ElasticNet, LinearRegression
from sklearn.model_selection import KFold
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeRegressor

try:
    from xgboost import XGBRegressor
except Exception:
    # XGBoost's macOS wheel looks for Homebrew's OpenMP runtime. Without
    # Homebrew, restart once pointing it at the copy scikit-learn ships.
    # An interactive session cannot be restarted; see the README there.
    interactive = hasattr(sys, "ps1") or "ipykernel" in sys.modules
    if sys.platform != "darwin" or "DYLD_FALLBACK_LIBRARY_PATH" in os.environ or interactive:
        raise
    import sklearn

    dylibs = os.path.join(os.path.dirname(sklearn.__file__), ".dylibs")
    os.execve(sys.executable, [sys.executable, *sys.orig_argv[1:]],
              dict(os.environ, DYLD_FALLBACK_LIBRARY_PATH=dylibs))

SEED = 42


def cv_folds(n_splits: int = 5) -> KFold:
    return KFold(n_splits=n_splits, shuffle=True, random_state=SEED)


def preprocessor(area, other, nominal, kind: str) -> ColumnTransformer:
    """'linear' scales and logs areas; 'tree' passes numbers through as they are."""
    onehot = OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=10,
                           sparse_output=False)
    if kind == "linear":
        log_scale = Pipeline([("log", FunctionTransformer(np.log1p)), ("scale", StandardScaler())])
        parts = [("area", log_scale, area), ("num", StandardScaler(), other)]
    else:
        parts = [("num", "passthrough", area + other)]
    return ColumnTransformer(parts + [("cat", onehot, nominal)])


def target_transform() -> Pipeline:
    log = FunctionTransformer(np.log, inverse_func=np.exp, check_inverse=False)
    return Pipeline([("log", log), ("scale", StandardScaler())])


def wrap(prep: ColumnTransformer, model) -> TransformedTargetRegressor:
    return TransformedTargetRegressor(
        regressor=Pipeline([("prep", prep), ("model", model)]),
        transformer=target_transform(),
    )


@dataclass
class Spec:
    key: str
    name: str
    family: str
    blurb: str
    model: object
    prep: str
    params: dict = field(default_factory=dict)
    n_iter: int = 20

    def build(self, area, other, nominal) -> TransformedTargetRegressor:
        return wrap(preprocessor(area, other, nominal, self.prep), self.model)

    def search_space(self) -> dict:
        return {f"regressor__model__{k}": v for k, v in self.params.items()}


# n_jobs=1 inside each model: parallelism happens across CV folds and search
# candidates instead, and single-threaded fits give comparable timings.
SPECS = [
    Spec("baseline", "Median price", "Baseline",
         "Predicts the median training price for every house. Anything useful has to beat it.",
         DummyRegressor(strategy="median"), "linear", n_iter=0),
    Spec("ols", "Linear regression", "Linear",
         "Ordinary least squares on log price. No tuning, no regularisation.",
         LinearRegression(), "linear", n_iter=0),
    Spec("enet", "Elastic net", "Linear",
         "Linear regression with L1 + L2 penalties that shrink and drop weak features.",
         ElasticNet(max_iter=50_000, random_state=SEED), "linear",
         {"alpha": loguniform(1e-4, 3e-1), "l1_ratio": uniform(0.05, 0.95)}),
    Spec("tree", "Decision tree", "Tree",
         "One tree of yes/no splits. Easy to read, prone to memorising the data.",
         DecisionTreeRegressor(random_state=SEED), "tree",
         {"max_depth": randint(3, 16), "min_samples_leaf": randint(1, 30),
          "max_features": [None, 0.8, 0.5, 0.3]}),
    Spec("rf", "Random forest", "Tree ensemble",
         "300 deep trees on bootstrap samples, averaged.",
         RandomForestRegressor(n_estimators=300, n_jobs=1, random_state=SEED), "tree",
         {"max_features": [0.2, 0.33, 0.5, 0.75], "min_samples_leaf": [1, 2, 4],
          "max_depth": [None, 12, 20]}, n_iter=12),
    Spec("xgb", "XGBoost", "Tree ensemble",
         "Gradient-boosted shallow trees, each one correcting the errors of the ones before.",
         XGBRegressor(tree_method="hist", n_jobs=1, random_state=SEED), "tree",
         {"n_estimators": randint(300, 1500), "learning_rate": loguniform(0.01, 0.15),
          "max_depth": randint(2, 7), "min_child_weight": randint(1, 10),
          "subsample": uniform(0.5, 0.5), "colsample_bytree": uniform(0.2, 0.8),
          "reg_lambda": loguniform(0.1, 10)}, n_iter=25),
    Spec("mlp", "Neural network", "Neural network",
         "A small multilayer perceptron (one or two hidden layers, at most 128 units).",
         MLPRegressor(early_stopping=True, max_iter=2000, random_state=SEED), "linear",
         {"hidden_layer_sizes": [(32,), (64,), (128,), (64, 32), (128, 64)],
          "alpha": loguniform(1e-3, 30), "learning_rate_init": loguniform(3e-4, 1e-2),
          "batch_size": [32, 64, 128]}),
]

STACK_KEY = "stack"
STACK_NAME = "Stacked ensemble"
STACK_BLURB = ("Feeds out-of-fold predictions from the tuned elastic net, random forest, "
               "XGBoost and neural network into a linear blender with non-negative weights.")
STACK_MEMBERS = ["enet", "rf", "xgb", "mlp"]


def build_stack(tuned: dict[str, TransformedTargetRegressor]) -> TransformedTargetRegressor:
    """Blend the tuned members. Each member keeps its own preprocessing."""
    members = [(key, tuned[key].regressor) for key in STACK_MEMBERS]
    stack = StackingRegressor(members, final_estimator=LinearRegression(positive=True),
                              cv=cv_folds(), n_jobs=1)
    return TransformedTargetRegressor(regressor=stack, transformer=target_transform())
