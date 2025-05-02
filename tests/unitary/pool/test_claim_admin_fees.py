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


def snapshot_values(pool, actors):
    values = {}
    for actor in actors:
        values[actor] = sum(coin0_values(pool, actor))
    return values


def snapshot_balances(pool, actors):
    balances = {}
    for actor in actors:
        # actor_addy = actor.address if hasattr(actor, 'address') else actor
        actor_addy = actor
        bals = [pool.coins[0].balanceOf(actor_addy), pool.coins[1].balanceOf(actor_addy)]
        balances[actor_addy] = bals
    return balances


def get_pool_state(pool_instance, print_state=False, print_normalized=True):
    xcp_profit = pool_instance.xcp_profit()
    virtual_price = pool_instance.virtual_price()
    price_scale = pool_instance.price_scale()
    price_oracle = pool_instance.price_oracle()

    b_0 = pool_instance.balances(0)
    b_1 = pool_instance.balances(1)
    val_0 = b_0
    val_1 = b_1 * price_scale // 10**18
    spot_price = pool_instance.last_prices()
    # spot_price = b_0 * 10**18 // b_1
    ratio = val_0 / val_1
    if print_state:
        scale_print = 1e18 if print_normalized else 1
        print(
            f"xcp_profit: {(xcp_profit/scale_print):.{7}f}; "
            f"virtual_price: {(virtual_price/scale_print):.{7}f}; "
            f"price_scale: {(price_scale/scale_print):.{1}f}; "
            f"price_oracle: {(price_oracle/scale_print):.{1}f}; "
            f"spot_price: {(spot_price/scale_print):.{1}f}; "
            f"values: {val_0/scale_print:.{1}f}, {val_1/scale_print:.{1}f} (total: {val_0/scale_print + val_1/scale_print:.{1}f}, ratio: {ratio:.{2}f})."
        )
    return xcp_profit, virtual_price, price_scale, price_oracle, spot_price, ratio


def balance_pool(pool_instance, precision=0.0001, update_ema=False):
    # pool can be balanced nicely with get_y to get precise swap amounts, but this crude method works too
    _, _, _, _, _, ratio = get_pool_state(pool_instance, print_state=False)

    i = 0
    while abs(ratio - 1) > precision:
        i += 1
        larger_coin = 0 if ratio > 1 else 1
        smaller_coin = 1 - larger_coin
        trade_back_size = int(pool_instance.balances(smaller_coin) * (abs(ratio - 1) / 2))
        _ = pool_instance.exchange(smaller_coin, trade_back_size, update_ema=update_ema)
        _, _, _, _, _, ratio = get_pool_state(pool_instance, print_state=False)
        if i > 100:
            print(f"failed to balance pool: {ratio}")
            break
    return ratio


def work_pool(
    pool_instance, n_swaps, trade_size, update_ema=False, main_direction=0, xcp_growth=None
):
    # performs trades to raise xcp_profit and virtual price
    if xcp_growth is None:
        for i in range(n_swaps):
            # print(f'swapping {trade_size} {pool_instance.coins[main_direction].symbol()} for {pool_instance.coins[1 - main_direction].symbol()}')
            # print(pool_instance.price_oracle())
            amt_out = pool_instance.exchange(main_direction, trade_size, update_ema=update_ema)
            swap_back = amt_out
            _ = pool_instance.exchange(1 - main_direction, int(swap_back), update_ema=update_ema)
    else:
        xcp_start = pool_instance.xcp_profit()
        i = 0
        while (pool_instance.xcp_profit() - xcp_start) / 1e18 < xcp_growth:
            amt_out = pool_instance.exchange(main_direction, trade_size, update_ema=update_ema)
            swap_back = amt_out
            _ = pool_instance.exchange(1 - main_direction, int(swap_back), update_ema=update_ema)
            i += 1
            if i > 100:
                print(f"failed to work pool: {pool_instance.xcp_profit() - xcp_start}")
                break


