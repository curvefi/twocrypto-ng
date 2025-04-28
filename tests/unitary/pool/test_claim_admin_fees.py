import boa
import pytest

boa.env.evm.patch.code_size_limit = 56_000
# TRADE_SIZE = 3 # times pool liq
TRADE_SIZE = 1_000_000 * 10**18
N_TRADES = 10


def coin0_values(pool, address):
    return [
        pool.coins[0].balanceOf(address),
        pool.coins[1].balanceOf(address) * pool.price_scale() // 10**18,
    ]


def balance_pool(pool_instance, precision=0.0001, update_ema=False):
    # pool can be balanced nicely with get_y to get precise swap amounts, but this crude method works too
    val_rate = (
        pool_instance.balances(0)
        * 10**18
        / (pool_instance.price_oracle() * pool_instance.balances(1))
    )

    i = 0
    while abs(val_rate - 1) > precision:
        i += 1
        larger_coin = 0 if val_rate > 1 else 1
        smaller_coin = 1 - larger_coin
        trade_back_size = int(pool_instance.balances(smaller_coin) * (abs(val_rate - 1) / 2))
        _ = pool_instance.exchange(smaller_coin, trade_back_size, update_ema=update_ema)
        val_rate = (
            pool_instance.balances(0)
            * 10**18
            / (pool_instance.price_oracle() * pool_instance.balances(1))
        )
        if i > 100:
            print(f"failed to balance pool: {val_rate}")
            break
    return val_rate


def work_pool(pool_instance, n_swaps, trade_size, update_ema=False):
    # performs trades to raise xcp_profit and virtual price
    for i in range(n_swaps):
        amt_out = pool_instance.exchange(0, trade_size, update_ema=update_ema)
        _ = pool_instance.exchange(1, amt_out, update_ema=update_ema)


def test_claim_no_rebalancing(gm_pool, fee_receiver):
    gm_pool.add_liquidity_balanced(1_500_000 * 10**18)
    pool_instance = gm_pool
    boa.env.enable_fast_mode()
    # initially balances of admin must be zero

    assert pool_instance.xcp_profit() == 10**18
    assert pool_instance.virtual_price() == 10**18

    assert pool_instance.coins[0].balanceOf(fee_receiver) == 0
    assert pool_instance.coins[1].balanceOf(fee_receiver) == 0

    pool_values_init = coin0_values(pool_instance, pool_instance.address)

    # now we washtrade the pool to raise xcp_profit and virtual price
    # not updating the ema to avoid rebalancing, just fee collection
    work_pool(pool_instance, N_TRADES, TRADE_SIZE, update_ema=False)
    # for value tracking to make sense, we wash the pool back to perfect balance
    balance_pool(pool_instance)

    pool_values_post = coin0_values(pool_instance, pool_instance.address)

    pool_values_change = [pool_values_post[i] - pool_values_init[i] for i in [0, 1]]
    pool_value_surplus = sum(pool_values_change)

    # pool value must increase (we washtraded fees)
    assert pool_value_surplus > 0

    estimated_profit_admin_lp = pool_value_surplus // 2  # half to rebalance, half to admin-lp
    estimated_profit_admin = estimated_profit_admin_lp * pool_instance.admin_fee() // 10**10

    # admin has 0 balance before claiming
    receiver_values_init = coin0_values(pool_instance, fee_receiver)
    assert sum(receiver_values_init) == 0

    # claim admin fees
    pool_instance.internal._claim_admin_fees()
    receiver_values_post = coin0_values(pool_instance, fee_receiver)

    value_received = sum(receiver_values_post) - sum(receiver_values_init)
    # approx because add_liq doesn't earn for xcp_profit
    assert value_received == pytest.approx(estimated_profit_admin, rel=1e-8)


