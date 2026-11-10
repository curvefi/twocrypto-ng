"""
The pool deployed through the legacy CurveTwocryptoFactory.

tests/reference/CurveTwocryptoFactory.vy is the production legacy factory
source (Vyper 0.3.10). The rollout replaces its pool_implementations[0] with
this pool's blueprint and points its math_implementation at TwocryptoMath. Its
views_implementation is left alone: existing pools read it on every quote,
while this pool uses its embedded VIEW.
"""

import boa
import pytest

from tests.utils.constants import POOL_DEPLOYER
from tests.utils.god_mode import GodModePool

LEGACY_FACTORY = "tests/reference/CurveTwocryptoFactory.vy"
ZERO_ADDRESS = "0x" + "00" * 20


@pytest.fixture(scope="module")
def legacy_factory_deployer():
    return boa.load_partial(LEGACY_FACTORY)


def _new_legacy_factory(legacy_factory_deployer, deployer, fee_receiver, owner):
    with boa.env.prank(deployer):
        factory = legacy_factory_deployer.deploy()
        factory.initialise_ownership(fee_receiver, owner)
    return factory


@pytest.fixture(scope="module")
def legacy_factory(
    legacy_factory_deployer,
    deployer,
    fee_receiver,
    owner,
    amm_implementation,
    math_contract,
    gauge_implementation,
):
    factory = _new_legacy_factory(legacy_factory_deployer, deployer, fee_receiver, owner)
    with boa.env.prank(owner):
        factory.set_pool_implementation(amm_implementation.address, 0)
        factory.set_math_implementation(math_contract.address)
        factory.set_gauge_implementation(gauge_implementation.address)
    return factory


def _legacy_deploy_pool(factory, params, coins, sender, **overrides):
    p = {**params, **overrides}
    with boa.env.prank(sender):
        return factory.deploy_pool(
            "Curve.fi USD<>WETH",
            "USD<>WETH",
            [coin.address for coin in coins],
            0,
            p["A"],
            p["gamma"],
            p["mid_fee"],
            p["out_fee"],
            p["fee_gamma"],
            p["adjustment_step_min"],  # legacy name: allowed_extra_profit
            p["adjustment_step_max"],  # legacy name: adjustment_step
            p["ma_time"],  # legacy name: ma_exp_time
            p["initial_prices"][1],
        )


@pytest.fixture(scope="module")
def legacy_pool(legacy_factory, params, coins, deployer):
    return POOL_DEPLOYER.at(_legacy_deploy_pool(legacy_factory, params, coins, deployer))


def test_deploys_v3_pool(
    legacy_pool, legacy_factory, params, coins, math_contract, views_contract, owner, fee_receiver
):
    pool = legacy_pool
    assert pool.version() == "v3.1.0"
    assert pool.factory() == legacy_factory.address
    assert pool.MATH() == math_contract.address
    assert pool.VIEW() == views_contract.address
    assert pool.admin() == owner
    assert pool.fee_receiver() == fee_receiver
    assert pool.A() == params["A"]
    assert pool.gamma() == params["gamma"]
    assert list(pool.adjustment_step()) == [
        params["adjustment_step_min"],
        params["adjustment_step_max"],
    ]
    assert pool.price_scale() == params["initial_prices"][1]

    assert legacy_factory.find_pool_for_coins(coins[0].address, coins[1].address) == pool.address
    assert list(legacy_factory.get_coins(pool.address)) == [coin.address for coin in coins]
    # never set: the new pool does not read the factory's view pointer
    assert legacy_factory.views_implementation() == ZERO_ADDRESS


def test_pool_trades_and_quotes(legacy_pool, legacy_factory):
    pool = legacy_pool
    gm_pool = GodModePool(pool)
    amounts = gm_pool.compute_balanced_amounts(10**24)
    assert pool.calc_token_amount(amounts, True) == gm_pool.add_liquidity(amounts)

    dx = 10**21
    quote = pool.get_dy(0, 1, dx)
    assert gm_pool.exchange(0, dx) == quote

    lp = pool.balanceOf(boa.env.eoa) // 10
    quote = pool.calc_withdraw_one_coin(lp, 0)
    assert pool.remove_liquidity_one_coin(lp, 0, 0) == quote

    assert list(legacy_factory.get_balances(pool.address)) == [pool.balances(0), pool.balances(1)]


def test_typical_legacy_values_deploy(legacy_factory, params, coins, deployer):
    # the usual legacy preset: allowed_extra_profit 2e12, adjustment_step 1.46e14
    pool = POOL_DEPLOYER.at(
        _legacy_deploy_pool(
            legacy_factory,
            params,
            coins,
            deployer,
            adjustment_step_min=2 * 10**12,
            adjustment_step_max=146 * 10**12,
        )
    )
    assert list(pool.adjustment_step()) == [2 * 10**12, 146 * 10**12]


def test_min_step_above_max_step_rejected(legacy_factory, params, coins, deployer):
    with boa.reverts():
        _legacy_deploy_pool(
            legacy_factory,
            params,
            coins,
            deployer,
            adjustment_step_min=10**16,
            adjustment_step_max=10**15,
        )


def test_requires_math_pointer(
    legacy_factory_deployer, deployer, fee_receiver, owner, amm_implementation, params, coins
):
    factory = _new_legacy_factory(legacy_factory_deployer, deployer, fee_receiver, owner)
    with boa.env.prank(owner):
        factory.set_pool_implementation(amm_implementation.address, 0)

    with boa.reverts("Math implementation not set"):
        _legacy_deploy_pool(factory, params, coins, deployer)
