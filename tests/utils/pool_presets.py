# read from csv file with the same name
import os

import pandas as pd

script_dir = os.path.dirname(__file__)
csv_path = os.path.join(script_dir, "pool_presets.csv")

df = pd.read_csv(csv_path)

all_presets = df.iloc[0:].to_dict(orient="records")

numeric_columns = [
    "A",
    "gamma",
    "mid_fee",
    "out_fee",
    "fee_gamma",
    "allowed_extra_profit",
    "adjustment_step",
    "ma_exp_time",
]

all_presets = [
    {k: int(v) if k in numeric_columns else v for k, v in d.items()}
    for d in all_presets
]


def get_preset_by_name(name):
    return [d for d in all_presets if d["name"] == name][0]