def test_n_claim_no_rebalancing(gm_pool, fee_receiver):
    gm_pool.add_liquidity_balanced(1_500_000 * 10**18)
    pool_instance = gm_pool

    N_REP = 20
    boa.env.enable_fast_mode()

    assert pool_instance.xcp_profit() == 10**18
    assert pool_instance.virtual_price() == 10**18

    assert pool_instance.coins[0].balanceOf(fee_receiver) == 0
    assert pool_instance.coins[1].balanceOf(fee_receiver) == 0

    for _ in range(N_REP):
        boa.env.time_travel(seconds=86_400)  # so that we can claim repeatedly

        pool_values_init = coin0_values(pool_instance, pool_instance.address)
        P_init = pool_instance.xcp_profit()

        work_pool(pool_instance, N_TRADES, TRADE_SIZE, update_ema=False)
        balance_pool(pool_instance)

        pool_values_post = coin0_values(pool_instance, pool_instance.address)
        P_post = pool_instance.xcp_profit()
        VP_post = pool_instance.virtual_price()
        # fees_admin_lp = int(np.sqrt(P_post * 1e18) - np.sqrt(P_init * 1e18))
        fees_admin_lp = (P_post - P_init) // 2
        fees_admin = fees_admin_lp * pool_instance.admin_fee() // 10**10
        estimated_profit_admin_vp_rated = fees_admin * sum(pool_values_post) // VP_post
        estimated_profit_admin_absolute = (
            (sum(pool_values_post) - sum(pool_values_init))
            * pool_instance.admin_fee()
            // 10**10
            // 2
        )
        # vp-defined rate and absolute values must match
        assert estimated_profit_admin_vp_rated == pytest.approx(
            estimated_profit_admin_absolute, rel=1e-8
        )
        estimated_profit_admin = estimated_profit_admin_absolute
        pool_value_surplus = sum(pool_values_post) - sum(pool_values_init)
        assert pool_value_surplus > 0

        receiver_values_init = coin0_values(pool_instance, fee_receiver)
        pool_instance.internal._claim_admin_fees()
        receiver_values_post = coin0_values(pool_instance, fee_receiver)

        value_received = sum(receiver_values_post) - sum(receiver_values_init)

        assert value_received == pytest.approx(estimated_profit_admin, rel=1e-8)


