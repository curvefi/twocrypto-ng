import boa
import pytest

from tests.utils.constants import MAX_FEE, PRECISION, UNIX_DAY, VENOM_FLAG
from tests.utils.god_mode import GodModePool

POLICY_TARGET_NUM = 102
POLICY_TARGET_DEN = 100

TWO_PERCENT_POLICY_DEPLOYER = boa.loads_partial(
    f"""
# pragma version 0.4.3
# pragma optimize gas

N_COINS: constant(uint256) = 2
last_price_scale: public(uint256)


@external
@view
def get_fee(xp: uint256[N_COINS]) -> uint256:
    return 0


@external
@view
def get_price_scale() -> uint256:
    return self.last_price_scale * {POLICY_TARGET_NUM} // {POLICY_TARGET_DEN}


@external
def update_pool_state(
    xp: uint256[N_COINS],
    price_scale: uint256,
    price_oracle: uint256,
    last_prices: uint256,
    virtual_price: uint256,
    xcp_profit: uint256,
    D: uint256,
):
    self.last_price_scale = price_scale
""",
    compiler_args={"experimental_codegen": VENOM_FLAG},
)

INITIAL_LIQ = 100_000 * PRECISION
WORK_SWAPS = 10
WORK_RATIO = 3
REBALANCE_STEPS = 6
REBALANCE_RATIO_NUM = 3
REBALANCE_RATIO_DEN = 5


def _deploy_two_percent_policy(pool, factory_admin):
    policy = TWO_PERCENT_POLICY_DEPLOYER.deploy()
    pool.set_policy_contract(policy, sender=factory_admin)
    return policy


def _exchange_and_read_rebalance_state(pool_instance):
    pool_instance.exchange(
        0,
        pool_instance.balances(0) * REBALANCE_RATIO_NUM // REBALANCE_RATIO_DEN,
        update_ema=False,
    )
    return pool_instance.price_scale(), pool_instance.donation_shares()


def _set_probe_rebalancing_params(pool_instance, factory_admin):
    pool_instance.apply_new_parameters(
        MAX_FEE + 1,
        MAX_FEE + 1,
        PRECISION,
        0,
        PRECISION + 1,
        PRECISION + 1,
        sender=factory_admin,
    )


def _balance_pool(pool_instance, precision=0.0001):
    value_0 = pool_instance.balances(0)
    value_1 = pool_instance.balances(1) * pool_instance.price_scale() // PRECISION
    ratio = value_0 / value_1

    i = 0
    while abs(ratio - 1) > precision:
        i += 1
        larger_coin = 0 if ratio > 1 else 1
        smaller_coin = 1 - larger_coin
        trade_back_size = int(pool_instance.balances(smaller_coin) * (abs(ratio - 1) / 2))
        pool_instance.exchange(smaller_coin, trade_back_size, update_ema=False)
        value_0 = pool_instance.balances(0)
        value_1 = pool_instance.balances(1) * pool_instance.price_scale() // PRECISION
        ratio = value_0 / value_1
        if i > 100:
            raise AssertionError(f"failed to balance pool: {ratio}")


def _work_pool(pool_instance):
    trade_size = pool_instance.balances(0) * WORK_RATIO
    for _ in range(WORK_SWAPS):
        amount_out = pool_instance.exchange(0, trade_size, update_ema=False)
        pool_instance.exchange(1, int(amount_out), update_ema=False)


def _snapshot(pool_instance):
    return {
        "virtual_price": pool_instance.virtual_price(),
        "xcp_profit": pool_instance.xcp_profit(),
        "admin_balances": [pool_instance.admin_balances(i) for i in range(2)],
        "get_virtual_price": pool_instance.get_virtual_price(),
        "price_scale": pool_instance.price_scale(),
        "price_oracle": pool_instance.price_oracle(),
        "last_prices": pool_instance.last_prices(),
        "D": pool_instance.D(),
        "balances": pool_instance.balances(),
        "pool_token_balances": [
            pool_instance.coins[0].balanceOf(pool_instance.address),
            pool_instance.coins[1].balanceOf(pool_instance.address),
        ],
        "total_supply": pool_instance.totalSupply(),
    }


