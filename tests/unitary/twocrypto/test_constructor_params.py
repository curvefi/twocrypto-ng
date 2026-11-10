"""
Constructor validation of the pool, independent of the factory that deploys it.

Legacy factories pack (allowed_extra_profit, adjustment_step, ma_exp_time) into
the slots this pool reads as (adjustment_step_min, adjustment_step_max, ma_time)
and check each slot's range but not their order, so the pool rejects a step
min above the step max, which would leave it unable to rebalance. These tests deploy the pool directly,
without a factory, so every bound checked here is the pool's own.
"""

import boa
import pytest

from tests.conftest import _deploy_pool
from tests.utils.constants import MAX_A, MAX_GAMMA, MIN_A, MIN_GAMMA, POOL_DEPLOYER
from tests.utils.god_mode import GodModePool

ZERO_ADDRESS = "0x" + "00" * 20
FORMER_MAGIC_GAMMA = 11111111111


def _pack_2(p1, p2):
    return p1 | (p2 << 128)


def _pack_3(x):
    return (x[0] << 128) | (x[1] << 64) | x[2]


def _deploy(coins, params, **overrides):
    p = {**params, "initial_price": params["initial_prices"][1], **overrides}
    precisions = [10 ** (18 - coin.decimals()) for coin in coins]
    return POOL_DEPLOYER.deploy(
        "Curve.fi USD<>WETH",
        "USD<>WETH",
        [coin.address for coin in coins],
        ZERO_ADDRESS,  # _math: ignored, the pool uses its embedded MATH
        b"\x00" * 32,  # _salt: ignored
        _pack_2(precisions[0], precisions[1]),
        _pack_2(p["gamma"], p["A"]),
        _pack_3([p["mid_fee"], p["out_fee"], p["fee_gamma"]]),
        _pack_3([p["adjustment_step_min"], p["adjustment_step_max"], p["ma_time"]]),
        p["initial_price"],
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"A": MIN_A},
        {"A": MAX_A},
        {"gamma": MIN_GAMMA},
        {"gamma": MAX_GAMMA},
        {"gamma": FORMER_MAGIC_GAMMA},
        {"fee_gamma": 1},
        {"fee_gamma": 10**18},
        {"adjustment_step_min": 0, "adjustment_step_max": 1},
        {"adjustment_step_min": 10**15, "adjustment_step_max": 10**15},
        {"adjustment_step_max": 10**18},
        {"ma_time": 87},
        {"ma_time": 872541},
        {"initial_price": 10**6 + 1},
        {"initial_price": 10**30 - 1},
    ],
)
def test_accepts_boundary_values(coins, params, overrides):
    p = {**params, "initial_price": params["initial_prices"][1], **overrides}
    pool = _deploy(coins, params, **overrides)

    assert pool.A() == p["A"]
    assert pool.gamma() == p["gamma"]
    assert pool.fee_gamma() == p["fee_gamma"]
    assert list(pool.adjustment_step()) == [p["adjustment_step_min"], p["adjustment_step_max"]]
    assert pool.packed_rebalancing_params() & (2**64 - 1) == p["ma_time"]
    assert pool.price_scale() == p["initial_price"]
    assert pool.last_prices() == p["initial_price"]


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"A": MIN_A - 1}, "A below minimum"),
        ({"A": MAX_A + 1}, "A above maximum"),
        ({"gamma": MIN_GAMMA - 1}, "gamma below minimum"),
        ({"gamma": MAX_GAMMA + 1}, "gamma above maximum"),
        (
            {"adjustment_step_min": 2 * 10**15, "adjustment_step_max": 10**15},
            "min adjustment above max",
        ),
    ],
)
def test_rejects_out_of_bounds(coins, params, overrides, reason):
    with boa.reverts(dev=f'"{reason}"'):
        _deploy(coins, params, **overrides)


def test_fee_split_defaults(pool):
    assert pool.admin_fee() == 5 * 10**9
    assert pool.reserved_profit_fraction() == 5 * 10**9
    assert pool.POLICY() == ZERO_ADDRESS


def test_initializer_and_allowlist_removed(pool):
    for name in ("initialize", "change_allowlist", "lp_allowlist"):
        assert not hasattr(pool, name), name


def test_former_magic_gamma_is_an_ordinary_gamma(factory, coins, params, deployer):
    p = {**params, "gamma": FORMER_MAGIC_GAMMA}
    pool = POOL_DEPLOYER.at(_deploy_pool(factory, p, coins, deployer))
    assert pool.gamma() == FORMER_MAGIC_GAMMA

    # no initialization step: the first deposit goes straight through
    gm_pool = GodModePool(pool)
    assert gm_pool.add_liquidity_balanced(10**24) > 0
    assert gm_pool.exchange(0, 10**21) > 0
