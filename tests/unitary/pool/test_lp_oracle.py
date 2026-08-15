import boa
import pytest

from tests.utils import approx
from tests.utils.constants import VENOM_FLAG

LP_ORACLE_DEPLOYER = boa.load_partial(
    "contracts/main/LPOracle.vy", compiler_args={"experimental_codegen": VENOM_FLAG}
)


@pytest.fixture(scope="module")
def lp_oracle(deployer):
    with boa.env.prank(deployer):
        return LP_ORACLE_DEPLOYER.deploy()


def test_lp_oracle_sanity_and_initial_price(lp_oracle, pool_with_deposit):
    assert lp_oracle.sanity_check(pool_with_deposit) is True
    assert approx(
        lp_oracle.lp_price(pool_with_deposit, 0) * pool_with_deposit.totalSupply() // 10**18,
        2 * int(1.5 * 10**6) * 10**18,  # 2 * dollar_amt_each_coin
        1e-6,
    )


def test_lp_oracle_consistent_cross_numeraire_after_state_change(
    lp_oracle, pool_with_deposit, coins, users
):
    user = users[2]
    amount = 300_000 * 10**18
    for coin in coins:
        boa.deal(coin, user, amount)
        coin.approve(pool_with_deposit, 2**256 - 1, sender=user)

    out = pool_with_deposit.exchange(0, 1, amount, 0, sender=user)
    pool_with_deposit.exchange(1, 0, out // 3, 0, sender=user)

    p_oracle = pool_with_deposit.price_oracle()
    lp0 = lp_oracle.lp_price(pool_with_deposit, 0)
    lp1 = lp_oracle.lp_price(pool_with_deposit, 1)

    assert lp0 > 0 and lp1 > 0
    assert approx(lp0, lp1 * p_oracle // 10**18, 1e-6)
