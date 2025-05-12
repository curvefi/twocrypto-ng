"""
GodMode™ is a bespoke thin wrapper around twocrypto that reduces
the amount of boilerplate code needed to write meaningful tests.
"""

import boa
from tests.utils.constants import N_COINS, ERC20_DEPLOYER

god = boa.env.generate_address()


class GodModePool:
    def __init__(self, instance):
        self.instance = instance
        self.coins = [ERC20_DEPLOYER.at(instance.coins(i)) for i in range(N_COINS)]
        for c in self.coins:
            c.approve(self.instance, 2**256 - 1, sender=god)

    def compute_balanced_amounts(self, amount):
        return [amount, amount * 10**18 // self.instance.price_scale()]

    def __getattr__(self, name):
        return getattr(self.instance, name)

    def coins(self, i=None):
        if i is None:
            return self.coins
        return self.coins[i]

    def donate(self, amounts, slippage=0, update_ema=False):
        self.__premint_amounts(amounts)

        self.instance.donate(amounts, slippage, sender=god)

        if update_ema:
            self.__update_ema()

    def donate_balanced(self, amount, update_ema=False):
        balanced_amounts = self.compute_balanced_amounts(amount)

        return self.donate(balanced_amounts, update_ema=update_ema)

    def exchange(self, i, dx, update_ema=False, indicate_rebalance=False):
        if i == 0:
            amounts = [dx, 0]
        else:
            amounts = [0, dx]
        self.__premint_amounts(amounts)
        if indicate_rebalance:
            price_scale_pre = self.instance.price_scale()
        dy = self.instance.exchange(i, 1 - i, dx, 0, sender=god)
        if indicate_rebalance:
            price_scale_post = self.instance.price_scale()
            rebalanced = price_scale_post != price_scale_pre
            print("Rebalance!" if rebalanced else "No rebalance!")

        if update_ema:
            self.__update_ema()

        return dy

    def add_liquidity(self, amounts, update_ema=False, donate=False):
        self.__premint_amounts(amounts)

        lp_tokens_received = self.instance.add_liquidity(
            amounts, 0, boa.env.eoa, donate, sender=god
        )

        if update_ema:
            self.__update_ema()

        return lp_tokens_received

    def add_liquidity_balanced(self, amount, update_ema=False, donate=False):
        balanced_amounts = self.compute_balanced_amounts(amount)

        return self.add_liquidity(balanced_amounts, update_ema=update_ema, donate=donate)

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
