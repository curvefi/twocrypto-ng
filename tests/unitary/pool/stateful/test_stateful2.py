import boa
from hypothesis import note
from hypothesis.stateful import rule
from hypothesis.strategies import data, integers, just
from stateful_base2 import StatefulBase


class OnlySwapStateful(StatefulBase):
    """This test suits always starts with a seeded pool
    with balanced amounts and execute only swaps depending
    on the liquidity in the pool.
    """

    @rule(
        data=data(),
        i=integers(min_value=0, max_value=1),
        user=just(boa.env.generate_address()),
    )
    def exchange(self, data, i: int, user: str):
        liquidity = self.coins[i].balanceOf(self.pool.address)
        dx = data.draw(
            integers(
                min_value=int(liquidity * 0.0001),
                max_value=int(liquidity * 0.85),
            ),
            label="dx",
        )
        note("trying to swap: {:.3%} of pool liquidity".format(dx / liquidity))
        return super().exchange(dx, i, user)


class UpOnlyLiquidityStateful(OnlySwapStateful):
    """This test suite does everything as the OnlySwapStateful
    but also adds liquidity to the pool. It does not remove liquidity."""

    # TODO
    pass


class OnlyBalancedLiquidityStateful(UpOnlyLiquidityStateful):
    """This test suite does everything as the UpOnlyLiquidityStateful
    but also removes liquidity from the pool. Both deposits and withdrawals
    are balanced.
    """

    # TODO
    pass


class UnbalancedLiquidityStateful(OnlyBalancedLiquidityStateful):
    """This test suite does everything as the OnlyBalancedLiquidityStateful
    but also removes liquidity from the pool. Deposits and withdrawals can
    be unbalanced.

    This is the most complex test suite and should be used when making sure
    that some specific gamma and A can be used without unexpected behavior.
    """

    # TODO
    pass


class RampingStateful(UnbalancedLiquidityStateful):
    """This test suite does everything as the UnbalancedLiquidityStateful
    but also ramps the pool. Because of this some of the invariant checks
    are disabled (loss is expected).
    """

    # TODO
    pass


TestOnlySwap = OnlySwapStateful.TestCase
# TestUpOnlyLiquidity = UpOnlyLiquidityStateful.TestCase
# TestOnlyBalancedLiquidity = OnlyBalancedLiquidityStateful.TestCase
# TestUnbalancedLiquidity = UnbalancedLiquidityStateful.TestCase
# RampingStateful = RampingStateful.TestCase
