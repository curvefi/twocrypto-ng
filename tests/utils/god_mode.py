"""
GodMode™ is a bespoke thin wrapper around twocrypto that reduces
the amount of boilerplate code needed to write meaningful tests.
"""

import boa
from tests.utils.constants import N_COINS

god = boa.env.generate_address()


class GodModePool:
    def __init__(self, instance, coins):
        self.instance = instance
        self.coins = coins
        for c in self.coins:
            c.approve(self.instance, 2**256 - 1, sender=god)

    def __getattr__(self, name):
        return getattr(self.instance, name)

    def exchange(self, i, dx, update_ema=False):
        if i == 0:
            amounts = [dx, 0]
        else:
            amounts = [0, dx]
        self.__premint_amounts(amounts)

        dy = self.instance.exchange(i, 1 - i, dx, 0, sender=god)

        if update_ema:
            self.__update_ema()

        return dy

    def add_liquidity(self, amounts, update_ema=False):
        self.__premint_amounts(amounts)

        lp_tokens_received = self.instance.add_liquidity(amounts, 0, boa.env.eoa, sender=god)

        if update_ema:
            self.__update_ema()

        return lp_tokens_received

    def add_liquidity_balanced(self, amount, update_ema=False):
        balanced_amounts = [amount, amount * 10**18 // self.instance.price_scale()]

        return self.add_liquidity(balanced_amounts, update_ema=update_ema)

    def balances_snapshot(self):
        snapshot = {
            "user_lp": self.instance.balanceOf(boa.env.eoa),
            "lp_supply": self.instance.totalSupply(),
            "user_coins": [self.coins[i].balanceOf(boa.env.eoa) for i in range(N_COINS)],
            "pool_coins": [self.instance.balances(i) for i in range(N_COINS)],
        }
        assert snapshot["pool_coins"] == [
            self.coins[i].balanceOf(self.instance) for i in range(N_COINS)
        ], "pool coins balances are not consistent"
        return snapshot

    def __premint_amounts(self, amounts):
        for c, amount in zip(self.coins, amounts):
            boa.deal(c, god, amount)

    def __update_ema(self):
        boa.env.time_travel(seconds=86400 * 7)
