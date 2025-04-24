import logging
import pandas as pd
from pool import Pool, WAD
from actors import Trader, LP, Admin
import os

logger = logging.getLogger(__name__)


def flatten_dict(d, parent_key="", sep="_"):
    """
    Recursively flatten a nested dictionary into a single-level dictionary
    with keys joined by sep.

    Example:
    {'a': 1, 'b': {'c': 2}} -> {'a': 1, 'b_c': 2}
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def snapshot_all(lp_user, trader, admin, pool):
    """Capture snapshot of all actors and pool state"""
    return {
        "lp_user": lp_user.snapshot(),
        "trader": trader.snapshot(),
        "admin": admin.snapshot(),
        "pool": pool.snapshot(),
    }


def snapshot_all_normalized(lp_user, trader, admin, pool):
    """Capture normalized snapshot (with values in coin0 terms)"""
    return {
        "lp_user": lp_user.snapshot_normalized(),
        "trader": trader.snapshot_normalized(),
        "admin": admin.snapshot_normalized(),
        "pool": pool.snapshot_normalized(),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

    # Use default pool parameters
    params = {
        "A": 400_000,
        "gamma": 145_000_000_000_000,
        "mid_fee": 26_000_000,
        "out_fee": 45_000_000,
        "fee_gamma": 230_000_000_000_000,
        "allowed_extra_profit": 2_000_000_000_000,
        "adjustment_step": 146_000_000_000_000,
        "ma_exp_time": 866,
    }
    initial_price = 1_500
    pool = Pool(params=params, initial_price=initial_price)

    # Dead LP user to initialize pool
    dead_lp_rate = 0.0001
    dead_lp_amounts = [int(dead_lp_rate * WAD), int(dead_lp_rate * WAD // initial_price)]
    dead_lp = LP(pool, initial_amounts=dead_lp_amounts)
    dead_lp.add_liquidity(dead_lp_amounts)

    # Admin that would take fees
    admin = Admin(pool)

    # Trader that will washtrade the pool
    trader_amounts = [5_000_000 * WAD, 5_000_000 * WAD // initial_price]
    trader = Trader(pool, initial_amounts=trader_amounts)

    # LP that will provide liquidity to the pool
    lp_amounts = [1_000_000 * WAD, 1_000_000 * WAD // initial_price]
    lp = LP(pool, initial_amounts=lp_amounts)

    # Create a single DataFrame to store all snapshots
    df = pd.DataFrame()
    lp.add_liquidity()

    # main loop
    N_ITER = 200
    AMT_SWAP = 1_000_000
    # FREQ_DIR_SWAP = 50
    N_FLIP_DIR = 9
    FREQ_DIR_SWAP = N_ITER // (N_FLIP_DIR)
    for i in range(N_ITER):
        logger.info(f"Iteration {i}")
        bal_lp, val_lp = lp.sim_remove_liquidity()
        print(f"bal_lp: {bal_lp}\nval_lp: {val_lp}")
        s0 = snapshot_all_normalized(lp_user=lp, trader=trader, admin=admin, pool=pool)
        # if i==N_ITER//2:
        if i % 20 == 0 and i > 0:
            admin.claim_fees()
            trade = False
        # elif i < N_ITER//2:
        elif i % (FREQ_DIR_SWAP * 2) < FREQ_DIR_SWAP:
            amt = AMT_SWAP
            direction = 0
            trade = True
        else:
            amt = int(AMT_SWAP / s0["pool"]["price_scale"])
            direction = 1
            trade = True
        # Add liquidity
        if trade:
            out = trader.trade(direction, amt * WAD, update_ema=True)

        s1 = snapshot_all_normalized(lp_user=lp, trader=trader, admin=admin, pool=pool)

        rebalance_happened = s0["pool"]["price_scale"] != s1["pool"]["price_scale"]
        data = {
            "iteration": i,
            "data": s0,
            "rebalance_happened": rebalance_happened,
            "fees_claimed": s0["admin"]["balances"][0] < s1["admin"]["balances"][0],
        }

        logger.info(
            f"Iteration {i} complete: "
            f"Pool value: {s1['pool']['total_value']:.4f}, "
            f"LP value: {s1['lp_user']['total_value']:.4f}, "
            f"Trader value: {s1['trader']['total_value']:.4f}, "
            f"Admin value: {s1['admin']['total_value']:.4f}\n"
            f"Rebalance happened: {rebalance_happened}"
        )
        df = pd.concat([df, pd.DataFrame([flatten_dict(data)])], ignore_index=True)
    # save to current directory
    # df.to_csv("pool_simulation_results.csv", index=False)
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    # fname = f"sim_data/sim_{int(time.time())}.csv"
    fname = "sim_data/sim_data.csv"
    df.to_csv(os.path.join(cur_dir, fname), index=False)
    logger.info(f"Saved to {fname}")
