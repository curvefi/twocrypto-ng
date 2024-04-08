import boa
from boa.test import strategy
from hypothesis.stateful import invariant, rule, run_state_machine_as_test

from tests.unitary.pool.stateful.stateful_base import StatefulBase
from tests.utils import approx
from tests.utils import simulation_int_many as sim
from tests.utils.tokens import mint_for_testing

MAX_SAMPLES = 20
STEP_COUNT = 100


class StatefulSimulation(StatefulBase):
    exchange_amount_in = strategy(
        "uint256", min_value=10**17, max_value=10**5 * 10**18
    )
    exchange_i = strategy("uint8", max_value=1)
    user = strategy("address")

    def setup(self):

        super().setup()

        for u in self.users[1:]:
            for coin, q in zip(self.coins, self.initial_deposit):
                mint_for_testing(coin, u, q)
            for i in range(2):
                self.balances[i] += self.initial_deposit[i]
            self.swap.add_liquidity(self.initial_deposit, 0, sender=u)
            self.total_supply += self.swap.balanceOf(u)

        self.virtual_price = self.swap.get_virtual_price()

        self.trader = sim.Trader(
            self.swap.A(),
            self.swap.gamma(),
            self.swap.D(),
            2,
            [10**18, self.swap.price_scale()],
            self.swap.mid_fee() / 1e10,
            self.swap.out_fee() / 1e10,
            self.swap.allowed_extra_profit(),
            self.swap.fee_gamma(),
            self.swap.adjustment_step() / 1e18,
            int(
                self.swap.ma_time() / 0.693
            ),  # crypto swap returns ma time in sec
        )
        for i in range(2):
            self.trader.curve.x[i] = self.swap.balances(i)

        # Adjust virtual prices
        self.trader.xcp_profit = self.swap.xcp_profit()
        self.trader.xcp_profit_real = self.swap.virtual_price()
        self.trader.t = boa.env.vm.state.timestamp
        self.swap_no = 0

    @rule(
        exchange_amount_in=exchange_amount_in,
        exchange_i=exchange_i,
        user=user,
    )
    def exchange(self, exchange_amount_in, exchange_i, user):

        dx = (
            exchange_amount_in
            * 10**18
            // self.trader.price_oracle[exchange_i]
        )
        self.swap_no += 1
        super().exchange(dx, exchange_i, user)

        if not self.swap_out:
            return  # if swap breaks, dont check.

        dy_trader = self.trader.buy(dx, exchange_i, 1 - exchange_i)
        self.trader.tweak_price(boa.env.vm.state.timestamp)

        # exchange checks:
        assert approx(self.swap_out, dy_trader, 1e-3)
        assert approx(
            self.swap.price_oracle(), self.trader.price_oracle[1], 1.5e-3
        )

        boa.env.time_travel(12)

    @invariant()
    def simulator(self):
        if self.trader.xcp_profit / 1e18 - 1 > 1e-8:
            assert (
                abs(self.trader.xcp_profit - self.swap.xcp_profit())
                / (self.trader.xcp_profit - 10**18)
                < 0.05
            )

        price_scale = self.swap.price_scale()
        price_trader = self.trader.curve.p[1]
        try:
            assert approx(price_scale, price_trader, 1e-3)
        except Exception:
            if self.check_limits([0, 0, 0]):
                assert False


def test_sim(users, coins, swap):
    from hypothesis import settings
    from hypothesis._settings import HealthCheck

    StatefulSimulation.TestCase.settings = settings(
        max_examples=MAX_SAMPLES,
        stateful_step_count=STEP_COUNT,
        suppress_health_check=HealthCheck.all(),
        deadline=None,
    )

    for k, v in locals().items():
        setattr(StatefulSimulation, k, v)

    run_state_machine_as_test(StatefulSimulation)
