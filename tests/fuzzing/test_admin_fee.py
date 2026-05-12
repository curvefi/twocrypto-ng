import boa
from hypothesis import given, settings
from hypothesis import strategies as st
from pytest import fixture
from tests.conftest import INITIAL_PRICES, _crypto_swap_with_deposit, _deploy_pool
from tests.utils.constants import POOL_DEPLOYER

SETTINGS = {"max_examples": 100, "deadline": None}
ADMIN_CLAIM_SETTINGS = {"max_examples": 25, "deadline": None}
FEE_PRECISION = 10**10
EXCHANGE_FEE = 10**7


@fixture(scope="module")
def user_b():
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    return acc


@fixture(scope="module")
def admin_fee_trader(coins, pool):
    acc = boa.env.generate_address()
    boa.env.set_balance(acc, 10**25)
    for coin in coins:
        coin.approve(pool, 2**256 - 1, sender=acc)
    return acc


@fixture(scope="module")
def concentrated_pool_with_deposit(factory, coins, params, deployer, user):
    high_a_params = params.copy()
    high_a_params["A"] = 10_000 * 10_000
    high_a_params["mid_fee"] = EXCHANGE_FEE
    high_a_params["out_fee"] = EXCHANGE_FEE

    pool = POOL_DEPLOYER.at(_deploy_pool(factory, high_a_params, coins, deployer))
    return _crypto_swap_with_deposit(coins, user, pool, INITIAL_PRICES)