def test_n_claim_lp_no_rebalancing(gm_pool, fee_receiver):
    N_REP = 10
    boa.env.enable_fast_mode()
    pool_instance = gm_pool

    # dead lp user not to reset the pool at any time
    dead_lp_user = boa.env.generate_address()
    boa.env.set_balance(dead_lp_user, 10**20)
    for c in pool_instance.coins:
        c.approve(pool_instance, 2**256 - 1, sender=dead_lp_user)
    AMT_DEAD_LP = 500_000 * 10**18
    boa.deal(pool_instance.coins[0], dead_lp_user, AMT_DEAD_LP)
    boa.deal(
        pool_instance.coins[1], dead_lp_user, AMT_DEAD_LP * 10**18 // pool_instance.price_scale()
    )
    pool_instance.instance.add_liquidity(
        [
            pool_instance.coins[0].balanceOf(dead_lp_user),
            pool_instance.coins[1].balanceOf(dead_lp_user),
        ],
        0,
        sender=dead_lp_user,
    )

    # Setup LP user
    lp_user = boa.env.generate_address()
    boa.env.set_balance(lp_user, 10**20)
    for c in pool_instance.coins:
        c.approve(pool_instance, 2**256 - 1, sender=lp_user)

    AMT_LP = 1_500_000 * 10**18
    amounts_to_add = [AMT_LP, AMT_LP * 10**18 // pool_instance.price_scale()]
    boa.deal(pool_instance.coins[0], lp_user, amounts_to_add[0])
    boa.deal(pool_instance.coins[1], lp_user, amounts_to_add[1])

    for i in range(N_REP):
        # print(f"\niteration {i}")
        boa.env.time_travel(seconds=86_400)  # so that we can claim repeatedly
        # Record initial values
        pool_value_init = sum(coin0_values(pool_instance, pool_instance.address))
        lp_user_value_init = sum(coin0_values(pool_instance, lp_user))

        # Add all available liquidity from lp_user
        pool_instance.instance.add_liquidity(
            [pool_instance.coins[0].balanceOf(lp_user), pool_instance.coins[1].balanceOf(lp_user)],
            0,
            sender=lp_user,
        )
        pool_value_with_lp = sum(coin0_values(pool_instance, pool_instance.address))
        # print(f"pool_values_with_lp: {pool_value_with_lp}")
        lp_user_balance_rate = (pool_value_with_lp - pool_value_init) / pool_value_with_lp
        # print(f"lp_user_balance_rate: {lp_user_balance_rate}")

        # Work the pool and balance
        work_pool(pool_instance, N_TRADES, TRADE_SIZE, update_ema=False)
        balance_pool(pool_instance)

        pool_value_post = sum(coin0_values(pool_instance, pool_instance.address))
        pool_value_surplus = pool_value_post - pool_value_with_lp
        # print(f"pool_value_surplus: {pool_value_surplus}")
        assert pool_value_surplus > 0

        receiver_value_init = sum(coin0_values(pool_instance, fee_receiver))
        pool_instance.internal._claim_admin_fees()
        receiver_value_post = sum(coin0_values(pool_instance, fee_receiver))
        value_received_admin = receiver_value_post - receiver_value_init
        # print(f"value_received_admin: {value_received_admin}")

        # Remove all LP from lp_user
        pool_instance.instance.remove_liquidity(
            pool_instance.balanceOf(lp_user), [0, 0], sender=lp_user
        )
        lp_user_value_post = sum(coin0_values(pool_instance, lp_user))
        value_received_lp_user = lp_user_value_post - lp_user_value_init
        # print(f"lp_user_value_change: {value_received_lp_user}")
        # print(f"rate_received_admin: {value_received_admin / pool_value_surplus}")
        # print(f"rate_received_lp: {value_received_lp_user / pool_value_surplus}")
        # print(f"rate_received_lp_rate_adjusted: {value_received_lp_user / (pool_value_surplus * lp_user_balance_rate)}")
        # print(f"virtual_price: {pool_instance.virtual_price()/1e18}")

        # admin always gets quarter of profits
        expected_value_received_admin = (
            pool_value_surplus * pool_instance.admin_fee() // 10**10 // 2
        )
        assert value_received_admin == pytest.approx(expected_value_received_admin, rel=0.01)

        profit_after_admin = pool_value_surplus - value_received_admin
        # LPs get rest of profits that are unburned by rebalance
        expected_value_received_lp_user = profit_after_admin * lp_user_balance_rate
        assert value_received_lp_user == pytest.approx(expected_value_received_lp_user, rel=0.01)

        # at least half of all profits go to our lp user (rate-adjusted)
        assert value_received_lp_user > pool_value_surplus // 2 * lp_user_balance_rate


def test_n_claim_lp_rebalancing(gm_pool, fee_receiver):
    """
    Concise version of test_n_claim_lp_no_rebalancing using GodModePool features.
    """
    N_REP = 10
    boa.env.enable_fast_mode()
    pool_instance = gm_pool

    # dead lp user not to reset the pool at any time
    dead_lp_user = boa.env.generate_address()
    boa.env.set_balance(dead_lp_user, 10**20)
    for c in pool_instance.coins:
        c.approve(pool_instance, 2**256 - 1, sender=dead_lp_user)
    AMT_DEAD_LP = 1 * 10**18
    boa.deal(pool_instance.coins[0], dead_lp_user, AMT_DEAD_LP)
    boa.deal(
        pool_instance.coins[1], dead_lp_user, AMT_DEAD_LP * 10**18 // pool_instance.price_scale()
    )
    pool_instance.instance.add_liquidity(
        [
            pool_instance.coins[0].balanceOf(dead_lp_user),
            pool_instance.coins[1].balanceOf(dead_lp_user),
        ],
        0,
        sender=dead_lp_user,
    )

    # Setup LP user
    lp_user = boa.env.generate_address()
    boa.env.set_balance(lp_user, 10**20)
    for c in pool_instance.coins:
        c.approve(pool_instance, 2**256 - 1, sender=lp_user)

    AMT_LP = 1_500_000 * 10**18
    amounts_to_add = [AMT_LP, AMT_LP * 10**18 // pool_instance.price_scale()]
    boa.deal(pool_instance.coins[0], lp_user, amounts_to_add[0])
    boa.deal(pool_instance.coins[1], lp_user, amounts_to_add[1])

    for i in range(N_REP):
        print(f"\niteration {i}")
        boa.env.time_travel(seconds=86_400)  # so that we can claim repeatedly
        # Record initial values
        pool_value_init = sum(coin0_values(pool_instance, pool_instance.address))
        lp_user_value_init = sum(coin0_values(pool_instance, lp_user))

        # Add all available liquidity from lp_user
        pool_instance.instance.add_liquidity(
            [pool_instance.coins[0].balanceOf(lp_user), pool_instance.coins[1].balanceOf(lp_user)],
            0,
            sender=lp_user,
        )
        pool_value_with_lp = sum(coin0_values(pool_instance, pool_instance.address))
        print(f"pool_values_with_lp: {pool_value_with_lp}")
        lp_user_balance_rate = (pool_value_with_lp - pool_value_init) / pool_value_with_lp
        print(f"lp_user_balance_rate: {lp_user_balance_rate}")

        vp_pre_work = pool_instance.virtual_price()
        ps_pre_work = pool_instance.price_scale()
        # Work the pool and balance
        work_pool(pool_instance, N_TRADES, TRADE_SIZE, update_ema=True)
        balance_pool(pool_instance, update_ema=True)
        vp_post_work = pool_instance.virtual_price()
        ps_post_work = pool_instance.price_scale()
        print(f"vp_pre_work: {vp_pre_work/1e18}, vp_post_work: {vp_post_work/1e18}")
        print(f"ps_pre_work: {ps_pre_work/1e18}, ps_post_work: {ps_post_work/1e18}")
        print(
            f"xcp_profit: {pool_instance.xcp_profit()/1e18}, xcp_profit_a: {pool_instance.xcp_profit_a()/1e18}"
        )
        print(
            f"xcp_profit_a_diff: {(pool_instance.xcp_profit() - pool_instance.xcp_profit_a())/1e18}"
        )
        pool_value_post = sum(coin0_values(pool_instance, pool_instance.address))
        pool_value_surplus = pool_value_post - pool_value_with_lp
        print(f"pool_value_surplus: {pool_value_surplus}")
        assert pool_value_surplus > 0

        receiver_value_init = sum(coin0_values(pool_instance, fee_receiver))
        pool_instance.internal._claim_admin_fees()
        receiver_value_post = sum(coin0_values(pool_instance, fee_receiver))
        value_received_admin = receiver_value_post - receiver_value_init
        print(f"value_received_admin: {value_received_admin}")

        # Remove all LP from lp_user
        pool_instance.instance.remove_liquidity(
            pool_instance.balanceOf(lp_user), [0, 0], sender=lp_user
        )
        lp_user_value_post = sum(coin0_values(pool_instance, lp_user))
        value_received_lp_user = lp_user_value_post - lp_user_value_init
        print(f"lp_user_value_change: {value_received_lp_user}")
        print(f"rate_received_admin: {value_received_admin / pool_value_surplus}")
        print(f"rate_received_lp: {value_received_lp_user / pool_value_surplus}")
        print(
            f"rate_received_lp_rate_adjusted: {value_received_lp_user / (pool_value_surplus * lp_user_balance_rate)}"
        )
        print(f"virtual_price: {pool_instance.virtual_price()/1e18}")

        # admin always gets quarter of profits
        # expected_value_received_admin = (
        #     pool_value_surplus * pool_instance.admin_fee() // 10**10 // 2
        # )
        # assert value_received_admin == pytest.approx(expected_value_received_admin, rel=0.01)

        # profit_after_admin = pool_value_surplus - value_received_admin
        # LPs get rest of profits that are unburned by rebalance
        # expected_value_received_lp_user = profit_after_admin * lp_user_balance_rate
        # assert value_received_lp_user == pytest.approx(expected_value_received_lp_user, rel=0.01)

        # at least half of all profits go to our lp user (rate-adjusted)
        # assert value_received_lp_user > pool_value_surplus // 2 * lp_user_balance_rate


# def test_n_claim_lp_with_rebalancing(pool_instance, fee_receiver):
#     N_REP = 10
#     boa.env.enable_fast_mode()

#     # Setup LP user
#     lp_user = boa.env.generate_address()
#     boa.env.set_balance(lp_user, 10**20)
#     for c in pool_instance.coins:
#         c.approve(pool_instance, 2**256 - 1, sender=lp_user)

#     AMT_LP = 1_500_000 * 10**18
#     amounts_to_add = [AMT_LP, AMT_LP * 10**18 // pool_instance.price_scale()]
#     boa.deal(pool_instance.coins[0], lp_user, amounts_to_add[0])
#     boa.deal(pool_instance.coins[1], lp_user, amounts_to_add[1])
#     pool_total_earnings = 0
#     lp_total_earnings = 0
#     admin_total_earnings = 0
#     for i in range(N_REP):
#         print(f"iteration {i}")
#         # Record initial values
#         pool_value_init = pool_instance.balances(0) + pool_instance.balances(1) * pool_instance.price_scale() // 10**18
#         receiver_value_init = sum([
#             pool_instance.coins[0].balanceOf(fee_receiver),
#             pool_instance.coins[1].balanceOf(fee_receiver) * pool_instance.price_scale() // 10**18
#         ])
#         lp_user_value_init = sum([
#             pool_instance.coins[0].balanceOf(lp_user),
#             pool_instance.coins[1].balanceOf(lp_user) * pool_instance.price_scale() // 10**18
#         ])

#         # Add all available liquidity from lp_user
#         pool_instance.instance.add_liquidity([
#             pool_instance.coins[0].balanceOf(lp_user),
#             pool_instance.coins[1].balanceOf(lp_user)
#         ], 0, sender=lp_user)
#         pool_value_with_lp = pool_instance.balances(0) + pool_instance.balances(1) * pool_instance.price_scale() // 10**18
#         lp_user_balance_rate = (pool_value_with_lp - pool_value_init) / pool_value_with_lp
#         print(f"lp_user_balance_rate: {lp_user_balance_rate}")
#         # Work the pool and balance, with rebalancing (update_ema=True)
#         vp_pre_work = pool_instance.virtual_price()
#         UPDATE_EMA = False
#         work_pool(pool_instance, N_TRADES, TRADE_SIZE, update_ema=UPDATE_EMA)
#         balance_pool(pool_instance, precision=1e-6, update_ema=UPDATE_EMA)
#         vp_post_work = pool_instance.virtual_price()

#         pool_value_post = pool_instance.balances(0) + pool_instance.balances(1) * pool_instance.price_scale() // 10**18
#         pool_value_surplus = pool_value_post - pool_value_with_lp
#         print(f"pool_value_surplus: {pool_value_surplus}, ({(pool_value_surplus/1e18):4.2f})")
#         assert pool_value_surplus > 0

#         pool_instance.internal._claim_admin_fees()
#         vp_post_claim = pool_instance.virtual_price()
#         receiver_value_post = sum([
#             pool_instance.coins[0].balanceOf(fee_receiver),
#             pool_instance.coins[1].balanceOf(fee_receiver) * pool_instance.price_scale() // 10**18
#         ])
#         value_received_admin = receiver_value_post - receiver_value_init
#         admin_total_earnings += value_received_admin
#         print(f"value_received_admin: {value_received_admin}, ({(value_received_admin/1e18):4.2f})")

#         # Remove all LP from lp_user
#         pool_instance.instance.remove_liquidity(pool_instance.balanceOf(lp_user), [0, 0], sender=lp_user)
#         lp_user_value_post = sum([
#             pool_instance.coins[0].balanceOf(lp_user),
#             pool_instance.coins[1].balanceOf(lp_user) * pool_instance.price_scale() // 10**18
#         ])
#         vp_post_lp_remove = pool_instance.virtual_price()
#         lp_user_value_change = lp_user_value_post - lp_user_value_init
#         lp_total_earnings += lp_user_value_change
#         pool_total_earnings += (pool_value_surplus - value_received_admin - lp_user_value_change)
#         print(f"lp_user_value_change: {lp_user_value_change}, ({(lp_user_value_change/1e18):4.2f})")
#         print(f"rate_received_admin: {value_received_admin / pool_value_surplus}")
#         print(f"rate_received_lp: {lp_user_value_change / pool_value_surplus}")
#         print(f"rate_received_lp_rate_adjusted: {lp_user_value_change / (pool_value_surplus * lp_user_balance_rate)}")
#         print(f"vp_pre_work: {vp_pre_work/1e18}, vp_post_work: {vp_post_work/1e18}, vp_post_claim: {vp_post_claim/1e18}, vp_post_lp_remove: {vp_post_lp_remove/1e18}")
#         print(f"vp_post_claim/vp_post_work: {vp_post_claim/vp_post_work}")
#         vp_dif_claim = vp_post_work - vp_post_claim
#         vp_dif_work = vp_post_work - vp_pre_work
#         print(f"vp_dif_claim: {vp_dif_claim/1e18}, vp_dif_work: {vp_dif_work/1e18}, rate_claim: {vp_dif_claim/vp_dif_work}")
#         print(f"pool_total_earnings: {pool_total_earnings/1e18}, lp_total_earnings: {lp_total_earnings/1e18}, admin_total_earnings: {admin_total_earnings/1e18}")

#         print("--------------------------------")
