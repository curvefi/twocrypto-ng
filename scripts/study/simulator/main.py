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

    # main loop
    for i in range(100):
        logger.info(f"Iteration {i}")
        s0 = snapshot_all_normalized(lp_user=lp, trader=trader, admin=admin, pool=pool)
        # Add liquidity
        lp.add_liquidity()
        s1 = snapshot_all_normalized(lp_user=lp, trader=trader, admin=admin, pool=pool)

        # Washtrade (move price with rebalances)
        trader.wash(
            fee_pct=0.01,
            price_shift=0.02,
            trade_size=500_000 * 10**18,
            balance_precision=1e-7,
            max_trades=100,
        )
        # Washtrade (move price back!)
        price_diff = (pool.price_scale() - initial_price * WAD) / pool.price_scale()
        trader.wash(
            fee_pct=0.01,
            price_shift=-price_diff,
            trade_size=500_000 * 10**18,
            balance_precision=1e-7,
            max_trades=100,
        )

        s2 = snapshot_all_normalized(lp_user=lp, trader=trader, admin=admin, pool=pool)

        # Claim admin fees
        admin.claim_fees()
        s3 = snapshot_all_normalized(lp_user=lp, trader=trader, admin=admin, pool=pool)

        # Remove LP
        lp.remove_liquidity()
        s4 = snapshot_all_normalized(lp_user=lp, trader=trader, admin=admin, pool=pool)
        data = {
            "iteration": i,
            "init": s0,
            "add_liquidity": s1,
            "washtrade": s2,
            "claim_fees": s3,
            "remove_liquidity": s4,
        }
        logger.info(
            f"Iteration {i} complete: "
            f"Pool value: {s4['pool']['total_value']:.4f}, "
            f"LP value: {s4['lp_user']['total_value']:.4f}, "
            f"Trader value: {s4['trader']['total_value']:.4f}, "
            f"Admin value: {s4['admin']['total_value']:.4f}"
        )
        df = pd.concat([df, pd.DataFrame([flatten_dict(data)])], ignore_index=True)
    # save to current directory
    # df.to_csv("pool_simulation_results.csv", index=False)
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    df.to_csv(os.path.join(cur_dir, "pool_simulation_results.csv"), index=False)