def move_price_oracle(pool_instance, price_change, update_ema=True):
    # print('moving spot price...')
    # move_spot_price(pool_instance, price_change, update_ema=update_ema)
    # get_pool_state(pool_instance, print_state=True)
    # print('tweaking price oracle...')
    # work_pool(pool_instance, 10*N_TRADES, 10**18, update_ema=update_ema)
    # get_pool_state(pool_instance, print_state=True)

    current_price = pool_instance.price_oracle()
    # print(f"current_price: {current_price}")
    goal_price = current_price * (1 + price_change)
    # print(f"goal_price: {goal_price}")
    price_diff_pre = goal_price - current_price
    if price_diff_pre > 0:
        main_direction = 0
    else:
        main_direction = 1
    price_diff_post = price_diff_pre
    i = 0

    while price_diff_pre * price_diff_post > 0:  # check the sign of the price change
        trade_size = int(pool_instance.balances(main_direction) * abs(price_change)) // 2_0
        pool_instance.exchange(main_direction, trade_size, update_ema=update_ema)
        price_diff_pre = price_diff_post
        # print(f"price_oracle: {pool_instance.price_oracle()}")
        price_diff_post = goal_price - pool_instance.price_oracle()
        i += 1
        # print(f"price_diff_pre: {price_diff_pre}, price_diff_post: {price_diff_post}")

        if i > 100:
            print(f"failed to move price: {price_diff_post}")
            break
    print(f"price_oracle: {pool_instance.price_oracle()}")


def move_price_scale(pool_instance, price_change, verbose=True):
    move_price_oracle(pool_instance, price_change, update_ema=True)
    if verbose:
        get_pool_state(pool_instance, print_state=True)
        print("balancing the pool...")
    balance_pool(pool_instance, update_ema=False)
    if verbose:
        get_pool_state(pool_instance, print_state=True)
        print("tweaking the price...")
    work_pool(pool_instance, N_TRADES, 10**18, update_ema=False)
    if verbose:
        get_pool_state(pool_instance, print_state=True)
        print("balancing the pool...")
    balance_pool(pool_instance, update_ema=False)
    if verbose:
        get_pool_state(pool_instance, print_state=True)


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
        print(f"pool_values_with_lp: {pool_value_with_lp}")
        lp_user_balance_rate = (pool_value_with_lp - pool_value_init) / pool_value_with_lp
        print(f"lp_user_balance_rate: {lp_user_balance_rate}")

        xcpp_pre_work, vp_pre_work, ps_pre_work = (
            pool_instance.xcp_profit(),
            pool_instance.virtual_price(),
            pool_instance.price_scale(),
        )
        # Work the pool and balance
        work_pool(pool_instance, N_TRADES, TRADE_SIZE, update_ema=False)
        balance_pool(pool_instance, update_ema=False)
        vp_post_work, ps_post_work, xcpp_post_work = (
            pool_instance.virtual_price(),
            pool_instance.price_scale(),
            pool_instance.xcp_profit(),
        )
        print(f"vp_pre_work: {vp_pre_work/1e18}, vp_post_work: {vp_post_work/1e18}")
        print(f"ps_pre_work: {ps_pre_work/1e18}, ps_post_work: {ps_post_work/1e18}")
        print(f"xcpp_pre_work: {xcpp_pre_work/1e18}, xcpp_post_work: {xcpp_post_work/1e18}")
        print(f"xcpp_post_work - xcpp_pre_work: {(xcpp_post_work - xcpp_pre_work)/1e18}")

        pool_value_post = sum(coin0_values(pool_instance, pool_instance.address))
        pool_value_surplus = pool_value_post - pool_value_with_lp
        print(f"pool_value_surplus: {pool_value_surplus}")
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
    # This check is only valid when the pool finishes its “work loop”
    # with the same price_scale it started with.
    #
    # Test outline:
    #   1. Grow the pool (xcp_profit up).
    #   2. Force price_scale upward via swaps & rebalancing.
    #   3. Pull price_scale back to the starting level.
    #
    # Because the start- and end-price_scale match, any difference between
    # initial and final pool value reflects *pure profit*; nothing is hidden
    # in the peg-correction mechanics.
    #
    # Profit-sharing limits:
    #   • If no rebalancing was needed, admin receives 25 % of the profit.
    #   • If the full “half-growth” reserve was spent on rebalancing,
    #     admin receives 50 %.
    #   • If only part of reserve was spent on rebalancing, admin receives between 25 % and 50 %.
    #   • LPs get the rest of profits.

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

    AMT_LP = 1_000_000 * 10**18
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

        get_pool_state(pool_instance, print_state=True)
        # Work the pool and balance
        print("working the pool...")
        # we collect xcp_profit to have some rebalancing reserve
        xcp_growth = 0.2
        work_pool(pool_instance, N_TRADES, TRADE_SIZE, update_ema=False, xcp_growth=xcp_growth)
        get_pool_state(pool_instance, print_state=True)
        print("balancing the pool...")
        balance_pool(pool_instance, update_ema=False)
        get_pool_state(pool_instance, print_state=True)
        price_init = pool_instance.price_scale()
        # now we move price up and down and burn rebalance reserve
        price_change_1 = 0.3
        print(f"price_init: {price_init/1e18}, price_change_1: {price_change_1}")
        move_price_scale(pool_instance, price_change_1, verbose=True)
        get_pool_state(pool_instance, print_state=True)

        price_change_2 = price_init / pool_instance.price_scale() - 1
        print(f"price_change_2: {price_change_2}")
        move_price_scale(pool_instance, 0.95 * price_change_2, verbose=False)
        get_pool_state(pool_instance, print_state=True)

        print("claiming admin fees...")
        pool_value_post = sum(coin0_values(pool_instance, pool_instance.address))
        pool_value_surplus = pool_value_post - pool_value_with_lp
        print(f"pool_value_surplus: {pool_value_surplus}")

        # assert pool_value_surplus > 0

        receiver_value_init = sum(coin0_values(pool_instance, fee_receiver))
        pool_instance.internal._claim_admin_fees()
        get_pool_state(pool_instance, print_state=True)

        receiver_value_post = sum(coin0_values(pool_instance, fee_receiver))
        value_received_admin = receiver_value_post - receiver_value_init
        rate_received_admin = value_received_admin / pool_value_surplus
        print(f"value_received_admin: {value_received_admin}")
        xcpp_post_claim = pool_instance.xcp_profit()
        print(f"xcpp_post_claim: {xcpp_post_claim/1e18}")
        # Remove all LP from lp_user
        pool_instance.instance.remove_liquidity(
            pool_instance.balanceOf(lp_user), [0, 0], sender=lp_user
        )
        lp_user_value_post = sum(coin0_values(pool_instance, lp_user))
        value_received_lp_user = lp_user_value_post - lp_user_value_init
        rate_received_lp_user = value_received_lp_user / (pool_value_surplus * lp_user_balance_rate)
        print(f"lp_user_value_change: {value_received_lp_user}")
        print(f"rate_received_admin: {rate_received_admin}")
        print(f"rate_received_lp: {rate_received_lp_user}")
        print(f"rate_received_lp_rate_adjusted: {rate_received_lp_user}")
        print(f"virtual_price: {pool_instance.virtual_price()/1e18}")

        # admin should get at least 0.25 of profits (if no rebalances happened), and up to 0.5 (if all rebalance reserve is used)
        assert 0.25 < rate_received_admin < 0.5
        # LPs get half the profits (if all rebalance reserve is used), and more if rebalance reserve is not used
        assert 0.5 < rate_received_lp_user < 1


