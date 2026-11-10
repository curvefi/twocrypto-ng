import boa
import pytest


@pytest.mark.parametrize("coin_idx", [0, 1])
def test_set_policy_contract_reverts_when_policy_is_pool_coin(pool, coins, factory_admin, coin_idx):
    with boa.reverts(dev='"policy is coin"'):
        pool.set_policy_contract(coins[coin_idx].address, sender=factory_admin)
