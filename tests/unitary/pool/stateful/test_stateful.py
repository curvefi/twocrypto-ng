from hypothesis import assume, note
from hypothesis.stateful import precondition, rule
from hypothesis.strategies import data, floats, integers, sampled_from
from stateful_base import StatefulBase
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
        self.report_equilibrium()


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
    def add_liquidity_balanced(self, amount: int, user: str):
        balanced_amounts = self.get_balanced_deposit_amounts(amount)
        note(
            "increasing pool liquidity with balanced amounts: "
            + "{:.2e} {:.2e}".format(*balanced_amounts)
        )
        self.add_liquidity(balanced_amounts, user)
        # TODO check equilibrium should be unchanged


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
    def remove_liquidity_balanced(self, data):
        # we use a data strategy since the amount we want to remove
        # depends on the pool liquidity and the depositor balance
        # which are only known at runtime
        depositor = data.draw(
            sampled_from(list(self.depositors)),
            label="depositor for balanced withdraw",
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
        # TODO check equilibrium should be unchanged


class ImbalancedLiquidityStateful(OnlyBalancedLiquidityStateful):
    """This test suite does everything as the `OnlyBalancedLiquidityStateful`
    Deposits and withdrawals can be imbalanced.

    This is the most complex test suite and should be used when making sure
    that some specific gamma and A can be used without unexpected behavior.
    """

    @rule(
        amount=integers(min_value=int(1e20), max_value=int(1e24)),
        imbalance_ratio=floats(min_value=0, max_value=1),
        user=address,
    )
    def add_liquidity_imbalanced(
        self, amount: int, imbalance_ratio: float, user: str
    ):
        balanced_amounts = self.get_balanced_deposit_amounts(amount)
        imbalanced_amounts = [
            int(balanced_amounts[0] * imbalance_ratio),
            int(balanced_amounts[1] * (1 - imbalance_ratio)),
        ]
        # TODO better note with direction of imbalance
        note(
            "imabalanced deposit of liquidity: {:.2%} {:.2%}".format(
                imbalance_ratio, 1 - imbalance_ratio
            )
        )
        self.add_liquidity(imbalanced_amounts, user)
        self.report_equilibrium()

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
        percentage=floats(min_value=0.1, max_value=1),
        coin_idx=integers(min_value=0, max_value=1),
    )
    def remove_liquidity_imbalanced(
        self, data, percentage: float, coin_idx: int
    ):
        # we use a data strategy since the amount we want to remove
        # depends on the pool liquidity and the depositor balance
        depositor = data.draw(
            sampled_from(list(self.depositors)),
            label="depositor for imbalanced withdraw",
        )
        depositor_balance = self.pool.balanceOf(depositor)

        # ratio of the pool that the depositor will remove
        depositor_ratio = (
            depositor_balance * percentage
        ) / self.pool.totalSupply()

        # here things gets dirty because removing
        # liquidity in an imbalanced way can break the pool
        # so we have to filter out edge cases that are unlikely
        # to happen in the real world
        assume(
            # too small amounts lead to "Loss" revert
            depositor_balance >= 1e11
            # if we withdraw the whole liquidity
            # (in an imabalanced way) it will revert
            and depositor_ratio < 0.7
        )
        note(
            "removing {:.2e} lp tokens ".format(depositor_balance * percentage)
            + "which is {:.4%} of pool liquidity ".format(depositor_ratio)
            + "(only coin {}) ".format(coin_idx)
            + "and {:.1%} of address balance".format(percentage)
        )
        self.remove_liquidity_one_coin(percentage, coin_idx, depositor)
        self.report_equilibrium()

    def can_always_withdraw(self):
        super().can_always_withdraw(imbalanced_operations_allowed=True)


class RampingStateful(ImbalancedLiquidityStateful):
    """This test suite does everything as the `ImbalancedLiquidityStateful`
    but also ramps the pool. Because of this some of the invariant checks
    are disabled (loss is expected).
    """

    # TODO
    pass


# TestOnlySwap = OnlySwapStateful.TestCase
# TestUpOnlyLiquidity = UpOnlyLiquidityStateful.TestCase
# TestOnlyBalancedLiquidity = OnlyBalancedLiquidityStateful.TestCase
TestImbalancedLiquidity = ImbalancedLiquidityStateful.TestCase
# RampingStateful = RampingStateful.TestCase
# TODO variable decimals
