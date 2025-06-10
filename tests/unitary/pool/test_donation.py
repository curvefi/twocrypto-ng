import boa
from tests.utils.constants import N_COINS
from pytest import fixture, approx

boa.env.evm.patch.code_size_limit = 1000000  # Increase code size limit for deployment


def test_cant_donate_on_empty_pool(gm_pool):
    assert gm_pool.donation_shares() == 0
    gm_pool.donate([10**18, 2 * 10**18])
    assert gm_pool.donation_shares() == 0


@fixture()
def gm_pool_with_liquidity(gm_pool):
    gm_pool.add_liquidity_balanced(1_000 * 10**18)
    return gm_pool


def test_donate(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity
    assert (
        pool.donation_shares() == 0
    ), "donation_shares should be 0 before any donation has been sent"

    HALF_DONATION_DOLLAR_VALUE = 10 * 10**18  # 20 dollars
    old_virtual_price = pool.virtual_price()
    old_balances = [pool.balances(i) for i in range(N_COINS)]
    old_xcp_profit = pool.xcp_profit()
    assert (
        pool.last_donation_release_ts() == 0
    ), "last_donation_release_ts should be 0 before any donation has been sent"
    pool.donate_balanced(HALF_DONATION_DOLLAR_VALUE)
    assert pool.last_donation_release_ts() == boa.env.evm.patch.timestamp, "ts must update"
    donated_amounts = pool.compute_balanced_amounts(HALF_DONATION_DOLLAR_VALUE)
    assert pool.virtual_price() > old_virtual_price, "Donation must increase vp due to noise fee"
    assert pool.xcp_profit() > old_xcp_profit, "donation increases xcp profit due to noise fee"
    for i in range(N_COINS):
        assert (
            pool.balances(i) == old_balances[i] + donated_amounts[i]
        ), "donations should increase balances"

    assert (
        pool.donation_shares() > 0
    ), "donation shares should be greater than 0 after a donation has been sent"


def test_absorption(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity

    HALF_DONATION_DOLLAR_VALUE = 10 * 10**18  # 20 dollars
    donated_amounts = pool.compute_balanced_amounts(HALF_DONATION_DOLLAR_VALUE)
    pool.donate(donated_amounts)

    assert (
        pool.donation_shares() > 0
    ), "donation_shares should be greater than 0 after a donation has been sent"
    assert (
        pool.internal._donation_shares() == 0
    ), "donation_shares should be 0 if no time has passed"

    old_donation_shares = pool.internal._donation_shares()
    old_virtual_price = pool.virtual_price()
    old_xcp_profit = pool.xcp_profit()

    for i in range(86400 * 7 // 1000):
        boa.env.time_travel(seconds=1)

        assert (
            pool.internal._donation_shares() >= old_donation_shares
        ), "available donation_shares should increase with time"
        assert pool.xcp_profit() == old_xcp_profit, "xcp profit should not change with time"
        assert (
            pool.virtual_price() == old_virtual_price
        ), "virtual price should not change with time"

        old_virtual_price = pool.virtual_price()
        old_xcp_profit = pool.xcp_profit()
        old_donation_shares = pool.internal._donation_shares()


def test_multiple_donations_linear_vesting(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity

    D = gm_pool_with_liquidity.donation_duration()
    DONATION_USD = 10 * 10**18

    # First donation
    minted1 = pool.donate_balanced(DONATION_USD)
    assert pool.donation_shares() == minted1
    # immediately, nothing is unlocked
    assert pool.internal._donation_shares() == 0

    # Half‐time vesting of first donation
    boa.env.time_travel(seconds=D // 2)
    unlocked1 = pool.internal._donation_shares()
    assert unlocked1 == approx(
        minted1 // 2, rel=0.02
    ), f"~50% of first batch unlocked, got {unlocked1}"

    # Second donation — must not instant‐unlock
    minted2 = pool.donate_balanced(DONATION_USD)
    assert pool.donation_shares() == minted1 + minted2
    # immediately after second donation, unlocked stays the same (approx because of precision)
    assert pool.internal._donation_shares() == approx(unlocked1, rel=0.001)

    # Another half‐period: first batch fully unlocked, second ~50%
    boa.env.time_travel(seconds=D // 2)
    unlocked2 = pool.internal._donation_shares()
    expected2 = minted1 + (minted2 // 2)
    assert unlocked2 == approx(
        expected2, rel=0.01
    ), f"Expected ~(1st + half of 2nd) = {expected2}, got {unlocked2}"


def test_slippage(gm_pool_with_liquidity, views_contract):
    pool = gm_pool_with_liquidity
    DONATION_AMOUNT = pool.compute_balanced_amounts(10 * 10**18)

    expected_amount = views_contract.calc_token_amount(DONATION_AMOUNT, True, pool.address)

    pool.donate(DONATION_AMOUNT, slippage=expected_amount)

    # we increase expected_amount but not change the amount, expect revert
    with boa.reverts("slippage"):
        pool.donate(DONATION_AMOUNT, slippage=int(1.1 * expected_amount))


def test_add_liquidity_affected_by_donations(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity

    with boa.env.anchor():
        expected_user_lp_tokens = pool.add_liquidity_balanced(10**18)

    pool.donate_balanced(10**18)
    actual_user_lp_tokens = pool.add_liquidity_balanced(10**18)

    assert (
        expected_user_lp_tokens > actual_user_lp_tokens
    ), "new user gets less lp because of noise_fee"


def test_remove_liquidity_affected_by_donations(gm_pool_with_liquidity):
    pool = gm_pool_with_liquidity

    user_lp_tokens = pool.add_liquidity_balanced(10**18)

    with boa.env.anchor():
        expected_user_tokens = pool.remove_liquidity(user_lp_tokens, [0, 0])

    pool.donate_balanced(10**18)
    actual_user_tokens = pool.remove_liquidity(user_lp_tokens, [0, 0])

    # we allow the values in these arrays to be off by one because of rounding
    for expected, actual in zip(expected_user_tokens, actual_user_tokens):
        assert expected < actual, "user gets more tokens due to noise fee"


def test_donation_improves_swap_liquidity():
    # TODO simple test where we check that a donation give a better price for a swap
    pass


def test_donation_improves_rebalance(gm_pool):
    pool = gm_pool
    N_LIQ_ADD = 100_000 * 10**18
    pool.add_liquidity_balanced(N_LIQ_ADD)

    # first swap a lot with time travel and see where the virtual_price goes
    N_SWAPS = 30
    R_SWAP = 0.9
    R_SWAP_BACK = 0.9
    T_FWD = 86_400 * 7
    R_DONATE = 0.01
    n_rb = []
    ps = []
    res_dict = {}
    for donate in [0, 1]:
        # 0 - no donation, 1 - donation
        n_rebalances = 0
        # first without donation
        with boa.env.anchor():
            for i in range(N_SWAPS):
                print(f"ITERATION {i}")
                ps_pre = pool.price_scale()
                pool.add_liquidity_balanced(int(R_DONATE * N_LIQ_ADD), donate=bool(donate))
                boa.env.time_travel(seconds=T_FWD)
                ps_post = pool.price_scale()
                n_rebalances += 1 if ps_pre != ps_post else 0

                ps_pre = pool.price_scale()
                out = pool.exchange(0, int(R_SWAP * N_LIQ_ADD), update_ema=False)
                boa.env.time_travel(seconds=T_FWD)
                ps_post = pool.price_scale()
                n_rebalances += 1 if ps_pre != ps_post else 0

                ps_pre = pool.price_scale()
                pool.exchange(1, int(R_SWAP_BACK * out), update_ema=False)
                boa.env.time_travel(seconds=T_FWD)
                ps_post = pool.price_scale()
                n_rebalances += 1 if ps_pre != ps_post else 0
            n_rb.append(n_rebalances)
            ps.append(ps_post)
        res_dict[donate] = (n_rebalances, ps_post)

    for donate, (n_rebalances, ps) in res_dict.items():
        print(f"Donation: {donate}, rebalances: {n_rebalances}, ps: {ps}")
    assert n_rb[1] >= n_rb[0], "donation should increase the number of rebalances"


def test_donation_improves_rebalance_onesided(gm_pool):
    pool = gm_pool
    N_LIQ_ADD = 100_000 * 10**18
    pool.add_liquidity_balanced(N_LIQ_ADD)

    # first swap a lot with time travel and see where the virtual_price goes
    N_SWAPS = 30
    R_SWAP = 0.9
    R_SWAP_BACK = 0.9
    T_FWD = 86_400
    R_DONATE = 0.01
    n_rb = []
    ps = []
    res_dict = {}
    for donate in [0, 1]:
        # 0 - no donation, 1 - donation
        n_rebalances = 0
        # first without donation
        with boa.env.anchor():
            for i in range(N_SWAPS):
                print(f"ITERATION {i}")
                ps_pre = pool.price_scale()
                amt_donate = pool.compute_balanced_amounts(int(R_DONATE * N_LIQ_ADD))
                amt_donate[i % 2] = 0  # flip onesided donation
                pool.add_liquidity(amt_donate, update_ema=True, donate=bool(donate))
                boa.env.time_travel(seconds=T_FWD)
                ps_post = pool.price_scale()
                n_rebalances += 1 if ps_pre != ps_post else 0

                ps_pre = pool.price_scale()
                out = pool.exchange(0, int(R_SWAP * N_LIQ_ADD), update_ema=False)
                boa.env.time_travel(seconds=T_FWD)
                ps_post = pool.price_scale()
                n_rebalances += 1 if ps_pre != ps_post else 0

                ps_pre = pool.price_scale()
                pool.exchange(1, int(R_SWAP_BACK * out), update_ema=False)
                boa.env.time_travel(seconds=T_FWD)
                ps_post = pool.price_scale()
                n_rebalances += 1 if ps_pre != ps_post else 0
            n_rb.append(n_rebalances)
            ps.append(ps_post)
        res_dict[donate] = (n_rebalances, ps_post)

    for donate, (n_rebalances, ps) in res_dict.items():
        print(f"Donation: {donate}, rebalances: {n_rebalances}, ps: {ps}")
    assert n_rb[1] >= n_rb[0], "donation should increase the number of rebalances"


def test_remove_after_rebalancing(gm_pool):
    # This test simulates a sandwich attack where a user front-runs
    # a rebalancing event to extract value.

    # Pool Setup & Initial Liquidity
    initial_amount = 400_000 * 10**18
    gm_pool.add_liquidity_balanced(initial_amount)

    # Phase 1: Donation
    # A donation is made, which increases the pool's assets without minting
    # corresponding LP tokens for a regular user. This profit is meant
    # to be socialized over time, but this attack tries to capture it.
    donation_amount = 200_000 * 10**18
    gm_pool.donate_balanced(donation_amount)

    # Phase 2: Unbalance the Pool
    # A large swap unbalances the pool.
    exchange_amount = 200_000 * 10**18
    # exchange from random address to preserve null balances
    gm_pool.exchange(0, exchange_amount, sender=boa.env.generate_address())

    # Phase 3: Manipulate Oracle and Time Travel
    # Attacker anticipates a price change and sees an opportunity.
    # We simulate this by moving time forward and directly setting the
    # oracle price that the pool will read.

    # raise price to induce rebalancing
    new_oracle_price = int(gm_pool.price_scale() * 1.3)
    gm_pool.eval(f"self.last_prices = {new_oracle_price}")
    gm_pool.eval(f"self.cached_price_oracle = {new_oracle_price}")

    # Time travel 1 week to make the new oracle price effective for rebalancing.
    week_in_seconds = 86400 * 7
    boa.env.time_travel(seconds=week_in_seconds)
    bals = [gm_pool.coins[i].balanceOf(gm_pool.god) for i in range(N_COINS)]
    assert bals[0] == bals[1] == 0, "Balances should be 0"
    # Phase 4: Add Liquidity (Attacker front-runs rebalancing)
    # The attacker adds liquidity, which will trigger a rebalancing operation
    # due to the oracle price change.

    # donation_shares_pre = gm_pool.donation_shares()
    attacker_add_liquidity_amount_coin0 = 500_000 * 10**18
    # pool is imbalanced, and we add proportionally disbalanced liquidity
    pool_balances = [gm_pool.coins[i].balanceOf(gm_pool) for i in range(N_COINS)]
    fraction = (
        attacker_add_liquidity_amount_coin0 / pool_balances[0]
    )  # rate of coin0 to pool balance
    attacker_amounts = [
        int(pool_balances[0] * fraction),
        int(pool_balances[1] * fraction),
    ]  # proportionally disbalanced lp

    # attacker_amounts = gm_pool.compute_balanced_amounts(attacker_add_liquidity_amount_coin0)
    lp_tokens_received = gm_pool.add_liquidity(attacker_amounts, donate=False)
    # assert ( # can conditional if and .eval(_tweak_price too)
    #     gm_pool.price_scale() != price_scale_before_attack
    # ), "Rebalancing should have occurred"
    # assert gm_pool.donation_shares() < donation_shares_pre, "Donation shares should decrease"

    # Phase 5: Remove Liquidity and Calculate Profit
    # Attacker removes liquidity immediately after the rebalancing.
    assets_received = gm_pool.remove_liquidity(lp_tokens_received, [0, 0])

    # Calculate the net gain/loss in tokens, same as in the script.
    delta_coin0 = assets_received[0] - attacker_amounts[0]
    delta_coin1 = assets_received[1] - attacker_amounts[1]
    rel_delta_coin0 = delta_coin0 / attacker_amounts[0]
    rel_delta_coin1 = delta_coin1 / attacker_amounts[1]
    print(f"Rel delta coin0: {rel_delta_coin0:.2%}, Rel delta coin1: {rel_delta_coin1:.2%}")
    assert (
        delta_coin0 <= 0 and delta_coin1 <= 0
    ), f"Attacker shouldn't have a net positive return. Deltas: {delta_coin0}, {delta_coin1}"
    # if delta_coin0 > 0 or delta_coin1 > 0:
    #     print("Profit")
    # else:
    #     print("No profit")
    # print(f"Delta coin0: {delta_coin0}, Delta coin1: {delta_coin1}")