@given(ratio=st.floats(min_value=0.0001, max_value=0.1))
@settings(**SETTINGS)
def test_admin_fee_after_deposit(pool, coins, fee_receiver, user, user_b, ratio):
    quantities = [10**42 // p for p in INITIAL_PRICES]

    for coin, q in zip(coins, quantities):
        for u in [user, user_b]:
            boa.deal(coin, u, q)
            with boa.env.prank(u):
                coin.approve(pool, 2**256 - 1)

    split_quantities = [quantities[0] // 100, quantities[1] // 100]

    with boa.env.prank(user):
        pool.add_liquidity(split_quantities, 0)

    with boa.env.prank(user_b):
        for _ in range(100):
            before = coins[1].balanceOf(user_b)
            pool.exchange(0, 1, split_quantities[0] // 100, 0)
            after = coins[1].balanceOf(user_b)
            to_swap = after - before
            pool.exchange(1, 0, to_swap, 0)

    balances = [pool.balances(i) for i in range(2)]
    split_quantities = [int(balances[0] * ratio), int(balances[1] * ratio)]
    with boa.env.prank(user):
        pool.add_liquidity(split_quantities, 0)

    assert coins[0].balanceOf(fee_receiver) + coins[1].balanceOf(fee_receiver) == 0

    return pool


@given(
    reserved_profit_fraction=st.one_of(
        st.just(0),
        st.integers(min_value=10**8, max_value=FEE_PRECISION),
    ),
    admin_fee=st.one_of(
        st.just(0),
        st.integers(min_value=10**8, max_value=FEE_PRECISION),
    ),
    swap_coin=st.integers(min_value=0, max_value=1),
    add_imbalance=st.integers(min_value=1, max_value=20),
    withdraw_coin=st.integers(min_value=0, max_value=1),
    withdraw_fraction=st.integers(min_value=1, max_value=20),
)
@settings(**ADMIN_CLAIM_SETTINGS)
def test_exchange_admin_fee_share_tracks_washtrade_volume(
    concentrated_pool_with_deposit,
    coins,
    fee_receiver,
    factory_admin,
    admin_fee_trader,
    reserved_profit_fraction,
    admin_fee,
    swap_coin,
    add_imbalance,
    withdraw_coin,
    withdraw_fraction,
):
    pool = concentrated_pool_with_deposit
    initial_price_scale = pool.price_scale()

    pool.set_fee_parameters(0, 0, sender=factory_admin)
    for coin in coins:
        coin.approve(pool, 2**256 - 1, sender=admin_fee_trader)

    trader_lp = pool.balanceOf(admin_fee_trader)
    if trader_lp == 0:
        amounts = [
            10_000 * 10**18,
            10_000 * 10**18 * 10**18 // initial_price_scale,
        ]
        for i, amount in enumerate(amounts):
            boa.deal(coins[i], admin_fee_trader, amount)
        pool.add_liquidity(amounts, 0, admin_fee_trader, sender=admin_fee_trader)
        trader_lp = pool.balanceOf(admin_fee_trader)

    pool.set_fee_parameters(reserved_profit_fraction, admin_fee, sender=factory_admin)
    receiver_before = [coin.balanceOf(fee_receiver) for coin in coins]

    # Fixed-out withdrawal calls the autoclaim path before taking its own fee.
    # Do it first so later assertions only need to reason about newly cached fees.
    token_amount = max(trader_lp // 10, 1)
    amount_i = pool.balances(withdraw_coin) // (10_000 + withdraw_fraction)
    pool.remove_liquidity_fixed_out(
        token_amount,
        withdraw_coin,
        amount_i,
        0,
        admin_fee_trader,
        sender=admin_fee_trader,
    )
    remove_admin_value = (
        pool.admin_balances(0) + pool.admin_balances(1) * initial_price_scale // 10**18
    )

    traded_value = 0
    for k in range(20):
        i = (swap_coin + k) % 2
        j = 1 - i
        swap_amount = pool.balances(i) // 10_000
        traded_value += swap_amount if i == 0 else swap_amount * initial_price_scale // 10**18
        boa.deal(coins[i], admin_fee_trader, swap_amount)
        pool.exchange(i, j, swap_amount, 0, admin_fee_trader, sender=admin_fee_trader)

    exchange_admin = [
        pool.admin_balances(0),
        pool.admin_balances(1),
    ]
    exchange_admin_value = (
        exchange_admin[0] + exchange_admin[1] * initial_price_scale // 10**18 - remove_admin_value
    )
    expected_exchange_admin_value = (
        traded_value
        * EXCHANGE_FEE
        * reserved_profit_fraction
        * admin_fee
        // FEE_PRECISION
        // FEE_PRECISION
        // FEE_PRECISION
    )

    # Generate add-liquidity haircut fees using a small controlled imbalance.
    add_amounts = [
        pool.balances(0) // 20_000,
        pool.balances(1) // (20_000 + add_imbalance),
    ]
    for i, amount in enumerate(add_amounts):
        boa.deal(coins[i], admin_fee_trader, amount)
    pool.add_liquidity(add_amounts, 0, admin_fee_trader, sender=admin_fee_trader)

    assert pool.price_scale() == initial_price_scale

    expected_admin = [pool.admin_balances(i) for i in range(2)]
    expected_admin_value = expected_admin[0] + expected_admin[1] * initial_price_scale // 10**18
    physical_before_claim = [coin.balanceOf(pool) for coin in coins]
    total_supply_before_claim = pool.totalSupply()
    virtual_price_before_claim = pool.virtual_price()
    xcp_profit_before_claim = pool.xcp_profit()
    D_before_claim = pool.D()

    boa.env.time_travel(seconds=86_400)
    pool.internal._claim_admin_fees()

    receiver_after = [coin.balanceOf(fee_receiver) for coin in coins]
    physical_after_claim = [coin.balanceOf(pool) for coin in coins]
    owned_after = [pool.balances(i) for i in range(2)]
    receiver_value_received = (
        receiver_after[0]
        - receiver_before[0]
        + (receiver_after[1] - receiver_before[1]) * initial_price_scale // 10**18
    )

    if reserved_profit_fraction == 0 or admin_fee == 0:
        assert expected_admin == [0, 0]
        assert exchange_admin_value == 0
    else:
        # The pool is highly concentrated, trades are small, and mid_fee == out_fee,
        # so washtrade admin take should track fee * LP/DAO split * DAO split.
        assert abs(exchange_admin_value - expected_exchange_admin_value) <= max(
            expected_exchange_admin_value // 100, 10**12
        )
        assert expected_admin_value > 0
    assert receiver_value_received == expected_admin_value
    assert [pool.admin_balances(i) for i in range(2)] == [0, 0]
    assert owned_after == [physical_after_claim[i] for i in range(2)]
    assert [physical_before_claim[i] - physical_after_claim[i] for i in range(2)] == expected_admin
    assert pool.totalSupply() == total_supply_before_claim
    assert pool.virtual_price() == virtual_price_before_claim
    assert pool.xcp_profit() == xcp_profit_before_claim
    assert pool.D() == D_before_claim
