from math import sqrt

import boa
import pytest

from tests.conftest import INITIAL_PRICES
from tests.utils import approx
from tests.utils.constants import UNIX_DAY

SETTINGS = {"max_examples": 1000, "deadline": None}


def norm(price_oracle, price_scale):
    norm = 0
    ratio = price_oracle * 10**18 / price_scale
    if ratio > 10**18:
        ratio -= 10**18
    else:
        ratio = 10**18 - ratio
    norm += ratio**2
    return sqrt(norm)


def test_initial(pool_with_deposit):
    assert pool_with_deposit.price_scale() == INITIAL_PRICES[1]
    assert pool_with_deposit.price_oracle() == INITIAL_PRICES[1]


@pytest.mark.parametrize("i", [0, 1])
def test_price_scale_change(pool_with_deposit, i, coins, users):
    j = 1 - i
    amount = 10**6 * 10**18
    t = UNIX_DAY
    user = users[1]
    prices1 = INITIAL_PRICES
    amount = amount * 10**18 // prices1[i]
    boa.deal(coins[i], user, amount)
    boa.deal(coins[j], user, amount)
    coins[i].approve(pool_with_deposit, 2**256 - 1, sender=user)
    coins[j].approve(pool_with_deposit, 2**256 - 1, sender=user)

    out = pool_with_deposit.exchange(i, j, amount, 0, sender=user)
    pool_with_deposit.exchange(j, i, int(out * 0.95), 0, sender=user)
    price_scale_1 = pool_with_deposit.price_scale()

    boa.env.time_travel(t)

    pool_with_deposit.exchange(0, 1, coins[0].balanceOf(user), 0, sender=user)

    price_oracle = pool_with_deposit.price_oracle()
    rebal_params = pool_with_deposit.internal._unpack_3(
        pool_with_deposit._storage.packed_rebalancing_params.get()
    )
    _norm = norm(price_oracle, price_scale_1)
    step = max(rebal_params[1], _norm / 5)
    price_scale_2 = pool_with_deposit.price_scale()

    price_diff = abs(price_scale_2 - price_scale_1)
    adjustment = int(step * abs(price_oracle - price_scale_1) / _norm)
    assert price_diff > 0
    assert approx(adjustment, price_diff, 0.01)
    assert approx(
        pool_with_deposit.virtual_price(),
        pool_with_deposit.get_virtual_price(),
        1e-10,
    )


def test_lp_price(pool_with_deposit):
    tvl = (
        pool_with_deposit.balances(0)
        + pool_with_deposit.balances(1) * pool_with_deposit.price_scale() // 10**18
    )
    naive_price = tvl * 10**18 // pool_with_deposit.totalSupply()
    assert approx(naive_price, pool_with_deposit.lp_price(), 0)
