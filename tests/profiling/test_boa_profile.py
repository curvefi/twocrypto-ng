import random

import boa
import pytest

from tests.utils.tokens import mint_for_testing


NUM_RUNS = 10
N_COINS = 2


def _choose_indices():
    i = random.randint(0, N_COINS-1)
    j = 0 if i == 1 else 1
    return i, j


@pytest.mark.profile
def test_profile_amms(pools, tokens):
    
    user = boa.env.generate_address()

    for pool in pools:
        
        for coin in tokens:
            mint_for_testing(coin, user, 10**50)
            coin.approve(pool, 2**256 - 1, sender=user)

        with boa.env.prank(user):

            for k in range(NUM_RUNS):

                # proportional deposit:
                balances = [pool.balances(i) for i in range(N_COINS)]
                amount_first_coin = random.uniform(0, 0.05) * 10**(18+random.randint(1, 3))
                amounts =  [int(amount_first_coin), int(amount_first_coin * 1e18 // pool.price_scale())]
                pool.add_liquidity(amounts, 0)
                boa.env.time_travel(random.randint(12, 600))

                # deposit single token:
                balances = [pool.balances(i) for i in range(N_COINS)]
                c = random.uniform(0, 0.05)
                i = random.randint(0, N_COINS-1)
                amounts = [0] * N_COINS
                for j in range(N_COINS):
                    if i == j:
                        amounts[i] = int(balances[i] * c)
                pool.add_liquidity(amounts, 0)
                boa.env.time_travel(random.randint(12, 600))

                # swap:
                i, j = _choose_indices()
                amount = int(pool.balances(i) * 0.01)
                pool.exchange(i, j, amount, 0)
                boa.env.time_travel(random.randint(12, 600))

                # withdraw proportionally:
                amount = int(pool.balanceOf(user) * random.uniform(0, 0.01))
                pool.remove_liquidity(amount, [0] * N_COINS)
                boa.env.time_travel(random.randint(12, 600))

                # withdraw in one coin:
                i = random.randint(0, N_COINS-1)
                amount = int(pool.balanceOf(user) * 0.01)
                pool.remove_liquidity_one_coin(amount, i, 0)
