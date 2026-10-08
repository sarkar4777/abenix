"""Train the next-hour power price model used by the battery desk journey.

Features, in order: hour (0-23), demand_gw, wind_gw. Target: price in EUR/MWh.
The data is synthetic with a fixed seed, so the file is the same on every run.

    python e2e/fixtures/battery_desk/train_price_model.py
"""

import pathlib

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

here = pathlib.Path(__file__).parent
rng = np.random.default_rng(7)
n = 4000

hour = rng.integers(0, 24, n)
demand = rng.uniform(28, 60, n)
wind = rng.uniform(0, 30, n)
evening = ((hour >= 17) & (hour <= 21)).astype(float)
morning = ((hour >= 7) & (hour <= 9)).astype(float)
price = 20 + 1.6 * demand - 2.2 * wind + 30 * evening + 12 * morning + rng.normal(0, 4, n)

X = np.column_stack([hour, demand, wind])
model = GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.08, random_state=0)
model.fit(X, price)

joblib.dump(model, here / "price_model.joblib")
for row in ([19, 55, 5], [3, 32, 25], [13, 45, 12]):
    print(row, round(float(model.predict([row])[0]), 1))
