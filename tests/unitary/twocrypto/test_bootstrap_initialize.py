import copy

import boa

from tests.utils.constants import FEE_PRECISION, POLICY_DEPLOYER, POOL_DEPLOYER
from tests.utils.god_mode import GodModePool

PRECISION = 10**18
INITIAL_LIQUIDITY = 1000 * PRECISION
ZERO_ADDRESS = boa.eval("empty(address)")


def _deploy_bootstrap_pool(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract
):
    bootstrap_params = copy.deepcopy(params)
    bootstrap_params["gamma"] = 11111111111

    with boa.env.prank(deployer):
        pool_address = factory.deploy_pool(
            "Curve.fi USD<>WETH",
            "USD<>WETH",
            [coin.address for coin in coins],
            0,
            bootstrap_params["A"],
            bootstrap_params["gamma"],
            bootstrap_params["mid_fee"],
            bootstrap_params["out_fee"],
            bootstrap_params["fee_gamma"],
            bootstrap_params["adjustment_step_min"],
            bootstrap_params["adjustment_step_max"],
            bootstrap_params["ma_time"],
            bootstrap_params["initial_prices"][1],
        )

    return POOL_DEPLOYER.at(pool_address)


def _premint_and_add(pool, coins, account):
    amounts = [INITIAL_LIQUIDITY, INITIAL_LIQUIDITY * PRECISION // pool.price_scale()]
    for coin, amount in zip(coins, amounts):
        boa.deal(coin, account, amount)
        coin.approve(pool, amount, sender=account)

    return pool.add_liquidity(amounts, 0, account, False, sender=account)


def test_bootstrap_pool_reverts_first_add_before_initialize(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, alice
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )

    with boa.reverts("!init"):
        _premint_and_add(pool, coins, alice)


def test_deployer_can_initialize_and_seed_allowlist_with_policy(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, alice, bob
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )
    with boa.env.prank(deployer):
        policy = POLICY_DEPLOYER.deploy(pool.address)

    pool.initialize(
        FEE_PRECISION // 4,
        123,
        policy.address,
        [alice],
        sender=deployer,
    )

    logs = pool.get_logs()
    assert [type(log).__name__ for log in logs[-2:]] == [
        "LPAllowlistChanged",
        "LPAllowlistChanged",
    ]
    assert logs[-2].user.lower() == alice.lower()
    assert logs[-2].allowed is True
    assert logs[-1].user.lower() == ZERO_ADDRESS.lower()
    assert logs[-1].allowed is True

    assert pool.admin_fee() == 123
    assert pool.lp_profit_fraction() == FEE_PRECISION // 4
    assert pool.POLICY() == policy.address
    assert policy.get_price_scale() == 0

    with boa.reverts("!wl"):
        _premint_and_add(pool, coins, bob)

    minted = _premint_and_add(pool, coins, alice)
    assert minted > 0
    assert policy.get_price_scale() == 0

    gm_pool = GodModePool(pool)
    dy = gm_pool.exchange(0, 10**18)
    assert dy > 0
    assert pool.price_scale() > 0
    assert policy.get_price_scale() > 0

    with boa.reverts(dev='"pool does not need initialization"'):
        pool.initialize(FEE_PRECISION // 4, 123, policy.address, [alice], sender=deployer)


def test_non_deployer_cannot_initialize_during_window(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, bob
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )

    with boa.reverts(dev='"only deployer during initialization window"'):
        pool.initialize(0, 0, ZERO_ADDRESS, [], sender=bob)


def test_admin_can_initialize_after_window_and_leave_whitelist_disabled(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, bob
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )

    boa.env.time_travel(seconds=4 * 3600 + 1)

    pool.initialize(
        FEE_PRECISION // 3,
        321,
        ZERO_ADDRESS,
        [],
        sender=factory_admin,
    )

    logs = pool.get_logs()
    assert type(logs[-1]).__name__ == "LPAllowlistChanged"
    assert logs[-1].user.lower() == ZERO_ADDRESS.lower()
    assert logs[-1].allowed is False

    assert pool.admin_fee() == 321
    assert pool.lp_profit_fraction() == FEE_PRECISION // 3
    assert pool.POLICY() == ZERO_ADDRESS

    minted = _premint_and_add(pool, coins, bob)
    assert minted > 0


def test_initialize_zero_address_allowlist_keeps_whitelist_disabled(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, bob
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )

    pool.initialize(
        FEE_PRECISION // 3,
        321,
        ZERO_ADDRESS,
        [ZERO_ADDRESS],
        sender=deployer,
    )

    logs = pool.get_logs()
    assert type(logs[-1]).__name__ == "LPAllowlistChanged"
    assert logs[-1].user.lower() == ZERO_ADDRESS.lower()
    assert logs[-1].allowed is False

    minted = _premint_and_add(pool, coins, bob)
    assert minted > 0
