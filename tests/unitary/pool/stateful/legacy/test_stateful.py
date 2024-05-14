import boa
from hypothesis import HealthCheck, settings
from hypothesis.stateful import (
    Bundle,
    precondition,
    rule,
    run_state_machine_as_test,
)

from tests.fixtures.pool import INITIAL_PRICES
from tests.unitary.pool.stateful.legacy.stateful_base import StatefulBase
from tests.utils.tokens import mint_for_testing

MAX_SAMPLES = 20
STEP_COUNT = 100
MAX_D = 10**12 * 10**18  # $1T is hopefully a reasonable cap for tests


class NumbaGoUp(StatefulBase):
    """
    Test that profit goes up
    """

    depositor = Bundle("depositor")

    def supply_not_too_big(self):
        # TODO unsure about this condition
        # this is not stableswap so hard
        # to say what is a good limit
        return self.swap.D() < MAX_D

    def pool_not_empty(self):
        return self.total_supply != 0

    @precondition(supply_not_too_big)
    @rule(
        target=depositor,
        deposit_amounts=StatefulBase.two_token_amounts,
        user=StatefulBase.user,
    )
    def add_liquidity(self, amounts, user):
        if sum(amounts) == 0:
            return str(user)

        new_balances = [x + y for x, y in zip(self.balances, amounts)]

        for coin, q in zip(self.coins, amounts):
            mint_for_testing(coin, user, q)

        try:

            tokens = self.swap.balanceOf(user)
            self.swap.add_liquidity(amounts, 0, sender=user)
            tokens = self.swap.balanceOf(user) - tokens
            self.total_supply += tokens
            self.balances = new_balances

        except Exception:

            if self.check_limits(amounts):
                raise
            return str(user)

        # This is to check that we didn't end up in a borked state after
        # an exchange succeeded
        try:
            self.swap.get_dy(0, 1, 10 ** (self.decimals[0] - 2))
        except Exception:
            self.swap.get_dy(
                1,
                0,
                10**16 * 10 ** self.decimals[1] // self.swap.price_scale(),
            )
        return str(user)

    @precondition(pool_not_empty)
    @rule(token_amount=StatefulBase.token_amount, user=depositor)
    def remove_liquidity(self, token_amount, user):
        # TODO can we do something for slippage, maybe make it == token_amount?
        if self.swap.balanceOf(user) < token_amount or token_amount == 0:
            print("Skipping")
            # TODO this should be test with fuzzing
            # no need to have this case in stateful
            with boa.reverts():
                self.swap.remove_liquidity(token_amount, [0] * 2, sender=user)
        else:
            print("Removing")
            amounts = [c.balanceOf(user) for c in self.coins]
            tokens = self.swap.balanceOf(user)
            with self.upkeep_on_claim():
                self.swap.remove_liquidity(token_amount, [0] * 2, sender=user)
            tokens -= self.swap.balanceOf(user)
            self.total_supply -= tokens
            amounts = [
                (c.balanceOf(user) - a) for c, a in zip(self.coins, amounts)
            ]
            self.balances = [b - a for a, b in zip(amounts, self.balances)]

            # Virtual price resets if everything is withdrawn
            if self.total_supply == 0:
                self.virtual_price = 10**18

    @precondition(pool_not_empty)
    @rule(
        token_amount=StatefulBase.token_amount,
        exchange_i=StatefulBase.exchange_i,
        user=depositor,
    )
    def remove_liquidity_one_coin(self, token_amount, exchange_i, user):
        try:
            calc_out_amount = self.swap.calc_withdraw_one_coin(
                token_amount, exchange_i
            )
        except Exception:
            if (
                self.check_limits([0] * 2)
                and not (token_amount > self.total_supply)
                and token_amount > 10000
            ):
                self.swap.calc_withdraw_one_coin(
                    token_amount, exchange_i, sender=user
                )
            return

        d_token = self.swap.balanceOf(user)
        if d_token < token_amount:
            with boa.reverts():
                self.swap.remove_liquidity_one_coin(
                    token_amount, exchange_i, 0, sender=user
                )
            return

        d_balance = self.coins[exchange_i].balanceOf(user)
        try:
            with self.upkeep_on_claim():
                self.swap.remove_liquidity_one_coin(
                    token_amount, exchange_i, 0, sender=user
                )
        except Exception:
            # Small amounts may fail with rounding errors
            if (
                calc_out_amount > 100
                and token_amount / self.total_supply > 1e-10
                and calc_out_amount / self.swap.balances(exchange_i) > 1e-10
            ):
                raise
            return

        # This is to check that we didn't end up in a borked state after
        # an exchange succeeded
        _deposit = [0] * 2
        _deposit[exchange_i] = (
            10**16
            * 10 ** self.decimals[exchange_i]
            // ([10**18] + INITIAL_PRICES)[exchange_i]
        )
        assert self.swap.calc_token_amount(_deposit, True)

        d_balance = self.coins[exchange_i].balanceOf(user) - d_balance
        d_token = d_token - self.swap.balanceOf(user)

        assert (
            calc_out_amount == d_balance
        ), f"{calc_out_amount} vs {d_balance} for {token_amount}"

        self.balances[exchange_i] -= d_balance
        self.total_supply -= d_token

        # Virtual price resets if everything is withdrawn
        if self.total_supply == 0:
            self.virtual_price = 10**18


def test_numba_go_up(users, coins, swap):
    NumbaGoUp.TestCase.settings = settings(
        max_examples=MAX_SAMPLES,
        stateful_step_count=STEP_COUNT,
        suppress_health_check=list(HealthCheck),
        deadline=None,
    )

    for k, v in locals().items():
        setattr(NumbaGoUp, k, v)

    # because of this hypothesis.event does not work
    run_state_machine_as_test(NumbaGoUp)
