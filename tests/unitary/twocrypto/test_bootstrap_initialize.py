import copy

import boa
import pytest

from tests.utils.constants import (
    FEE_PRECISION,
    MAX_GAMMA,
    MIN_GAMMA,
    POLICY_DEPLOYER,
    POOL_DEPLOYER,
)
from tests.utils.god_mode import GodModePool

PRECISION = 10**18
INITIAL_LIQUIDITY = 1000 * PRECISION
ZERO_ADDRESS = boa.eval("empty(address)")
MAGIC_GAMMA = 11111111111


def _initial_price(params):
    return params["initial_prices"][1]


def _deploy_bootstrap_pool(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract
):
    bootstrap_params = copy.deepcopy(params)
    bootstrap_params["gamma"] = MAGIC_GAMMA

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


def test_initialize_reverts_after_liquidity(pool, coins, params, alice):
    minted = _premint_and_add(pool, coins, alice)
    assert minted > 0

    with boa.reverts(dev='"pool does not need initialization"'):
        pool.initialize(
            0, 0, ZERO_ADDRESS, _initial_price(params), [], params["gamma"], sender=alice
        )


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
        _initial_price(params),
        [alice],
        params["gamma"],
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
    assert pool.reserved_profit_fraction() == FEE_PRECISION // 4
    assert pool.POLICY() == policy.address
    assert policy.get_price_scale() == 0

    with boa.reverts("!wl"):
        _premint_and_add(pool, coins, bob)

    minted = _premint_and_add(pool, coins, alice)
    assert minted > 0
    assert policy.get_price_scale() == _initial_price(params)

    gm_pool = GodModePool(pool)
    dy = gm_pool.exchange(0, 10**18)
    assert dy > 0
    assert pool.price_scale() > 0
    assert policy.get_price_scale() > 0

    with boa.reverts(dev='"pool does not need initialization"'):
        pool.initialize(
            FEE_PRECISION // 4,
            123,
            policy.address,
            _initial_price(params),
            [alice],
            params["gamma"],
            sender=deployer,
        )


def test_initialize_refreshes_price_before_first_liquidity(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, alice
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )
    stale_price = _initial_price(params)
    initialized_price = stale_price * 2

    assert pool.price_scale() == stale_price
    assert pool.price_oracle() == stale_price
    assert pool.last_prices() == stale_price

    pool.initialize(
        FEE_PRECISION // 4,
        123,
        ZERO_ADDRESS,
        initialized_price,
        [alice],
        params["gamma"],
        sender=deployer,
    )

    assert pool.price_scale() == initialized_price
    assert pool.price_oracle() == initialized_price
    assert pool.last_prices() == initialized_price

    minted = _premint_and_add(pool, coins, alice)
    assert minted > 0


def test_non_deployer_or_admin_cannot_initialize(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, bob
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )

    with boa.reverts(dev='"only deployer or admin"'):
        pool.initialize(0, 0, ZERO_ADDRESS, _initial_price(params), [], params["gamma"], sender=bob)


@pytest.mark.parametrize("coin_idx", [0, 1])
def test_initialize_reverts_when_policy_is_pool_coin(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, coin_idx
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )

    with boa.reverts(dev='"policy is coin"'):
        pool.initialize(
            FEE_PRECISION // 4,
            123,
            coins[coin_idx].address,
            _initial_price(params),
            [],
            params["gamma"],
            sender=deployer,
        )


def test_admin_can_initialize_and_leave_whitelist_disabled(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, bob
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )

    pool.initialize(
        FEE_PRECISION // 3,
        321,
        ZERO_ADDRESS,
        _initial_price(params),
        [],
        params["gamma"],
        sender=factory_admin,
    )

    logs = pool.get_logs()
    assert type(logs[-1]).__name__ == "LPAllowlistChanged"
    assert logs[-1].user.lower() == ZERO_ADDRESS.lower()
    assert logs[-1].allowed is False

    assert pool.admin_fee() == 321
    assert pool.reserved_profit_fraction() == FEE_PRECISION // 3
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
        _initial_price(params),
        [ZERO_ADDRESS],
        params["gamma"],
        sender=deployer,
    )

    logs = pool.get_logs()
    assert type(logs[-1]).__name__ == "LPAllowlistChanged"
    assert logs[-1].user.lower() == ZERO_ADDRESS.lower()
    assert logs[-1].allowed is False

    minted = _premint_and_add(pool, coins, bob)
    assert minted > 0


def test_initialize_replaces_magic_gamma_and_keeps_A(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, alice
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )
    assert pool.gamma() == MAGIC_GAMMA
    assert pool.A() == params["A"]

    pool.initialize(
        0, 0, ZERO_ADDRESS, _initial_price(params), [], params["gamma"], sender=deployer
    )

    assert pool.gamma() == params["gamma"]
    assert pool.A() == params["A"]
    assert pool.initial_A_gamma() == pool.future_A_gamma() == (params["A"] << 128) | params["gamma"]

    minted = _premint_and_add(pool, coins, alice)
    assert minted > 0
    assert GodModePool(pool).exchange(0, 10**18) > 0


@pytest.mark.parametrize(
    "gamma, reason",
    [(MIN_GAMMA - 1, "gamma below minimum"), (MAX_GAMMA + 1, "gamma above maximum")],
)
def test_initialize_rejects_gamma_out_of_bounds(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, gamma, reason
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )

    with boa.reverts(dev=f'"{reason}"'):
        pool.initialize(0, 0, ZERO_ADDRESS, _initial_price(params), [], gamma, sender=deployer)


def test_initialize_clears_ramp_stopped_on_empty_pool(
    factory, factory_admin, coins, params, deployer, views_contract, math_contract, alice
):
    pool = _deploy_bootstrap_pool(
        factory, factory_admin, coins, params, deployer, views_contract, math_contract
    )

    # stop_ramp_A_gamma works on an empty pool and sets future_A_gamma_time
    # after last_timestamp, which would make the first deposit value empty
    # reserves as if a ramp were pending.
    boa.env.time_travel(seconds=600)
    pool.stop_ramp_A_gamma(sender=factory_admin)
    assert pool.future_A_gamma_time() > pool.last_timestamp()

    pool.initialize(
        0, 0, ZERO_ADDRESS, _initial_price(params), [], params["gamma"], sender=deployer
    )

    assert pool.initial_A_gamma_time() == 0
    assert pool.future_A_gamma_time() == 0
    assert pool.gamma() == params["gamma"]

    minted = _premint_and_add(pool, coins, alice)
    assert minted > 0
