from hypothesis import note
from hypothesis.stateful import precondition, rule
from hypothesis.strategies import data, integers, sampled_from
from stateful_base2 import StatefulBase
from strategies import address


class OnlySwapStateful(StatefulBase):
    """This test suits always starts with a seeded pool
    with balanced amounts and execute only swaps depending
    on the liquidity in the pool.
    """

    @rule(
        data=data(),
        i=integers(min_value=0, max_value=1),
        user=address,
    )
    def exchange_rule(self, data, i: int, user: str):
        liquidity = self.coins[i].balanceOf(self.pool.address)
        # we use a data strategy since the amount we want to swap
        # depends on the pool liquidity which is only known at runtime
        dx = data.draw(
            integers(
                # swap can be between 0.001% and 60% of the pool liquidity
                min_value=int(liquidity * 0.0001),
                max_value=int(liquidity * 0.60),
            ),
            label="dx",
        )
        note("trying to swap: {:.3%} of pool liquidity".format(dx / liquidity))
        self.exchange(dx, i, user)


class UpOnlyLiquidityStateful(OnlySwapStateful):
    """This test suite does everything as the `OnlySwapStateful`
    but also adds liquidity to the pool. It does not remove liquidity."""

    # too high liquidity can lead to overflows
    @precondition(lambda self: self.pool.D() < 1e28)
    @rule(
        # we can only add liquidity up to 1e25, this was reduced
        # from the initial deposit that can be up to 1e30 to avoid
        # breaking newton_D
        amount=integers(min_value=int(1e20), max_value=int(1e25)),
        user=address,
    )
    def add_liquidity_balanced_rule(self, amount: int, user: str):
        balanced_amounts = self.get_balanced_deposit_amounts(amount)
        note(
            "increasing pool liquidity with balanced amounts: "
            + "{:.2e} {:.2e}".format(*balanced_amounts)
        )
        self.add_liquidity(balanced_amounts, user)


class OnlyBalancedLiquidityStateful(UpOnlyLiquidityStateful):
    """This test suite does everything as the `UpOnlyLiquidityStateful`
    but also removes liquidity from the pool. Both deposits and withdrawals
    are balanced.
    """

    @precondition(
        # we need to have enough liquidity before removing
        # leaving the pool with shallow liquidity can break the amm
        lambda self: self.pool.totalSupply() > 10e20
        # we should not empty the pool
        # (we still check that we can in the invariants)
        and len(self.depositors) > 1
    )
    @rule(
        data=data(),
    )
    def remove_liquidity_balanced_rule(self, data):
        # we use a data strategy since the amount we want to remove
        # depends on the pool liquidity and the depositor balance
        # which are only known at runtime
        depositor = data.draw(
            sampled_from(list(self.depositors)), label="depositor"
        )
        depositor_balance = self.pool.balanceOf(depositor)
        # we can remove between 10% and 100% of the depositor balance
        amount = data.draw(
            integers(
                min_value=int(depositor_balance * 0.10),
                max_value=depositor_balance,
            ),
            label="amount to withdraw",
        )
        note(
            "Removing {:.2e} from the pool ".format(amount)
            + "that is {:.1%} of address balance".format(
                amount / depositor_balance
            )
            + " and {:.1%} of pool liquidity".format(
                amount / self.pool.totalSupply()
            )
        )

        self.remove_liquidity(amount, depositor)


class UnbalancedLiquidityStateful(OnlyBalancedLiquidityStateful):
    """This test suite does everything as the `OnlyBalancedLiquidityStateful`
    Deposits and withdrawals can be unbalanced.

    This is the most complex test suite and should be used when making sure
    that some specific gamma and A can be used without unexpected behavior.
    """

    # TODO
    pass


class RampingStateful(UnbalancedLiquidityStateful):
    """This test suite does everything as the `UnbalancedLiquidityStateful`
    but also ramps the pool. Because of this some of the invariant checks
    are disabled (loss is expected).
    """

    # TODO
    pass


TestOnlySwap = OnlySwapStateful.TestCase
TestUpOnlyLiquidity = UpOnlyLiquidityStateful.TestCase
TestOnlyBalancedLiquidity = OnlyBalancedLiquidityStateful.TestCase
# TestUnbalancedLiquidity = UnbalancedLiquidityStateful.TestCase
# RampingStateful = RampingStateful.TestCase
# TODO variable decimals
