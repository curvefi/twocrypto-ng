"""
First-deposit admission.

The first deposit is the only operation that never reaches get_y, get_p or
tweak_price, so the pool checks there the D range those functions require,
[10**17, 10**33], and the pool's 1,000:1 balance guard. The view mirrors the
refusal by quoting 0.
"""

import boa
import pytest

from tests.conftest import _deploy_pool
from tests.utils.constants import ERC20_DEPLOYER, POOL_DEPLOYER
from tests.utils.god_mode import GodModePool


def _amounts(pool, value_0, value_1):
    """value_0 of coin 0 and coin 1 worth value_1 (in coin 0) at the pool's price scale."""
    return [value_0, value_1 * 10**18 // pool.price_scale()]


def _assert_admitted(pool, amounts):
    quote = pool.calc_token_amount(amounts, True)
    minted = GodModePool(pool).add_liquidity(amounts)
    assert minted > 0
    assert minted == quote
    assert 10**17 <= pool.D() <= 10**33


def _assert_refused(pool, amounts, *reason, **dev):
    assert pool.calc_token_amount(amounts, True) == 0
    with boa.reverts(*reason, **dev):
        GodModePool(pool).add_liquidity(amounts)
    assert pool.D() == 0


@pytest.fixture()
def unit_price_pool(factory, coins, params, deployer):
    # price scale 1e18 makes the scaled balances equal the deposited amounts
    p = {**params, "initial_prices": [10**18, 10**18]}
    return POOL_DEPLOYER.at(_deploy_pool(factory, p, coins, deployer))


@pytest.mark.parametrize(
    "value_0, value_1",
    [
        (10**17, 10**17),  # D about 2e17
        (10**24, 10**24),
        (45 * 10**31, 45 * 10**31),  # D about 9e32
        (10**24, 10**24 // 900),  # 900:1, inside the 1,000:1 guard
        (10**24 // 900, 10**24),
    ],
)
def test_admitted_first_deposit_matches_quote(pool, value_0, value_1):
    _assert_admitted(pool, _amounts(pool, value_0, value_1))


@pytest.mark.parametrize(
    "value_0, value_1",
    [
        (2 * 10**16, 2 * 10**16),  # D about 4e16
        (6 * 10**32, 6 * 10**32),  # D about 1.2e33; each balance is still below 1e33
    ],
)
def test_first_deposit_outside_D_domain_refused(pool, value_0, value_1):
    _assert_refused(pool, _amounts(pool, value_0, value_1), dev='"initial D outside math domain"')


@pytest.mark.parametrize(
    "value_0, value_1",
    [
        (10**24, 10**24 // 2_000),
        (10**24 // 2_000, 10**24),
    ],
)
def test_imbalanced_first_deposit_refused(pool, value_0, value_1):
    _assert_refused(pool, _amounts(pool, value_0, value_1), "!balance")


@pytest.mark.parametrize(
    "amount, admitted",
    [
        (5 * 10**16 - 1, False),
        (5 * 10**16, True),  # D exactly 1e17
        (5 * 10**32, True),  # D exactly 1e33
        (5 * 10**32 + 1, False),
    ],
)
def test_D_bounds_are_inclusive(unit_price_pool, math_contract, amount, admitted):
    pool = unit_price_pool
    amounts = [amount, amount]
    # balanced balances: newton_D returns exactly twice the per-coin balance
    assert math_contract.newton_D(pool.A(), pool.gamma(), amounts, 0) == 2 * amount

    if admitted:
        _assert_admitted(pool, amounts)
    else:
        _assert_refused(pool, amounts, dev='"initial D outside math domain"')


@pytest.mark.parametrize("heavy", [0, 1])
@pytest.mark.parametrize("excess, admitted", [(-1, True), (0, False)])
def test_ratio_bound(unit_price_pool, heavy, excess, admitted):
    # floor(max / min) must stay below 1,000
    light_amount = 10**21
    amounts = [light_amount, light_amount]
    amounts[heavy] = 1_000 * light_amount + excess

    if admitted:
        _assert_admitted(unit_price_pool, amounts)
    else:
        _assert_refused(unit_price_pool, amounts, "!balance")


@pytest.mark.parametrize(
    "amounts",
    [
        [10**24, 0],
        [0, 10**24],
        [10**24, 10**24 // 20_000],  # beyond newton_D's own 10,000:1 input check
    ],
)
def test_one_sided_first_deposit_quotes_zero(unit_price_pool, amounts):
    # the pool reverts inside newton_D; the view quotes 0 instead of reverting
    _assert_refused(unit_price_pool, amounts)


def test_mixed_decimals_first_deposit(factory, params, deployer):
    coins = [
        ERC20_DEPLOYER.deploy("USD", "USD", 18),
        ERC20_DEPLOYER.deploy("USDC", "USDC", 6),
    ]
    p = {**params, "initial_prices": [10**18, 10**18]}

    def fresh_pool():
        return POOL_DEPLOYER.at(_deploy_pool(factory, p, coins, deployer))

    # coin 1 has 6 decimals: its scaled balance is amount * 10**12
    _assert_admitted(fresh_pool(), [10**18, 10**6])
    _assert_admitted(fresh_pool(), [5 * 10**16, 5 * 10**4])  # D exactly 1e17
    _assert_refused(
        fresh_pool(), [5 * 10**16, 5 * 10**4 - 1], dev='"initial D outside math domain"'
    )
    _assert_refused(fresh_pool(), [10**24, 5 * 10**8], "!balance")  # 2,000:1
