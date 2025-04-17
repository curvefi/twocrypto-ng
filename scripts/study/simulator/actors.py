import logging
import boa
from tests.utils.constants import N_COINS
from pool import WAD

logger = logging.getLogger(__name__)


class PoolActor:
    """
    Base class for all actors interacting with the pool (LP, Trader, Admin)
    Manages token balances, approvals, and value calculations
    """

    def __init__(self, pool, name=None, initial_amounts=None, address=None):
        # pool is always a Pool wrapper instance
        self.pool = pool
        self.instance = pool.instance
        self.coins = pool.coins
        self.address = address or boa.env.generate_address()
        self.name = name or self.__class__.__name__
        self.initial_amounts = initial_amounts or [0] * N_COINS
        for i, amount in enumerate(self.initial_amounts):
            if amount > 0:
                boa.deal(self.coins[i], self.address, amount)
        self.approve()
        self.lp_tokens = 0

    def approve(self):
        for coin in self.coins:
            coin.approve(self.instance.address, 2**256 - 1, sender=self.address)

    def balances(self):
        return [coin.balanceOf(self.address) for coin in self.coins]

    def value(self, price_scale=None):
        if price_scale is None:
            price_scale = self.pool.price_scale()
        bals = self.balances()
        return bals[0] + bals[1] * price_scale // WAD

    def mint(self, amounts):
        for i, amount in enumerate(amounts):
            if amount > 0:
                boa.deal(self.coins[i], self.address, amount)

    def snapshot(self):
        bals = self.balances()
        vals = [bals[0], bals[1] * self.pool.price_scale() // WAD]
        return dict(balances=bals, values=vals, total_value=sum(vals))

    def snapshot_normalized(self):
        snapshot = self.snapshot()
        snapshot["balances"] = [b / WAD for b in snapshot["balances"]]
        snapshot["values"] = [v / WAD for v in snapshot["values"]]
        snapshot["total_value"] = snapshot["total_value"] / WAD
        return snapshot


class LP(PoolActor):
    def __init__(self, pool, name=None, initial_amounts=None):
        super().__init__(pool, name=name, initial_amounts=initial_amounts)

    def add_liquidity(self, amounts=None):
        if not amounts:
            amounts = self.balances()
        lp_before = self.instance.balanceOf(self.address)
        self.instance.add_liquidity(amounts, 0, self.address, sender=self.address)
        lp_after = self.instance.balanceOf(self.address)
        self.lp_tokens = lp_after
        return lp_after - lp_before

    def remove_liquidity(self, amount=None):
        current_lp = self.instance.balanceOf(self.address)
        if amount is None:
            amount = current_lp
        if amount <= 0 or current_lp == 0:
            logger.warning(f"{self.name} has no liquidity to remove.")
            return [0, 0]
        if amount > current_lp:
            logger.warning(
                f"Warning: {self.name} trying to remove {amount/1e18:.4f} LP, but only has {current_lp/1e18:.4f}. Removing all."
            )
            amount = current_lp
        balances_before = self.balances()
        self.instance.remove_liquidity(amount, [0, 0], self.address, sender=self.address)
        self.lp_tokens = self.instance.balanceOf(self.address)
        balances_after = self.balances()
        received = [balances_after[i] - balances_before[i] for i in range(N_COINS)]
        return received


class Trader(PoolActor):
    def __init__(self, pool, name=None, initial_amounts=None):
        super().__init__(pool, name=name, initial_amounts=initial_amounts)
        self.volume_traded = 0

    def trade(self, i, dx, update_ema=False):
        j = 1 - i
        if self.balances()[i] < dx:
            self.mint([dx if idx == i else 0 for idx in range(N_COINS)])
        dy = self.instance.exchange(i, j, dx, 0, self.address, sender=self.address)
        if update_ema:
            boa.env.time_travel(seconds=86400 * 7)
        return dy

    def balance_pool(self, precision=0.0001, update_ema=False, max_iterations=50):
        logger.info("Balancing pool...")
        iteration = 0
        val_rate = 0
        while iteration < max_iterations:
            price_oracle = self.instance.price_oracle()
            if price_oracle == 0:
                logger.warning("Warning: Price oracle is zero, cannot balance.")
                break
            bal0 = self.instance.balances(0)
            bal1 = self.instance.balances(1)
            if bal1 == 0:
                logger.warning("Warning: Pool balance 1 is zero, cannot calculate value rate.")
                break
            val_rate = bal0 * 10**18 / (price_oracle * bal1)
            if abs(val_rate - 1) <= precision:
                logger.info(
                    f"Pool balanced after {iteration} iterations. Value ratio: {val_rate:.4f}"
                )
                break
            larger_coin = 0 if val_rate > 1 else 1
            smaller_coin = 1 - larger_coin
            trade_back_size = int(self.instance.balances(smaller_coin) * (abs(val_rate - 1) / 2))
            if trade_back_size < 1000:
                logger.info("Trade size too small, pool is effectively balanced")
                break
            self.trade(smaller_coin, trade_back_size, update_ema=update_ema)
            if smaller_coin:
                self.volume_traded += trade_back_size * self.instance.price_scale() // 10**18
            else:
                self.volume_traded += trade_back_size
            iteration += 1
        return val_rate

    def wash(
        self,
        fee_pct=0.1,
        price_shift=0.05,
        trade_size=10_000 * 10**18,
        balance_precision=1e-7,
        max_trades=100,
        # fee_pct: 0.1 = 10%, price_shift: 0.05 = 5%
        # trade_size: 10_000 = 10_000 units of coin 0, balance_precision: 0.001 = 0.1%
        # max_trades: 100 = maximum number of trades to perform
        # balance_precision: 0.001 = 0.1% of the pool value
        # max_trades: 100 = maximum number of trades to perform
    ):
        price_scale = self.instance.price_scale()
        pool_value_init = (
            self.instance.balances(0) + self.instance.balances(1) * price_scale // 10**18
        )
        target_fees = int(pool_value_init * fee_pct)
        logger.info(
            f"Initial pool value: {pool_value_init/1e18:.2f}, target fees: {target_fees/1e18:.2f}"
        )
        fees_accrued = 0
        trades_count = 0
        volume_traded = 0
        while fees_accrued < target_fees and trades_count < max_trades:
            value_before = (
                self.instance.balances(0)
                + self.instance.balances(1) * self.instance.price_scale() // 10**18
            )
            current_trade_size = min(trade_size, self.balances()[0])
            out = self.trade(0, current_trade_size, update_ema=False)
            self.trade(1, out, update_ema=False)

            volume_traded += current_trade_size + out * self.instance.price_scale() // 10**18

            value_after = (
                self.instance.balances(0)
                + self.instance.balances(1) * self.instance.price_scale() // 10**18
            )
            new_fees = max(0, value_after - value_before)
            fees_accrued += new_fees
            trades_count += 1
            if trades_count % 10 == 0:
                logger.info(
                    f"Trades: {trades_count}, Fees accrued: {fees_accrued/1e18:.4f}/{target_fees/1e18:.4f}"
                )
        logger.info(
            f"Fee accrual complete: {trades_count} trades, {fees_accrued/1e18:.4f} fees accrued"
        )
        logger.info("Balancing pool...")
        self.balance_pool(precision=0.01, update_ema=False)
        if abs(price_shift) > 0.0001:
            logger.info(f"Shifting price by {price_shift*100:.1f}%")
            initial_price_scale = self.instance.price_scale()
            target_price_scale = int(initial_price_scale * (1 + price_shift))
            trade_direction = 0 if price_shift > 0 else 1
            attempts = 0
            while attempts < max_trades:
                boa.env.time_travel(seconds=86400 * 7)
                current_price_scale = self.instance.price_scale()
                price_diff = current_price_scale - target_price_scale
                price_diff_pct = abs(price_diff) / target_price_scale
                logger.debug(
                    f"Current price scale: {current_price_scale/1e18:.6f}"
                    f", Target price scale: {target_price_scale/1e18:.6f}"
                    f", Price diff: {price_diff_pct:.6f}"
                )

                if (
                    price_diff_pct < 0.001
                    or (price_diff > 0 and trade_direction == 0)
                    or (price_diff < 0 and trade_direction == 1)
                ):
                    break

                trade_size = int(
                    min(
                        self.balances()[trade_direction],
                        self.instance.balances(trade_direction) // 10,
                    )
                )
                out = self.trade(trade_direction, trade_size, update_ema=True)
                self.trade(1 - trade_direction, int(0.9 * out), update_ema=True)
                self.volume_traded += trade_size + out * self.instance.price_scale() // 10**18

                attempts += 1
            logger.info(
                f"Price shift complete. Final price scale: {self.instance.price_scale()/1e18:.6f}"
            )
        self.balance_pool(precision=balance_precision, update_ema=False)
        return self.volume_traded


class Admin(PoolActor):
    def __init__(self, pool, name=None, initial_amounts=None):
        admin_address = pool.instance.fee_receiver()
        super().__init__(pool, name=name, initial_amounts=initial_amounts, address=admin_address)

    def claim_fees(self):
        fee_receiver_addr = self.instance.fee_receiver()
        receiver_balances_before = [coin.balanceOf(fee_receiver_addr) for coin in self.coins]
        self.instance.internal._claim_admin_fees()
        receiver_balances_after = [coin.balanceOf(fee_receiver_addr) for coin in self.coins]
        claimed = [receiver_balances_after[i] - receiver_balances_before[i] for i in range(N_COINS)]
        logger.info(f"Admin fees claimed: {claimed[0]/1e18:.4f}, {claimed[1]/1e18:.4f}")
        return claimed
