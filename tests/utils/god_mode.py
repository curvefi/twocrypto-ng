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
        self.god = god
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

    def balances(self, i=None):
        if i is None:
            return [self.instance.balances(j) for j in range(N_COINS)]
        return self.instance.balances(i)

    def xp(self):
        return self.instance.internal._xp(self.balances(), self.instance.price_scale())

    def donate(self, amounts, slippage=0, update_ema=False, sender=god):
        self.premint_amounts(amounts, to=sender)

        shares = self.instance.add_liquidity(
            amounts, slippage, boa.eval("empty(address)"), True, sender=sender
        )

        if update_ema:
            self.__update_ema()

        return shares

    def donate_balanced(self, amount, update_ema=False):
        balanced_amounts = self.compute_balanced_amounts(amount)
        return self.donate(balanced_amounts, update_ema=update_ema)

    def exchange(self, i, dx, update_ema=False, indicate_rebalance=False, sender=god):
        if i == 0:
            amounts = [dx, 0]
        else:
            amounts = [0, dx]
        self.premint_amounts(amounts, to=sender)
        if indicate_rebalance:
            price_scale_pre = self.instance.price_scale()
        dy = self.instance.exchange(i, 1 - i, dx, 0, sender=sender)
        if indicate_rebalance:
            price_scale_post = self.instance.price_scale()
            rebalanced = price_scale_post != price_scale_pre
            print("Rebalance!" if rebalanced else "No rebalance!")

        if update_ema:
            self.__update_ema()

        return dy

    def add_liquidity(self, amounts, update_ema=False, donate=False):
        self.premint_amounts(amounts)
        receiver = boa.eval("empty(address)") if donate else boa.env.eoa

        lp_tokens_received = self.instance.add_liquidity(amounts, 0, receiver, donate, sender=god)

        if update_ema:
            self.__update_ema()

        return lp_tokens_received

    def add_liquidity_balanced(self, amount, update_ema=False, donate=False):
        balanced_amounts = self.compute_balanced_amounts(amount)

        return self.add_liquidity(balanced_amounts, update_ema=update_ema, donate=donate)

    def remove_liquidity(self, lp_token_amount, min_amounts, update_ema=False):
        amounts_received = self.instance.remove_liquidity(lp_token_amount, min_amounts)

        if update_ema:
            self.__update_ema()

        return amounts_received

    def remove_liquidity_one_coin(self, lp_token_amount, i, min_amount, update_ema=False):
        amount_i_received = self.instance.remove_liquidity_one_coin(lp_token_amount, i, min_amount)

        if update_ema:
            self.__update_ema()

        return amount_i_received

    def remove_liquidity_fixed_out(
        self, lp_token_amount, i, amount_i, min_amount_j=0, update_ema=False
    ):
        amount_j_received = self.instance.remove_liquidity_fixed_out(
            lp_token_amount, i, amount_i, min_amount_j
        )

        if update_ema:
            self.__update_ema()

        return amount_j_received

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

    def get_metrics_snapshot(self):
        """Get a snapshot of key pool metrics for tracking"""
        return {
            "virtual_price": self.instance.virtual_price(),
            "xcp_profit": self.instance.xcp_profit(),
            "xcp_profit_a": self.instance.xcp_profit_a(),
            "price_scale": self.instance.price_scale(),
            "price_oracle": self.instance.price_oracle(),
            "total_supply": self.instance.totalSupply(),
            "D": self.instance.D(),
            "coin0_balance": self.instance.balances(0),
            "coin1_balance": self.instance.balances(1),
        }

    def premint_amounts(self, amounts, to=god):
        for c, amount in zip(self.coins, amounts):
            boa.deal(c, to, amount)
            c.approve(self.instance, amount, sender=to)

    def __update_ema(self):
        boa.env.time_travel(seconds=86400 * 7)

    def virtual_price_boosted(self):
        donation_shares = self.instance.internal._donation_shares()
        locked_supply = self.instance.totalSupply() - donation_shares
        if locked_supply == 0:
            return 10**18
        return (
            10**18
            * self.instance.internal._xcp(self.instance.D(), self.instance.price_scale())
            // locked_supply
        )
