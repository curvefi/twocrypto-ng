import boa
from boa.test import strategy
from hypothesis import HealthCheck, settings
from hypothesis.stateful import rule, run_state_machine_as_test

from tests.fixtures.pool import INITIAL_PRICES
from tests.unitary.pool.stateful.stateful_base import StatefulBase
from tests.utils.tokens import mint_for_testing

MAX_SAMPLES = 20
STEP_COUNT = 100
MAX_D = 10**12 * 10**18  # $1T is hopefully a reasonable cap for tests


class NumbaGoUp(StatefulBase):
    """
    Test that profit goes up
    """

    user = strategy("address")
    exchange_i = strategy("uint8", max_value=1)
    deposit_amounts = strategy(
        "uint256[2]", min_value=0, max_value=10**9 * 10**18
    )
    token_amount = strategy("uint256", max_value=10**12 * 10**18)
    check_out_amount = strategy("bool")

    @rule(deposit_amounts=deposit_amounts, user=user)
    def deposit(self, deposit_amounts, user):

        if self.swap.D() > MAX_D:
            return

        amounts = self.convert_amounts(deposit_amounts)
        if sum(amounts) == 0:
            return

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
            return

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

    @rule(token_amount=token_amount, user=user)
    def remove_liquidity(self, token_amount, user):
        if self.swap.balanceOf(user) < token_amount or token_amount == 0:
            with boa.reverts():
                self.swap.remove_liquidity(token_amount, [0] * 2, sender=user)
        else:
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

    @rule(
        token_amount=token_amount,
        exchange_i=exchange_i,
        user=user,
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

    run_state_machine_as_test(NumbaGoUp)
