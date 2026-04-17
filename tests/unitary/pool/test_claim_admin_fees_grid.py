import boa
import pytest

from tests.utils.constants import FEE_PRECISION
from tests.utils.god_mode import GodModePool

TRADE_SIZE = 1_000_000 * 10**18
N_TRADES = 10
INITIAL_LIQ = 1_500_000 * 10**18


def coin0_values(pool, address):
    return [
        pool.coins[0].balanceOf(address),
        pool.coins[1].balanceOf(address) * pool.price_scale() // 10**18,
    ]


def balance_pool(pool_instance, precision=0.0001):
    val_0 = pool_instance.balances(0)
    val_1 = pool_instance.balances(1) * pool_instance.price_scale() // 10**18
    ratio = val_0 / val_1

    i = 0
    while abs(ratio - 1) > precision:
        i += 1
        larger_coin = 0 if ratio > 1 else 1
        smaller_coin = 1 - larger_coin
        trade_back_size = int(pool_instance.balances(smaller_coin) * (abs(ratio - 1) / 2))
        pool_instance.exchange(smaller_coin, trade_back_size, update_ema=False)
        val_0 = pool_instance.balances(0)
        val_1 = pool_instance.balances(1) * pool_instance.price_scale() // 10**18
        ratio = val_0 / val_1
        if i > 100:
            raise AssertionError(f"failed to balance pool: {ratio}")


def work_pool(pool_instance, n_swaps, trade_size):
    for _ in range(n_swaps):
        amount_out = pool_instance.exchange(0, trade_size, update_ema=False)
        pool_instance.exchange(1, int(amount_out), update_ema=False)


# This is the first claim-fee test that exercises non-default lp_profit_fraction.
@pytest.mark.parametrize(
    "lp_profit_fraction", [FEE_PRECISION // 10, FEE_PRECISION // 2, 9 * FEE_PRECISION // 10]
)
@pytest.mark.parametrize(
    "admin_fee", [FEE_PRECISION // 10, FEE_PRECISION // 2, 9 * FEE_PRECISION // 10]
)
def test_claim_admin_fees_grid_no_rebalancing(
    pool, factory_admin, fee_receiver, lp_profit_fraction, admin_fee
):
    with boa.env.anchor():
        boa.env.enable_fast_mode()
        pool_instance = GodModePool(pool)
        pool_instance.set_fee_parameters(lp_profit_fraction, admin_fee, sender=factory_admin)
        pool_instance.add_liquidity_balanced(INITIAL_LIQ)

        work_pool(pool_instance, N_TRADES, TRADE_SIZE)
        balance_pool(pool_instance)

        xcp_profit_pre = pool_instance.xcp_profit()
        xcp_profit_a_pre = pool_instance.xcp_profit_a()
        admin_claimed_profit_pre = pool_instance.admin_claimed_profit()
        virtual_price_pre = pool_instance.virtual_price()
        D_pre = pool_instance.D()
        balances_pre = pool_instance.balances()
        receiver_balances_pre = [
            pool_instance.coins[0].balanceOf(fee_receiver),
            pool_instance.coins[1].balanceOf(fee_receiver),
        ]
        receiver_value_pre = sum(coin0_values(pool_instance, fee_receiver))

        accrued = xcp_profit_pre - xcp_profit_a_pre
        expected_fees = accrued * lp_profit_fraction * admin_fee // FEE_PRECISION // FEE_PRECISION
        expected_vp_post = virtual_price_pre - expected_fees
        expected_D_post = D_pre - D_pre * expected_fees // virtual_price_pre
        expected_admin_amounts = [
            balances_pre[i] * expected_fees // virtual_price_pre for i in range(2)
        ]

        pool_instance.internal._claim_admin_fees()

        receiver_balances_post = [
            pool_instance.coins[0].balanceOf(fee_receiver),
            pool_instance.coins[1].balanceOf(fee_receiver),
        ]
        actual_admin_amounts = [
            receiver_balances_post[i] - receiver_balances_pre[i] for i in range(2)
        ]
        assert actual_admin_amounts == expected_admin_amounts

        assert pool_instance.virtual_price() == expected_vp_post
        assert pool_instance.xcp_profit() == xcp_profit_pre
        assert pool_instance.xcp_profit_a() == xcp_profit_pre
        assert pool_instance.admin_claimed_profit() == admin_claimed_profit_pre + expected_fees
        assert pool_instance.D() == expected_D_post

        receiver_value_post = sum(coin0_values(pool_instance, fee_receiver))
        expected_claim_value = sum(
            [
                expected_admin_amounts[0],
                expected_admin_amounts[1] * pool_instance.price_scale() // 10**18,
            ]
        )
        assert receiver_value_post - receiver_value_pre == pytest.approx(
            expected_claim_value, rel=1e-8
        )
