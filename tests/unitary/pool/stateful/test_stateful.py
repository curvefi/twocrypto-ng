import boa
from hypothesis import assume, event, note
from hypothesis.stateful import precondition, rule
from hypothesis.strategies import data, floats, integers, sampled_from
from stateful_base import StatefulBase

from tests.utils.constants import MAX_A, MAX_GAMMA, MIN_A, MIN_GAMMA, UNIX_DAY
from tests.utils.strategies import address


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
        else:
            # if the exchange was not successful we add an
            # event to make sure that failure was reasonable
            event(
                "swap failed (balance = {:.2e}) {:.2%} of liquidity with A: "
                "{:.2e} and gamma: {:.2e}".format(
                    self.equilibrium,
                    dx / liquidity,
                    self.pool.A(),
                    self.pool.gamma(),
                )
            )


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
        data=data(),
        user=address,
    )
    def add_liquidity_imbalanced(self, data, user: str):
        note("[IMBALANCED DEPOSIT]")

        # we define a jump limit to avoid very big imbalanced deposits
        # that would make the liquidity in the pool before the deposit
        # irrelevant
        jump_limit = 2

        # we store the balances since we need them to calculate the
        # imbalanced amounts
        balances = [self.coins[i].balanceOf(self.pool) for i in range(2)]

        # deposit amount for coin 0
        a0 = data.draw(
            integers(
                min_value=int(1e13),
                max_value=max(balances[0] * jump_limit, int(1e13)),
            )
        )

        # we need this because 1e14 is a minimum in the contracts
        # for imbalance deposits. If we deposits two imbalanced amounts
        # the smallest one should be at least 1e14.
        # If the first deposit is smaller than 1e14 we set the second
        # deposit to 0.
        a1_min = 1e14 if a0 < 1e14 else 0

        # deposit amount for coin 1
        a1 = data.draw(
            integers(
                min_value=a1_min,
                max_value=max(balances[1] * jump_limit, a1_min),
            )
        )

        # we construct the imbalanced amounts argument for the function
        imbalanced_amounts = [a0, a1]

        note("depositing {:.2e} and {:.2e}".format(*imbalanced_amounts))

        # we correct the decimals of the imbalanced amounts
        imbalanced_amounts = self.correct_all_decimals(imbalanced_amounts)

        # we add the liquidity
        self.add_liquidity(imbalanced_amounts, user)

        # since this is an imbalanced deposit we report the new equilibrium
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
        # we allow imbalanced operations by default
        super().can_always_withdraw(imbalanced_operations_allowed=True)

    def virtual_price(self):
        # we disable this invariant because claiming admin fees can break it.
        # claiming admin_fees can lead to a decrease in the virtual price
        # however the pool is still profitable as long as xcpx is increasing.
        pass


class RampingStateful(ImbalancedLiquidityStateful):
    """This test suite does everything as the `ImbalancedLiquidityStateful`
    but also ramps the pool. Because of this some of the invariant checks
    are disabled (loss is expected).

    This class tests statefully tests wheter ramping A and
    gamma does not break the pool. At the start it always start
    with a ramp, then it can ramp again.
    """

    # create the steps for the ramp
    # [0.2, 0.3 ... 0.9, 1, 2, 3 ... 10]
    change_steps = [x / 10 if x < 10 else x for x in range(2, 11)] + list(
        range(2, 11)
    )

    # we can only ramp A and gamma at most 10x
    # lower/higher than their starting value
    change_step_strategy = sampled_from(change_steps)

    # we fuzz the ramp duration up to a year
    days = integers(min_value=1, max_value=365)

    @precondition(lambda self: not self.is_ramping())
    @rule(
        A_change=change_step_strategy,
        gamma_change=change_step_strategy,
        days=days,
    )
    def ramp(self, A_change, gamma_change, days):
        """
        Computes the new A and gamma values by multiplying the current ones
        by the change factors. Then clamps the new values to stay in the
        [MIN_A, MAX_A] and [MIN_GAMMA, MAX_GAMMA] ranges.

        Then proceeds to ramp the pool with the new values (with admin rights).
        """
        note("[RAMPING]")
        new_A = self.pool.A() * A_change
        new_A = int(
            max(MIN_A, min(MAX_A, new_A))
        )  # clamp new_A to stay in [MIN_A, MAX_A]

        new_gamma = self.pool.gamma() * gamma_change
        new_gamma = int(
            max(MIN_GAMMA, min(MAX_GAMMA, new_gamma))
        )  # clamp new_gamma to stay in [MIN_GAMMA, MAX_GAMMA]

        # current timestamp + fuzzed days
        ramp_duration = boa.env.evm.patch.timestamp + days * UNIX_DAY

        self.pool.ramp_A_gamma(
            new_A,
            new_gamma,
            ramp_duration,
            sender=self.admin,
        )

        note(
            "ramping A and gamma to {:.2e} and {:.2e}".format(new_A, new_gamma)
        )

    def up_only_profit(self):
        # we disable this invariant because ramping can lead to losses
        pass

    def sanity_check(self):
        # we disable this invariant because ramping can lead to losses
        pass


TestOnlySwap = OnlySwapStateful.TestCase
TestUpOnlyLiquidity = UpOnlyLiquidityStateful.TestCase
TestOnlyBalancedLiquidity = OnlyBalancedLiquidityStateful.TestCase
TestImbalancedLiquidity = ImbalancedLiquidityStateful.TestCase
TestRampingStateful = RampingStateful.TestCase
