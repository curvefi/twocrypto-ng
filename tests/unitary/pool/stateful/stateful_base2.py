from typing import List

import boa
from hypothesis import event, note
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    rule,
)
from hypothesis.strategies import integers
from strategies import address
from strategies import pool as pool_strategy

from contracts.mocks import ERC20Mock as ERC20
from tests.utils.constants import UNIX_DAY
from tests.utils.tokens import mint_for_testing


class StatefulBase(RuleBasedStateMachine):
    # try bigger amounts than 30 and e11 for low
    @initialize(
        pool=pool_strategy(),
        # TODO deposits can be as low as 1e11, but small deposits breaks swaps
        # I should do stateful testing only with deposit withdrawal
        amount=integers(min_value=int(1e20), max_value=int(1e30)),
        user=address,
    )
    def initialize_pool(self, pool, amount, user):
        # cahing the pool generated by the strategy
        self.pool = pool

        # total supply of lp tokens (updated from reported balances)
        self.total_supply = 0

        # caching coins here for easier access
        self.coins = [ERC20.at(pool.coins(i)) for i in range(2)]

        # these balances should follow the pool balances
        self.balances = [0, 0]

        # initial profit is 1e18
        self.xcp_profit = 1e18
        self.xcp_profit_a = 1e18
        self.xcpx = 1e18

        self.depositors = set()

        # deposit some initial liquidity
        balanced_amounts = self.get_balanced_deposit_amounts(amount)
        note(
            "seeding pool with balanced amounts: {:.2e} {:.2e}".format(
                *balanced_amounts
            )
        )
        self.add_liquidity(balanced_amounts, user)

    # --------------- utility methods ---------------

    def get_balanced_deposit_amounts(self, amount: int):
        """Get the amounts of tokens that should be deposited
        to the pool to have balanced amounts of the two tokens.

        Args:
            amount (int): the amount of the first token

        Returns:
            List[int]: the amounts of the two tokens
        """
        return [int(amount), int(amount * 1e18 // self.pool.price_scale())]

    # --------------- pool methods ---------------
    # methods that wrap the pool methods that should be used in
    # the rules of the state machine. These methods make sure that
    # both the state of the pool and of the state machine are
    # updated together. Calling pool methods directly will probably
    # lead to incorrect simulation and errors.

    def add_liquidity(self, amounts: List[int], user: str):
        """Wrapper around the `add_liquidity` method of the pool.
        Always prefer this instead of calling the pool method directly.

        Args:
            amounts (List[int]): amounts of tokens to be deposited
            user (str): the sender of the transaction

        Returns:
            str: the address of the depositor
        """
        # check to prevent revert on empty deposits
        if sum(amounts) == 0:
            event("empty deposit")
            return

        for coin, amount in zip(self.coins, amounts):
            # infinite approval
            coin.approve(self.pool, 2**256 - 1, sender=user)
            # mint the amount of tokens for the depositor
            mint_for_testing(coin, user, amount)

        # store the amount of lp tokens before the deposit
        lp_tokens = self.pool.balanceOf(user)

        # TODO stricter since no slippage
        self.pool.add_liquidity(amounts, 0, sender=user)

        # find the increase in lp tokens
        lp_tokens = self.pool.balanceOf(user) - lp_tokens
        # increase the total supply by the amount of lp tokens
        self.total_supply += lp_tokens

        # pool balances should increase by the amounts
        self.balances = [x + y for x, y in zip(self.balances, amounts)]

        # update the profit since it increases through `tweak_price`
        # which is called by `add_liquidity`
        self.xcp_profit = self.pool.xcp_profit()
        self.xcp_profit_a = self.pool.xcp_profit_a()

        self.depositors.add(user)

    def exchange(self, dx: int, i: int, user: str):
        """Wrapper around the `exchange` method of the pool.
        Always prefer this instead of calling the pool method directly.

        Args:
            dx (int): amount in
            i (int): the token the user sends to swap
            user (str): the sender of the transaction
        """
        # j is the index of the coin that comes out of the pool
        j = 1 - i

        mint_for_testing(self.coins[i], user, dx)
        self.coins[i].approve(self.pool.address, dx, sender=user)

        delta_balance_i = self.coins[i].balanceOf(user)
        delta_balance_j = self.coins[j].balanceOf(user)

        expected_dy = self.pool.get_dy(i, j, dx)

        actual_dy = self.pool.exchange(i, j, dx, expected_dy, sender=user)

        delta_balance_i = self.coins[i].balanceOf(user) - delta_balance_i
        delta_balance_j = self.coins[j].balanceOf(user) - delta_balance_j

        assert -delta_balance_i == dx
        assert delta_balance_j == expected_dy == actual_dy

        self.balances[i] -= delta_balance_i
        self.balances[j] -= delta_balance_j

        self.xcp_profit = self.pool.xcp_profit()

        note(
            "exchanged {:.2e} of token {} for {:.2e} of token {}".format(
                dx, i, actual_dy, j
            )
        )

    def remove_liquidity(self, amount, user):
        amounts = [c.balanceOf(user) for c in self.coins]
        tokens = self.swap.balanceOf(user)
        self.pool.remove_liquidity(amount, [0] * 2, sender=user)
        amounts = [
            (c.balanceOf(user) - a) for c, a in zip(self.coins, amounts)
        ]
        self.total_supply -= tokens
        tokens -= self.swap.balanceOf(user)
        self.balances = [b - a for a, b in zip(amounts, self.balances)]

        # virtual price resets if everything is withdrawn
        if self.total_supply == 0:
            event("full liquidity removal")
            self.virtual_price = 1e18

    def remove_liquidity_one_coin(self, percentage):
        pass

    @rule(time_increase=integers(min_value=1, max_value=UNIX_DAY * 7))
    def time_forward(self, time_increase):
        """Make the time moves forward by `sleep_time` seconds.
        Useful for ramping, oracle updates, etc.
        Up to 1 week.
        """
        boa.env.time_travel(time_increase)

    # --------------- pool invariants ----------------------

    @invariant()
    def newton_y_converges(self):
        """We use get_dy with a small amount to check if the newton_y
        still manages to find the correct value. If this is not the case
        the pool is broken and it can't execute swaps anymore.
        """
        ARBITRARY_SMALL_AMOUNT = int(1e15)
        try:
            self.pool.get_dy(0, 1, ARBITRARY_SMALL_AMOUNT)
            try:
                self.pool.get_dy(1, 0, ARBITRARY_SMALL_AMOUNT)
            except Exception:
                raise AssertionError("newton_y is broken")
        except Exception:
            pass

    @invariant()
    def can_always_withdraw(self):
        """Make sure that newton_D always works when withdrawing liquidity.
        No matter how imbalanced the pool is, it should always be possible
        to withdraw liquidity in a proportional way.
        """

        # anchor the environment to make sure that the balances are
        # restored after the invariant is checked
        with boa.env.anchor():
            # remove all liquidity from all depositors
            for d in self.depositors:
                # store the current balances of the pool
                prev_balances = [c.balanceOf(self.pool) for c in self.coins]
                # withdraw all liquidity from the depositor
                tokens = self.pool.balanceOf(d)
                self.pool.remove_liquidity(tokens, [0] * 2, sender=d)
                # assert current balances are less as the previous ones
                for c, b in zip(self.coins, prev_balances):
                    # check that the balance of the pool is less than before
                    assert c.balanceOf(self.pool) < b
            for c in self.coins:
                # there should not be any liquidity left in the pool
                assert c.balanceOf(self.pool) == 0

    @invariant()
    def balances(self):
        balances = [self.pool.balances(i) for i in range(2)]
        balances_of = [c.balanceOf(self.pool) for c in self.coins]
        for i in range(2):
            assert self.balances[i] == balances[i]
            assert self.balances[i] == balances_of[i]

    @invariant()
    def sanity_check(self):
        """Make sure the stateful simulations matches the contract state."""
        assert self.xcp_profit == self.pool.xcp_profit()
        assert self.total_supply == self.pool.totalSupply()

        # profit, cached vp and current vp should be at least 1e18
        assert self.xcp_profit >= 1e18
        assert self.pool.virtual_price() >= 1e18
        assert self.pool.get_virtual_price() >= 1e18

        for d in self.depositors:
            assert self.pool.balanceOf(d) > 0

    @invariant()
    def virtual_price(self):
        pass  # TODO

    @invariant()
    def up_only_profit(self):
        """This method checks if the pool is profitable, since it should
        never lose money.

        To do so we use the so called `xcpx`. This is an emprical measure
        of profit that is even stronger than `xcp`. We have to use this
        because `xcp` goes down when claiming admin fees.

        You can imagine `xcpx` as a value that that is always between the
        interval [xcp_profit, xcp_profit_a]. When `xcp` goes down
        when claiming fees, `xcp_a` goes up. Averaging them creates this
        measure of profit that only goes down when something went wrong.
        """
        xcp_profit = self.pool.xcp_profit()
        xcp_profit_a = self.pool.xcp_profit_a()
        xcpx = (xcp_profit + xcp_profit_a + 1e18) // 2

        # make sure that the previous profit is smaller than the current
        assert xcpx >= self.xcpx
        # updates the previous profit
        self.xcpx = xcpx
        self.xcp_profit = xcp_profit
        self.xcp_profit_a = xcp_profit_a


TestBase = StatefulBase.TestCase

# TODO make sure that xcp goes down when claiming admin fees
# TODO add an invariant with withdrawal simulations to make sure
# it is always possible