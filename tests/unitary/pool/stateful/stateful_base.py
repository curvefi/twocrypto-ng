import contextlib
from math import log

import boa
from boa.test import strategy
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from tests.fixtures.pool import INITIAL_PRICES
from tests.utils.constants import UNIX_DAY
from tests.utils.tokens import mint_for_testing

MAX_SAMPLES = 20
MAX_D = 10**12 * 10**18  # $1T is hopefully a reasonable cap for tests


class StatefulBase(RuleBasedStateMachine):
    exchange_amount_in = strategy("uint256", max_value=10**9 * 10**18)
    exchange_i = strategy("uint8", max_value=1)
    sleep_time = strategy("uint256", max_value=UNIX_DAY * 7)
    user = strategy("address")

    def __init__(self):

        super().__init__()

        self.decimals = [int(c.decimals()) for c in self.coins]
        self.user_balances = {u: [0] * 2 for u in self.users}
        self.initial_prices = INITIAL_PRICES
        self.initial_deposit = [
            10**4 * 10 ** (18 + d) // p
            for p, d in zip(self.initial_prices, self.decimals)
        ]  # $10k * 2

        self.xcp_profit = 10**18
        self.xcp_profit_a = 10**18

        self.total_supply = 0
        self.previous_pool_profit = 0

        self.swap_admin = self.swap.admin()
        self.fee_receiver = self.swap.fee_receiver()

        for user in self.users:
            for coin in self.coins:
                coin.approve(self.swap, 2**256 - 1, sender=user)

        self.setup()

    def setup(self, user_id=0):

        user = self.users[user_id]
        for coin, q in zip(self.coins, self.initial_deposit):
            mint_for_testing(coin, user, q)

        # Very first deposit
        self.swap.add_liquidity(self.initial_deposit, 0, sender=user)

        self.balances = self.initial_deposit[:]
        self.total_supply = self.swap.balanceOf(user)
        self.xcp_profit = 10**18

    def convert_amounts(self, amounts):
        prices = [10**18] + [self.swap.price_scale()]
        return [
            p * a // 10 ** (36 - d)
            for p, a, d in zip(prices, amounts, self.decimals)
        ]

    def check_limits(self, amounts, D=True, y=True):
        """
        Should be good if within limits, but if outside - can be either
        """
        _D = self.swap.D()
        prices = [10**18] + [self.swap.price_scale()]
        xp_0 = [self.swap.balances(i) for i in range(2)]
        xp = xp_0
        xp_0 = [
            x * p // 10**d for x, p, d in zip(xp_0, prices, self.decimals)
        ]
        xp = [
            (x + a) * p // 10**d
            for a, x, p, d in zip(amounts, xp, prices, self.decimals)
        ]

        if D:
            for _xp in [xp_0, xp]:
                if (
                    (min(_xp) * 10**18 // max(_xp) < 10**14)
                    or (max(_xp) < 10**9 * 10**18)
                    or (max(_xp) > 10**15 * 10**18)
                ):
                    return False

        if y:
            for _xp in [xp_0, xp]:
                if (
                    (_D < 10**17)
                    or (_D > 10**15 * 10**18)
                    or (min(_xp) * 10**18 // _D < 10**16)
                    or (max(_xp) * 10**18 // _D > 10**20)
                ):
                    return False

        return True

    @rule(
        exchange_amount_in=exchange_amount_in,
        exchange_i=exchange_i,
        user=user,
    )
    def exchange(self, exchange_amount_in, exchange_i, user):
        out = self._exchange(exchange_amount_in, exchange_i, user)
        if out:
            self.swap_out = out
            return
        self.swap_out = None

    def _exchange(self, exchange_amount_in, exchange_i, user):
        exchange_j = 1 - exchange_i
        try:
            calc_amount = self.swap.get_dy(
                exchange_i, exchange_j, exchange_amount_in
            )
        except Exception:
            _amounts = [0] * 2
            _amounts[exchange_i] = exchange_amount_in
            if self.check_limits(_amounts) and exchange_amount_in > 10000:
                raise
            return None
        _amounts = [0] * 2
        _amounts[exchange_i] = exchange_amount_in
        _amounts[exchange_j] = -calc_amount
        limits_check = self.check_limits(_amounts)  # If get_D fails
        mint_for_testing(self.coins[exchange_i], user, exchange_amount_in)

        d_balance_i = self.coins[exchange_i].balanceOf(user)
        d_balance_j = self.coins[exchange_j].balanceOf(user)
        try:
            self.coins[exchange_i].approve(
                self.swap, 2**256 - 1, sender=user
            )
            out = self.swap.exchange(
                exchange_i, exchange_j, exchange_amount_in, 0, sender=user
            )
        except Exception:
            # Small amounts may fail with rounding errors
            if (
                calc_amount > 100
                and exchange_amount_in > 100
                and calc_amount / self.swap.balances(exchange_j) > 1e-13
                and exchange_amount_in / self.swap.balances(exchange_i) > 1e-13
                and limits_check
            ):
                raise
            return None

        # This is to check that we didn't end up in a borked state after
        # an exchange succeeded
        self.swap.get_dy(
            exchange_j,
            exchange_i,
            10**16
            * 10 ** self.decimals[exchange_j]
            // INITIAL_PRICES[exchange_j],
        )

        d_balance_i -= self.coins[exchange_i].balanceOf(user)
        d_balance_j -= self.coins[exchange_j].balanceOf(user)

        assert d_balance_i == exchange_amount_in
        assert -d_balance_j == calc_amount, f"{-d_balance_j} vs {calc_amount}"

        self.balances[exchange_i] += d_balance_i
        self.balances[exchange_j] += d_balance_j

        return out

    @rule(sleep_time=sleep_time)
    def sleep(self, sleep_time):
        boa.env.time_travel(sleep_time)

    @invariant()
    def balances(self):
        balances = [self.swap.balances(i) for i in range(2)]
        balances_of = [c.balanceOf(self.swap) for c in self.coins]
        for i in range(2):
            assert self.balances[i] == balances[i]
            assert self.balances[i] == balances_of[i]

    @invariant()
    def total_supply(self):
        assert self.total_supply == self.swap.totalSupply()

    @invariant()
    def virtual_price(self):
        virtual_price = self.swap.virtual_price()
        xcp_profit = self.swap.xcp_profit()
        get_virtual_price = self.swap.get_virtual_price()

        assert xcp_profit >= 10**18 - 10
        assert virtual_price >= 10**18 - 10
        assert get_virtual_price >= 10**18 - 10

        assert (
            xcp_profit - self.xcp_profit > -3
        ), f"{xcp_profit} vs {self.xcp_profit}"
        assert (virtual_price - 10**18) * 2 - (
            xcp_profit - 10**18
        ) >= -5, f"vprice={virtual_price}, xcp_profit={xcp_profit}"
        assert abs(log(virtual_price / get_virtual_price)) < 1e-10

        self.xcp_profit = xcp_profit

    @invariant()
    def up_only_profit(self):

        current_profit = xcp_profit = self.swap.xcp_profit()
        xcp_profit_a = self.swap.xcp_profit_a()
        current_profit = (xcp_profit + xcp_profit_a + 1) // 2

        assert current_profit >= self.previous_pool_profit
        self.previous_pool_profit = current_profit

    @contextlib.contextmanager
    def upkeep_on_claim(self):

        admin_balances_pre = [
            c.balanceOf(self.fee_receiver) for c in self.coins
        ]
        pool_is_ramping = (
            self.swap.future_A_gamma_time() > boa.env.vm.state.timestamp
        )

        try:

            yield

        finally:

            new_xcp_profit_a = self.swap.xcp_profit_a()
            old_xcp_profit_a = self.xcp_profit_a

            claimed = False
            if new_xcp_profit_a > old_xcp_profit_a:
                claimed = True
                self.xcp_profit_a = new_xcp_profit_a

            admin_balances_post = [
                c.balanceOf(self.fee_receiver) for c in self.coins
            ]

            if claimed:

                for i in range(2):
                    claimed_amount = (
                        admin_balances_post[i] - admin_balances_pre[i]
                    )
                    assert (
                        claimed_amount > 0
                    )  # check if non zero amounts of claim
                    assert not pool_is_ramping  # cannot claim while ramping

                    # update self.balances
                    self.balances[i] -= claimed_amount

        self.xcp_profit = self.swap.xcp_profit()