def test_lp_deposit_fee_balanced(gm_pool, fee_receiver):
    pool_instance = gm_pool
    pool_fee_params = pool_instance.packed_fee_params()
    mid_fee, out_fee, fee_gamma = pool_instance.internal._unpack_3(pool_fee_params)
    print(f"mid_fee: {mid_fee/1e10}, out_fee: {out_fee/1e10}, fee_gamma: {fee_gamma/1e10}")
    # Setup LP user
    lp_user = boa.env.generate_address()
    boa.env.set_balance(lp_user, 10**20)
    for c in pool_instance.coins:
        c.approve(pool_instance, 2**256 - 1, sender=lp_user)

    # instantiate pool with some liquidity so that main size brings fees
    dead_lp_user = boa.env.generate_address()
    boa.env.set_balance(dead_lp_user, 10**20)
    for c in pool_instance.coins:
        c.approve(pool_instance, 2**256 - 1, sender=dead_lp_user)
    AMT_DEAD_LP = 1 * 10**17
    amounts_dead_lp = [AMT_DEAD_LP, AMT_DEAD_LP * 10**18 // pool_instance.price_scale()]
    boa.deal(pool_instance.coins[0], dead_lp_user, amounts_dead_lp[0])
    boa.deal(pool_instance.coins[1], dead_lp_user, amounts_dead_lp[1])

    pool_instance.instance.add_liquidity(
        [
            pool_instance.coins[0].balanceOf(dead_lp_user),
            pool_instance.coins[1].balanceOf(dead_lp_user),
        ],
        0,
        sender=dead_lp_user,
    )

    AMT_LP = 1_000_000 * 10**18
    amounts_to_add = [AMT_LP, AMT_LP * 10**18 // pool_instance.price_scale()]
    boa.deal(pool_instance.coins[0], lp_user, amounts_to_add[0])
    boa.deal(pool_instance.coins[1], lp_user, amounts_to_add[1])

    values_pre_lp = snapshot_values(pool_instance, [pool_instance, fee_receiver, lp_user])
    pool_instance.instance.add_liquidity(
        [pool_instance.coins[0].balanceOf(lp_user), pool_instance.coins[1].balanceOf(lp_user)],
        0,
        sender=lp_user,
    )
    # now we claim admin fees
    pool_instance.internal._claim_admin_fees()
    pool_instance.instance.remove_liquidity(
        pool_instance.balanceOf(lp_user), [0, 0], sender=lp_user
    )

    values_post_claim = snapshot_values(pool_instance, [pool_instance, fee_receiver, lp_user])

    admin_rate = values_post_claim[fee_receiver] / values_pre_lp[lp_user]
    print(f"admin_rate: {admin_rate}")
    # in fully balanced case the balanced liq fee is almost 0
    # it should be exactly 0, but because of rounding its slightly higher (2.5e-6)
    assert admin_rate == pytest.approx(2.5e-6, rel=1e-8)


def test_lp_deposit_fee_imbalanced(gm_pool, fee_receiver):
    pool_instance = gm_pool
    pool_fee_params = pool_instance.packed_fee_params()
    mid_fee, out_fee, fee_gamma = pool_instance.internal._unpack_3(pool_fee_params)
    # print(f'mid_fee: {mid_fee/1e10}, out_fee: {out_fee/1e10}, fee_gamma: {fee_gamma/1e10}')
    # Setup LP user
    lp_user = boa.env.generate_address()
    boa.env.set_balance(lp_user, 10**20)
    for c in pool_instance.coins:
        c.approve(pool_instance, 2**256 - 1, sender=lp_user)

    # instantiate pool with some liquidity so that main size brings fees
    dead_lp_user = boa.env.generate_address()
    boa.env.set_balance(dead_lp_user, 10**20)
    for c in pool_instance.coins:
        c.approve(pool_instance, 2**256 - 1, sender=dead_lp_user)
    AMT_DEAD_LP = 1 * 10**17
    amounts_dead_lp = [AMT_DEAD_LP, AMT_DEAD_LP * 10**18 // pool_instance.price_scale()]
    boa.deal(pool_instance.coins[0], dead_lp_user, amounts_dead_lp[0])
    boa.deal(pool_instance.coins[1], dead_lp_user, amounts_dead_lp[1])

    pool_instance.instance.add_liquidity(
        [
            pool_instance.coins[0].balanceOf(dead_lp_user),
            pool_instance.coins[1].balanceOf(dead_lp_user),
        ],
        0,
        sender=dead_lp_user,
    )

    AMT_LP = 1_000_000 * 10**18
    amounts_to_add = [AMT_LP, AMT_LP * 10**18 // pool_instance.price_scale()]

    # ADD IMBALANCE
    amounts_to_add[1] = int(0.001 * amounts_to_add[1])

    boa.deal(pool_instance.coins[0], lp_user, amounts_to_add[0])
    boa.deal(pool_instance.coins[1], lp_user, amounts_to_add[1])

    values_pre_lp = snapshot_values(pool_instance, [pool_instance, fee_receiver, lp_user])
    pool_instance.instance.add_liquidity(
        [pool_instance.coins[0].balanceOf(lp_user), pool_instance.coins[1].balanceOf(lp_user)],
        0,
        sender=lp_user,
    )

    # now we claim admin fees
    pool_instance.internal._claim_admin_fees()
    pool_instance.instance.remove_liquidity(
        pool_instance.balanceOf(lp_user), [0, 0], sender=lp_user
    )

    values_post_claim = snapshot_values(pool_instance, [pool_instance, fee_receiver, lp_user])

    admin_rate = values_post_claim[fee_receiver] / values_pre_lp[lp_user]

    # when adding such imbalanced liquidity, it's equivalent to swapping of half of amount of coin_in
    # in claim_admin_fees we only consider half booked for admin/lp and don't touch rebalance reserve (lp can withdraw it though)
    # so we only get half the amount of max_fee * amount_in/2
    # also there is self.admin_fee split that gives some more to LPs.

    expected_admin_rate = out_fee / 10**10 / (2 * 2) * pool_instance.admin_fee() / 10**10
    assert admin_rate == pytest.approx(expected_admin_rate, rel=1e-2)
