# read from csv file with the same name
import pandas as pd

df = pd.read_csv("tests/utils/pool_presets.csv")

all_presets = df.iloc[1:].to_dict(orient="records")

numeric_columns = [
    "A",
    "gamma",
    "mid_fee",
    "out_fee",
    "fee_gamma",
    "adjustment_step_min",
    "adjustment_step_max",
    "ma_exp_time",
]

all_presets = [
    {k: int(v) if k in numeric_columns else v for k, v in d.items()} for d in all_presets
]
