import boa

from tests.utils.tokens import mint_for_testing

god = boa.env.generate_address()


class GodModePool:
    def __init__(self, instance, coins):
        self.instance = instance
        self.coins = coins
        self.plotting = {}
        for c in self.coins:
            c.approve(self.instance, 2**256 - 1, sender=god)

    def __getattr__(self, name):
        return getattr(self.instance, name)

    def donate(self, amounts, update_ema=False):
        self.__premint_amounts(amounts)

        self.instance.donate(amounts, sender=god)

        if update_ema:
            self.__update_ema()

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

    def __premint_amounts(self, amounts):
        for c, amount in zip(self.coins, amounts):
            mint_for_testing(c, god, amount)

    def __update_ema(self):
        boa.env.time_travel(seconds=86400 * 7)