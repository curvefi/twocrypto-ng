import pytest
import boa
from hypothesis import note, settings
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule
from hypothesis.strategies import integers, sampled_from

from tests.unitary.factory.test_deploy_pool import ZERO_ADDRESS
from tests.utils.constants import (
    ERC20_DEPLOYER,
    FACTORY_DEPLOYER,
    MAX_A,
    MAX_GAMMA,
    MIN_A,
    MIN_GAMMA,
    UNIX_DAY,
    VENOM_FLAG,
)
from tests.utils.strategies import pool_from_preset
from tests.utils.pool_presets import all_presets

LP_ORACLE_DEPLOYER = boa.load_partial(
    "contracts/main/LPOracle.vy", compiler_args={"experimental_codegen": VENOM_FLAG}
)

FIXED_USERS = [boa.env.generate_address() for _ in range(3)]
FRACTION_DENOM = 10_000
INITIAL_FUNDS = 10**45


class LPOracleRampingStateful(RuleBasedStateMachine):
    """LPOracle checks with lightweight rules for swap/add/remove/donate/ramp."""

    change_steps = [x / 10 if x < 10 else x for x in range(2, 11)] + list(range(2, 11))

    @initialize(
        pool=pool_from_preset(
            preset=sampled_from(
                [{**p, "ma_exp_time": 87} for p in all_presets]
            )  # price_oracle = last_price
        ),
        amount=integers(min_value=int(1e20), max_value=int(1e30)),
    )
    def initialize_pool(self, pool, amount):
        self.pool = pool
        self.coins = [ERC20_DEPLOYER.at(pool.coins(i)) for i in range(2)]
        self.decimals = [c.decimals() for c in self.coins]
        self.admin = FACTORY_DEPLOYER.at(pool.factory()).admin()
        self.lp_oracle = LP_ORACLE_DEPLOYER.deploy()

        # Pre-fund all fixed users and set infinite approvals once.
        for user in FIXED_USERS + [ZERO_ADDRESS]:
            for coin in self.coins:
                boa.deal(coin, user, INITIAL_FUNDS)
                coin.approve(self.pool, 2**256 - 1, sender=user)

        # Seed pool with one balanced deposit.
        initial_amounts = self._balanced_amounts(amount)
        self.pool.add_liquidity(initial_amounts, 0, FIXED_USERS[0], False, sender=FIXED_USERS[0])
        note("seeded pool with balanced deposit")

    @staticmethod
    def _err_msg(exc: boa.BoaError) -> str:
        if getattr(exc, "stack_trace", None):
            return str(exc.stack_trace[0])
        return str(exc)

    def _correct_decimals(self, amount: int, coin_idx: int) -> int:
        if self.decimals[coin_idx] == 18:
            return amount
        corrected = amount // (10 ** (18 - self.decimals[coin_idx]))
        return max(corrected, 1) if amount > 0 else 0

    def _balanced_amounts(self, amount0_18: int) -> list[int]:
        amount1_18 = amount0_18 * 10**18 // self.pool.price_scale()
        return [
            self._correct_decimals(amount0_18, 0),
            self._correct_decimals(amount1_18, 1),
        ]

    def is_ramping(self) -> bool:
        return self.pool.future_A_gamma_time() > self.pool.last_timestamp()

    @rule(
        i=integers(min_value=0, max_value=1),
        user=sampled_from(FIXED_USERS),
        fraction=integers(min_value=1, max_value=5_000),  # up to 50% of liquidity
    )
    def exchange_rule(self, i: int, user: str, fraction: int):
        note("[EXCHANGE]")
        liquidity = self.coins[i].balanceOf(self.pool)
        user_balance = self.coins[i].balanceOf(user)
        target_dx = liquidity * fraction // FRACTION_DENOM
        max_dx = min(max(1, target_dx), user_balance)
        if max_dx < 1:
            note("[EXCHANGE][SKIP] no available balance/liquidity")
            return

        dx = max_dx
        j = 1 - i

        try:
            expected_dy = self.pool.get_dy(i, j, dx)
            self.pool.exchange(i, j, dx, 0, sender=user)
            note(f"[EXCHANGE][SUCCESS] dx={dx} dy≈{expected_dy}")
        except boa.BoaError as exc:
            err = self._err_msg(exc)
            if any(msg in err for msg in ("unsafe value for y", "unsafe values x[i]")):
                note("[EXCHANGE][ALLOWED FAILURE]")
                return
            raise

    @precondition(lambda self: self.pool.D() < 1e28)
    @rule(fraction=integers(min_value=1, max_value=2_000), user=sampled_from(FIXED_USERS))
    def add_liquidity_balanced_rule(self, fraction: int, user: str):
        note("[ADD_LIQUIDITY]")
        amounts = [
            max(1, self.pool.balances(0) * fraction // FRACTION_DENOM),
            max(1, self.pool.balances(1) * fraction // FRACTION_DENOM),
        ]
        if any(self.coins[i].balanceOf(user) < amounts[i] for i in range(2)):
            note("[ADD_LIQUIDITY][SKIP] insufficient user balance")
            return

        try:
            minted = self.pool.add_liquidity(amounts, 0, user, False, sender=user)
            note(f"[ADD_LIQUIDITY][SUCCESS] minted={minted}")
        except boa.BoaError as exc:
            err = self._err_msg(exc)
            if any(
                msg in err for msg in ("unsafe value for y", "unsafe values x[i]", "nothing minted")
            ):
                note("[ADD_LIQUIDITY][ALLOWED FAILURE]")
                return
            raise

    @precondition(lambda self: self.pool.totalSupply() > 10e20)
    @rule(user=sampled_from(FIXED_USERS), fraction=integers(min_value=500, max_value=10_000))
    def remove_liquidity_balanced_rule(self, user: str, fraction: int):
        note("[REMOVE_LIQUIDITY]")
        balance = self.pool.balanceOf(user)
        if balance <= 1:
            note("[REMOVE_LIQUIDITY][SKIP] low lp balance")
            return
        amount = max(1, balance * fraction // FRACTION_DENOM)
        amount = min(amount, balance)
        try:
            self.pool.remove_liquidity(amount, [0, 0], sender=user)
            note("[REMOVE_LIQUIDITY][SUCCESS]")
        except boa.BoaError as exc:
            err = self._err_msg(exc)
            if any(msg in err for msg in ("!amount", "!owner", "insufficient allowance")):
                note("[REMOVE_LIQUIDITY][ALLOWED FAILURE]")
                return
            raise

    @precondition(lambda self: self.pool.D() < 1e28)
    @rule(
        amount=integers(min_value=int(1e20), max_value=int(1e25)),
        imbalance_ratio=integers(min_value=0, max_value=FRACTION_DENOM),
    )
    def donate_rule(self, amount: int, imbalance_ratio: int):
        note("[DONATE]")
        max_adjust_steps = 25
        adjusted = False
        below_cap = False

        while not below_cap and max_adjust_steps > 0:
            balanced = self._balanced_amounts(amount)
            amounts = [
                balanced[0] * imbalance_ratio // FRACTION_DENOM,
                balanced[1] * (FRACTION_DENOM - imbalance_ratio) // FRACTION_DENOM,
            ]

            if amounts[0] + amounts[1] == 0:
                note("[DONATE][SKIP] zero amounts")
                return

            token_out = self.pool.calc_token_amount(amounts, True)
            below_cap = (
                token_out
                < (token_out + self.pool.totalSupply())
                * self.pool.donation_shares_max_ratio()
                // 10**18
            )
            if not below_cap:
                amount = max(1, amount * 9 // 10)
                adjusted = True
                max_adjust_steps -= 1

        if not below_cap:
            note("[DONATE][ALLOWED FAILURE] unable to fit cap")
            return

        if any(self.coins[i].balanceOf(ZERO_ADDRESS) < amounts[i] for i in range(2)):
            note("[DONATE][SKIP] insufficient ZERO_ADDRESS balance")
            return

        try:
            minted = self.pool.add_liquidity(amounts, 0, ZERO_ADDRESS, True, sender=ZERO_ADDRESS)
            if adjusted:
                note("[DONATE] adjusted for donation cap")
            note(f"[DONATE][SUCCESS] minted={minted}")
        except boa.BoaError as exc:
            err = self._err_msg(exc)
            if any(
                msg in err
                for msg in (
                    "donation above cap!",
                    "unsafe value for y",
                    "unsafe values x[i]",
                    "nothing minted",
                )
            ):
                note("[DONATE][ALLOWED FAILURE]")
                return
            raise

    @precondition(lambda self: not self.is_ramping())
    @rule(
        A_change=sampled_from(change_steps),
        gamma_change=sampled_from(change_steps),
        days=integers(min_value=1, max_value=365),
    )
    def ramp_rule(self, A_change, gamma_change, days):
        note("[RAMP]")
        new_A = int(max(MIN_A, min(MAX_A, self.pool.A() * A_change)))
        new_gamma = int(max(MIN_GAMMA, min(MAX_GAMMA, self.pool.gamma() * gamma_change)))
        ramp_end_ts = boa.env.evm.patch.timestamp + days * UNIX_DAY
        try:
            self.pool.ramp_A_gamma(new_A, new_gamma, ramp_end_ts, sender=self.admin)
            note("[RAMP][SUCCESS]")
        except boa.BoaError as exc:
            err = self._err_msg(exc)
            if "ramp" in err.lower():
                note("[RAMP][ALLOWED FAILURE]")
                return
            raise

    @rule(time_increase=integers(min_value=1, max_value=UNIX_DAY * 7))
    def time_forward(self, time_increase):
        """Make the time moves forward by `sleep_time` seconds.
        Useful for ramping, oracle updates, etc.
        Up to 1 week.
        """
        boa.env.time_travel(time_increase)

    @invariant()
    def portfolio_value_match(self):
        total_supply = self.pool.totalSupply()
        if total_supply == 0:
            return
        with boa.env.anchor():
            p = self.pool.last_prices()
            self.pool.eval(f"self.cached_price_oracle = {p}")
            assert self.pool.price_oracle() == pytest.approx(p, rel=1e-7)

            precisions = self.pool.precisions()
            x = self.pool.balances(0) * precisions[0]
            y = self.pool.balances(1) * precisions[1]
            lp_price = self.lp_oracle.lp_price(self.pool)
            assert lp_price * total_supply // 10**18 == pytest.approx(x + p * y // 10**18, rel=2e-6)


LPOracleRampingStateful.TestCase.settings = settings(
    max_examples=10,
    stateful_step_count=50,
    deadline=None,
)

TestLPOracleRampingStateful = LPOracleRampingStateful.TestCase