def _set_synthetic_high_state(pool_instance):
    scaled_balance_0 = pool_instance.balances(0) * 3
    scaled_balance_1 = pool_instance.balances(1) * 3
    boa.deal(pool_instance.coins[0], pool_instance.address, scaled_balance_0)
    boa.deal(pool_instance.coins[1], pool_instance.address, scaled_balance_1)

    pool_instance.eval("self.balances[0] = self.balances[0] * 3")
    pool_instance.eval("self.balances[1] = self.balances[1] * 3")
    pool_instance.eval("self.D = self.D * 3")
    pool_instance.eval("self.virtual_price = 3 * 10**18")
    pool_instance.eval("self.xcp_profit = 5 * 10**18")


def _run_rebalance_probe(pool_instance):
    _work_pool(pool_instance)
    _balance_pool(pool_instance)

    rebalance_count = 0
    price_scale_path = [pool_instance.price_scale()]

    for _ in range(REBALANCE_STEPS):
        boa.env.time_travel(seconds=7 * UNIX_DAY)
        price_scale_before = pool_instance.price_scale()
        amount_out = pool_instance.exchange(
            0,
            pool_instance.balances(0) * REBALANCE_RATIO_NUM // REBALANCE_RATIO_DEN,
            update_ema=False,
        )
        price_scale_after = pool_instance.price_scale()
        rebalance_count += int(price_scale_after != price_scale_before)
        price_scale_path.append(price_scale_after)

        boa.env.time_travel(seconds=7 * UNIX_DAY)
        price_scale_before = pool_instance.price_scale()
        pool_instance.exchange(
            1,
            int(amount_out * REBALANCE_RATIO_NUM // REBALANCE_RATIO_DEN),
            update_ema=False,
        )
        price_scale_after = pool_instance.price_scale()
        rebalance_count += int(price_scale_after != price_scale_before)
        price_scale_path.append(price_scale_after)

    return rebalance_count, price_scale_path


def _inject_threshold_probe(pool_instance):
    pool_instance.inject_function(
        """
@external
@view
def threshold_probe() -> uint256:
    threshold_base: uint256 = (
        10**18
        + (max(self.xcp_profit, 10**18) - 10**18) * self.lp_profit_fraction // 10**10
    )
    threshold_vp: uint256 = threshold_base
    if threshold_base > 10**18:
        threshold_vp = unsafe_sub(
            threshold_base,
            min(self.admin_claimed_profit, unsafe_sub(threshold_base, 10**18)),
        )
    return threshold_vp
"""
    )


def test_synthetic_vp_xcp_state_is_coherent(pool, factory_admin):
    with boa.env.anchor():
        boa.env.enable_fast_mode()
        pool_instance = GodModePool(pool)
        pool_instance.add_liquidity_balanced(INITIAL_LIQ)
        _set_probe_rebalancing_params(pool_instance, factory_admin)

        fresh_state = _snapshot(pool_instance)
        _set_synthetic_high_state(pool_instance)
        synthetic_state = _snapshot(pool_instance)

        assert fresh_state["price_scale"] == synthetic_state["price_scale"]
        assert fresh_state["price_oracle"] == synthetic_state["price_oracle"]
        assert fresh_state["last_prices"] == synthetic_state["last_prices"]
        assert fresh_state["total_supply"] == synthetic_state["total_supply"]

        assert synthetic_state["virtual_price"] == 3 * PRECISION
        assert synthetic_state["xcp_profit"] == 5 * PRECISION
        assert synthetic_state["get_virtual_price"] == 3 * PRECISION
        assert synthetic_state["D"] == 3 * fresh_state["D"]
        assert synthetic_state["balances"] == [3 * balance for balance in fresh_state["balances"]]
        assert synthetic_state["balances"] == synthetic_state["pool_token_balances"]


def test_rebalance_count_matches_fresh_vs_synthetic_high_state(pool, factory_admin):
    with boa.env.anchor():
        boa.env.enable_fast_mode()
        fresh_pool = GodModePool(pool)
        fresh_pool.add_liquidity_balanced(INITIAL_LIQ)
        _set_probe_rebalancing_params(fresh_pool, factory_admin)

        fresh_pre = _snapshot(fresh_pool)
        fresh_count, fresh_price_scale_path = _run_rebalance_probe(fresh_pool)
        fresh_post = _snapshot(fresh_pool)

    with boa.env.anchor():
        boa.env.enable_fast_mode()
        synthetic_pool = GodModePool(pool)
        synthetic_pool.add_liquidity_balanced(INITIAL_LIQ)
        _set_probe_rebalancing_params(synthetic_pool, factory_admin)
        _set_synthetic_high_state(synthetic_pool)

        synthetic_pre = _snapshot(synthetic_pool)
        synthetic_count, synthetic_price_scale_path = _run_rebalance_probe(synthetic_pool)
        synthetic_post = _snapshot(synthetic_pool)

    assert fresh_pre["virtual_price"] == PRECISION
    assert fresh_pre["xcp_profit"] == PRECISION
    assert synthetic_pre["virtual_price"] == 3 * PRECISION
    assert synthetic_pre["xcp_profit"] == 5 * PRECISION

    assert (
        fresh_count > 0
    ), f"fresh pool never rebalanced: fresh_price_scale_path={fresh_price_scale_path}"
    assert (
        synthetic_count > 0
    ), f"synthetic pool never rebalanced: synthetic_price_scale_path={synthetic_price_scale_path}"

    assert fresh_count == synthetic_count, (
        "rebalance counts diverged\n"
        f"fresh_pre={fresh_pre}\n"
        f"synthetic_pre={synthetic_pre}\n"
        f"fresh_price_scale_path={fresh_price_scale_path}\n"
        f"synthetic_price_scale_path={synthetic_price_scale_path}\n"
        f"fresh_post={fresh_post}\n"
        f"synthetic_post={synthetic_post}"
    )


def test_price_scale_rebalances_only_on_first_touch_in_block(pool, factory_admin):
    with boa.env.anchor():
        boa.env.enable_fast_mode()
        pool_instance = GodModePool(pool)
        policy = _deploy_two_percent_policy(pool, factory_admin)
        pool_instance.add_liquidity_balanced(INITIAL_LIQ)
        _set_probe_rebalancing_params(pool_instance, factory_admin)
        pool_instance.donate_balanced(INITIAL_LIQ // 20)
        boa.env.time_travel(seconds=pool_instance.donation_duration())
        pool_instance.eval("self.donation_protection_expiry_ts = 0")
        boa.env.time_travel(seconds=1)

        price_scale_before = pool_instance.price_scale()
        donation_shares_before = pool_instance.donation_shares()
        assert policy.last_price_scale() == price_scale_before

        (
            price_scale_after_first_touch,
            donation_shares_after_first_touch,
        ) = _exchange_and_read_rebalance_state(pool_instance)
        assert price_scale_after_first_touch != price_scale_before
        assert donation_shares_after_first_touch < donation_shares_before

        (
            price_scale_after_same_block,
            donation_shares_after_same_block,
        ) = _exchange_and_read_rebalance_state(pool_instance)
        assert price_scale_after_same_block == price_scale_after_first_touch
        assert donation_shares_after_same_block == donation_shares_after_first_touch

        boa.env.time_travel(seconds=1)
        (
            price_scale_after_next_block,
            donation_shares_after_next_block,
        ) = _exchange_and_read_rebalance_state(pool_instance)

        assert price_scale_after_next_block != price_scale_after_same_block
        assert donation_shares_after_next_block < donation_shares_after_same_block


def test_admin_claimed_profit_offsets_threshold_vp_with_floor(pool):
    pytest.skip("admin_claimed_profit was removed in token-denominated admin fee accounting")
    with boa.env.anchor():
        pool_instance = GodModePool(pool)
        pool_instance.add_liquidity_balanced(INITIAL_LIQ)
        _inject_threshold_probe(pool_instance)

        pool_instance.eval("self.xcp_profit = 3 * 10**18")
        pool_instance.eval("self.admin_claimed_profit = 0")
        assert pool_instance.instance.inject.threshold_probe() == 2 * PRECISION

        pool_instance.eval("self.admin_claimed_profit = 3 * 10**17")
        assert pool_instance.instance.inject.threshold_probe() == 17 * PRECISION // 10

        pool_instance.eval("self.admin_claimed_profit = 5 * 10**18")
        assert pool_instance.instance.inject.threshold_probe() == PRECISION
