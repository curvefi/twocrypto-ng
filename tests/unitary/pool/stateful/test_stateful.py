from hypothesis import assume, event, note
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
        note("[EXCHANGE]")
        liquidity = self.coins[i].balanceOf(self.pool)
        # we use a data strategy since the amount we want to swap
        # depends on the pool liquidity which is only known at runtime
        dx = data.draw(
            integers(
                # swap can be between 0.01% and 50% of the pool liquidity
                min_value=int(liquidity * 0.0001),
                max_value=int(liquidity * 0.50),
            ),
            label="dx",
        )
        # decimals: sometime very small amount get rounded to 0
        if dx == 0:
            note("corrected dx draw to 1")
            event("corrected dx to 1")
            dx = 1

        note("trying to swap: {:.2%} of pool liquidity".format(dx / liquidity))

        exchange_successful = self.exchange(dx, i, user)

        if exchange_successful:
            # if the exchange was successful it alters the pool
            # composition so we report the new equilibrium
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
        note("[BALANCED DEPOSIT]")
        # figure out the amount of the second token for a balanced deposit
        balanced_amounts = self.get_balanced_deposit_amounts(amount)

        # correct amounts to the right number of decimals
        balanced_amounts = self.correct_all_decimals(balanced_amounts)

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
    def remove_liquidity_balanced(self, data):
        note("[BALANCED WITHDRAW]")
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


class ImbalancedLiquidityStateful(OnlyBalancedLiquidityStateful):
    """This test suite does everything as the `OnlyBalancedLiquidityStateful`
    Deposits and withdrawals can be imbalanced.

    This is the most complex test suite and should be used when making sure
    that some specific gamma and A can be used without unexpected behavior.
    """

    # too high imbalanced liquidity can break newton_D
    @precondition(lambda self: self.pool.D() < 1e28)
    @rule(
        amount=integers(min_value=int(1e20), max_value=int(1e24)),
        imbalance_ratio=floats(min_value=0, max_value=1),
        user=address,
    )
    def add_liquidity_imbalanced(
        self, amount: int, imbalance_ratio: float, user: str
    ):
        note("[IMBALANCED DEPOSIT]")
        balanced_amounts = self.get_balanced_deposit_amounts(amount)
        imbalanced_amounts = [
            int(balanced_amounts[0] * imbalance_ratio)
            if imbalance_ratio != 1
            else balanced_amounts[0],
            int(balanced_amounts[1] * (1 - imbalance_ratio))
            if imbalance_ratio != 0
            else balanced_amounts[1],
        ]
        # too big/small highly imbalanced deposits can break newton_D
        # this check is not necessary for the first coin in the pool
        # because of the way the amounts are generated, since the
        # contraints are even stronger.
        assume(imbalance_ratio > 0.2 or 1e14 <= balanced_amounts[1] <= 1e30)

        # measures by how much the deposit will increase the
        # amount of liquidity in the pool.
        liquidity_jump_ratio = [
            imbalanced_amounts[i] / self.coins[i].balanceOf(self.pool)
            for i in range(2)
        ]

        # 1e7 is a magic number that was found by trial and error (limits
        # increase to 1000x times the liquidity of the pool)
        JUMP_LIMIT = 1e7
        # we make sure that the amount being deposited is not much
        # bigger than the amount already in the pool, otherwise the
        # pool math will break.
        assume(
            liquidity_jump_ratio[0] < JUMP_LIMIT
            and liquidity_jump_ratio[1] < JUMP_LIMIT
        )
        note(
            "imabalanced deposit of liquidity: {:.1%}/{:.1%} => ".format(
                imbalance_ratio, 1 - imbalance_ratio
            )
            + "{:.2e}/{:.2e}".format(*imbalanced_amounts)
            + "\n    which is {:.5%} of coin 0 pool balance ({:2e})".format(
                liquidity_jump_ratio[0], self.coins[0].balanceOf(self.pool)
            )
            + "\n    which is {:.5%} of coin 1 pool balance ({:2e})".format(
                liquidity_jump_ratio[1], self.coins[1].balanceOf(self.pool)
            )
        )

        imbalanced_amounts = self.correct_all_decimals(imbalanced_amounts)
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
        note("[IMBALANCED WITHDRAW]")
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
            # too small amounts can lead to decreases
            # in virtual balance due to rounding errors
            depositor_balance >= 1e11
            # if we withdraw too much liquidity
            # (in an imabalanced way) it will revert
            and depositor_ratio < 0.6
        )
        note(
            "removing {:.2e} lp tokens ".format(depositor_balance * percentage)
            + "which is {:.4%} of pool liquidity ".format(depositor_ratio)
            + "(only coin {}) ".format(coin_idx)
            + "and {:.1%} of address balance".format(percentage)
        )
        self.remove_liquidity_one_coin(percentage, coin_idx, depositor)
        self.report_equilibrium()

    def can_always_withdraw(self, imbalanced_operations_allowed=True):
        # we allow imabalanced operations by default
        super().can_always_withdraw(imbalanced_operations_allowed=True)


class RampingStateful(ImbalancedLiquidityStateful):
    """This test suite does everything as the `ImbalancedLiquidityStateful`
    but also ramps the pool. Because of this some of the invariant checks
    are disabled (loss is expected).
    """

    # TODO
    pass


TestOnlySwap = OnlySwapStateful.TestCase
TestUpOnlyLiquidity = UpOnlyLiquidityStateful.TestCase
TestOnlyBalancedLiquidity = OnlyBalancedLiquidityStateful.TestCase
TestImbalancedLiquidity = ImbalancedLiquidityStateful.TestCase
# RampingStateful = RampingStateful.TestCase
