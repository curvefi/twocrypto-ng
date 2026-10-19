"""YBOraclizedPolicy: fee, driver, LT deposit gate, governance and deployment.

Mock-pool tests pin the arithmetic. Real-pool tests run the policy on Twocrypto
with a LevAMM/LT stand-in that keeps LT.deposit's order of calls. Two opt-in
fork tests check the Pyth verifier and the production YieldBasis WETH market.
"""

import math
import os
import random
import struct
from decimal import ROUND_FLOOR, Decimal, localcontext
from types import SimpleNamespace

import boa
import pytest
from eth_utils import keccak

from scripts.deploy_yb_oraclized_policy import CONFIG as PRODUCTION
from scripts.deploy_yb_oraclized_policy import companion_calls
from scripts.deploy_yb_oraclized_policy import constructor_args
from scripts.deploy_yb_oraclized_policy import deploy as deploy_script
from tests.utils.constants import POOL_DEPLOYER

WAD = 10**18
Q = 10**10
FEES = (35 * 10**6, 9 * WAD // 10, 300 * 10**6, 120)  # base, capture, fallback, relax_time
# fast, slow, trend_gate, step_cap, report_lifetime (longer than FEES' relax_time)
DRIVER = (3_600, 7_200, 4 * WAD // 1_000, 20 * WAD // 10_000, 900)
TOLERANCE = 10**14  # 1 bp
EMERGENCY = boa.env.generate_address("emergency")
POLICY = boa.load_partial("contracts/main/YBOraclizedPolicy.vy")
# A signed Pyth Pro ETH/USD report (channel 3) and the mainnet state it was checked
# against, for the opt-in fork test.
SIGNED_REPORT = bytes.fromhex(
    "2a22999a959316e6c58af7f283d86e4d5c011f8c4bfd526cd9a11cb34de3a15047bc19ea18a4"
    "e964f9ba9efdc80ec0c684d5466243f40962f9bf6e8ccfe2ae6ea1834f1300002993c7d37500"
    "065b1d1ae41b8003010000000203000000003989b1aead04fff80c0100065b1d1ae41b80"
)
SIGNED_PRICE = 247123259053 * 10**10  # mantissa at exponent -8, in 1e18
SIGNED_OBSERVATION_US = 1789030423600000
PYTH_PIN = SimpleNamespace(
    chain_id=1,
    block=25945920,
    block_timestamp=1789030427,
    verifier="0xACeA761c27A909d4D3895128EBe6370FDE2dF481",
    implementation="0xd8f4a467abec64bc944eee1325b9007879b6555b",
    implementation_codehash="0xe034873bb8d9b1e210a9d0a54b7bb51a9a549cc244d2046e6c55d2d390851511",
    verification_fee_wei=1,
)

# ABI stub only: signature authentication is checked separately against Pyth on a fork.
VERIFIER = """
@external
@view
def verification_fee() -> uint256:
    return 1

@external
@payable
def verifyUpdate(report: Bytes[112]) -> (Bytes[41], address):
    assert msg.value == 1 and slice(report, 0, 1) == b"\\x00", "verification failed"
    return slice(report, 71, 41), self
"""

POOL_MOCK = """
_price_scale: uint256
D: public(uint256)
A: public(uint256)
balances: public(uint256[2])
last_prices: public(uint256)
user_supply: public(uint256)
admin_balances: public(uint256[2])
admin_fee: public(uint256)
balanceOf: public(HashMap[address, uint256])
coins: public(address[2])
precision0: uint256
locked: bool

@deploy
def __init__():
    self._price_scale = 100 * 10**18
    self.D = 2 * 10**24
    self.A = 100_000
    self.balances = [10**24, 10**22]  # xp = [1e24, 1e24] at price_scale 100
    self.last_prices = 100 * 10**18
    self.user_supply = 10**24
    self.coins = [self, empty(address)]
    self.precision0 = 1

@external
@view
def price_scale() -> uint256:
    assert not self.locked, "locked"  # Twocrypto's getter is nonreentrant.
    return self._price_scale

@external
@view
def precisions() -> uint256[2]:
    return [self.precision0, 1]
"""

# The LevAMM book for mock-pool tests.
AMM_MOCK = """
COLLATERAL: public(address)
STABLECOIN: public(address)
collateral_amount: public(uint256)
get_debt: public(uint256)

@deploy
def __init__(collateral: address, stablecoin: address):
    self.COLLATERAL = collateral
    self.STABLECOIN = stablecoin
"""

# LevAMM and LT in one contract. deposit() keeps LT.deposit's order: liquidity is
# added with the LevAMM as LP receiver, the pool calls the policy back, and only
# then is the LP booked. The contract funds itself, like LT pulling the LevAMM's
# idle stablecoin and the depositor's asset.
MARKET_MOCK = """
interface Pool:
    def add_liquidity(amounts: uint256[2], min_mint_amount: uint256, receiver: address) -> uint256: nonpayable
    def remove_liquidity(amount: uint256, min_amounts: uint256[2]) -> uint256[2]: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def coins(i: uint256) -> address: view

interface ERC20:
    def approve(spender: address, amount: uint256) -> bool: nonpayable

COLLATERAL: public(address)
STABLECOIN: public(address)
collateral_amount: public(uint256)
get_debt: public(uint256)

@deploy
def __init__(pool: address):
    self.COLLATERAL = pool
    self.STABLECOIN = staticcall Pool(pool).coins(0)
    for i: uint256 in range(2):
        extcall ERC20(staticcall Pool(pool).coins(i)).approve(pool, max_value(uint256))

@external
def deposit(assets: uint256, debt: uint256) -> uint256:
    lp: uint256 = extcall Pool(self.COLLATERAL).add_liquidity([debt, assets], 0, self)
    self.collateral_amount += lp
    self.get_debt += debt
    return lp

@external
def withdraw(frac: uint256) -> uint256[2]:
    lp: uint256 = self.collateral_amount * frac // 10**18
    self.collateral_amount -= lp
    self.get_debt -= self.get_debt * frac // 10**18
    return extcall Pool(self.COLLATERAL).remove_liquidity(lp, [0, 0])

@external
def buy_lp(lp: uint256):
    # LevAMM.exchange with LP in: the transfer and the booking settle together.
    extcall Pool(self.COLLATERAL).transferFrom(msg.sender, self, lp)
    self.collateral_amount += lp
"""


def report(price, observation_us=None, message_us=None, feed=2, channel=3):
    if observation_us is None:
        observation_us = boa.env.evm.patch.timestamp * 1_000_000
    if message_us is None:
        message_us = observation_us
    payload = struct.pack(
        ">IQBBIBBqBhBBQ",
        2479346549,
        message_us,
        channel,
        1,
        feed,
        3,
        0,
        price // 10**10,
        4,
        -8,
        12,
        1,
        observation_us,
    )
    assert len(payload) == 41
    return bytes(71) + payload


def config(fees=FEES, driver=DRIVER, tolerance=TOLERANCE):
    """PolicyConfig(fee, driver, ratio_tolerance)."""
    return (fees, driver, tolerance)


def oracle(verifier, channel=3, past=12_000_000, future=6_000_000, low=10**6, high=10**30):
    """OracleConfig: the backtested windows, and price bounds that admit every test price."""
    return (verifier, channel, past, future, low, high)


def deploy(pool, amm=None, fees=FEES, driver=DRIVER, tolerance=TOLERANCE, verifier=None):
    if amm is None:
        amm = boa.loads(AMM_MOCK, pool.address, pool.coins(0))
    if verifier is None:
        verifier = boa.loads(VERIFIER)
    boa.env.set_balance(boa.env.eoa, WAD)
    return POLICY.deploy(
        pool.address,
        amm.address,
        2,
        EMERGENCY,
        oracle(verifier.address),
        config(fees, driver, tolerance),
    )


def push(policy, pool, scale=100 * WAD, spot=100 * WAD, oracle=100 * WAD, xp=None):
    xp = [10**24, 10**24] if xp is None else xp
    policy.update_pool_state(xp, scale, oracle, spot, WAD, WAD, pool.D(), 0, sender=pool.address)


@pytest.fixture
def setup():
    with boa.env.anchor():
        pool = boa.loads(POOL_MOCK)
        policy = deploy(pool)
        push(policy, pool)
        yield pool, policy


def expected_fee(edge, age_us, fees=FEES):
    """(1 - w) * fresh + w * fallback, w = sqrt(age / relax_time): surcharge floored, plus one unit."""
    with localcontext() as ctx:
        ctx.prec = 70
        base, capture, fallback, relax = fees
        fresh = min(fallback, base + capture * max(edge - base, 0) // WAD)
        if age_us == 0 or fresh == fallback:
            return fresh
        weight = min(Decimal(age_us) / (relax * 10**6), Decimal(1)).sqrt()
        return (
            fresh + int(((fallback - fresh) * weight).to_integral_value(rounding=ROUND_FLOOR)) + 1
        )


def get_p(xp, D, A):
    """Twocrypto/StableswapMath _get_p, times nothing: dx0 / dx1 at xp."""
    ANN = A * 2
    Dr = D // 4
    for x in xp:
        Dr = Dr * D // x
    xp0_A = ANN * xp[0] // 10_000
    return WAD * (xp0_A + Dr * xp[0] // xp[1]) // (xp0_A + Dr)


# ------------------------------------ Fee ------------------------------------


@pytest.mark.parametrize(
    "fees",
    [
        FEES,
        (50 * 10**6, 85 * WAD // 100, 180 * 10**6, 300),  # candidate 3192329
        (50 * 10**6, 675 * WAD // 1_000, 175 * 10**6, 300),  # candidates 21859 and 521415
        (100_000, WAD, 100_000, 3_600),
        (100_000, 0, Q // 10, 1),
    ],
)
def test_reported_fee_matches_sqrt_reference(fees):
    with boa.env.anchor():
        policy = deploy(boa.loads(POOL_MOCK), fees=fees)
        rng = random.Random(139)
        relax_us = fees[3] * 10**6
        cases = [
            (edge, age)
            for edge in (0, 1, fees[0], fees[2], Q)
            for age in (0, 1, relax_us // 2, relax_us - 1)
        ] + [(rng.randrange(Q + 1), rng.randrange(relax_us)) for _ in range(100)]
        previous = None
        for edge, age in sorted(cases):
            fee = policy.internal._reported_fee(fees, edge, age)
            assert fee == expected_fee(edge, age, fees)
            assert fees[0] <= expected_fee(edge, 0, fees) <= fee <= fees[2]
            if previous is not None and previous[0] == edge:
                assert fee >= previous[1]  # Older reports never pay less.
            previous = (edge, fee)


@pytest.mark.parametrize("coin_in", [0, 1])
def test_reported_edge_uses_floor_valuations(setup, coin_in):
    _, policy = setup
    previous = [10**24, 10**24]
    scale, price = 100 * WAD, 101 * WAD
    for amount_in in (1, 2, 3, WAD, 99 * WAD, 101 * WAD):
        for amount_out in (1, 2, 3, WAD, 100 * WAD):
            candidate = previous.copy()
            candidate[coin_in] += amount_in
            candidate[1 - coin_in] -= amount_out
            if coin_in == 1:
                input_value, output_value = amount_in * price // scale, amount_out
            else:
                input_value, output_value = amount_in, amount_out * price // scale
            expected = Q - min(Q, input_value * Q // output_value)
            assert (
                policy.internal._reported_edge(candidate, previous, scale, price, coin_in)
                == expected
            )


def test_edge_ratio_reverts_on_uint256_overflow(setup):
    _, policy = setup
    # Valuation fits uint256, but multiplying either value by fee precision does not.
    with boa.reverts():
        policy.internal._reported_edge([1 + 10**70, 1], [1, 10**65], 1, 10**6, 0)


def test_fee_classification(setup):
    pool, policy = setup
    base, capture, fallback, relax = FEES
    balance = 10**24
    toward = [balance + 99 * WAD, balance - 100 * WAD]  # coin0 in at 0.99 per 1/100 coin1
    assert policy.get_fee(toward) == fallback  # No report yet.

    observed = boa.env.evm.patch.timestamp * 1_000_000 - 1_000_000
    policy.deliver_oracle_report(report(101 * WAD, observed), value=1)
    edge = Q - 99 * WAD * Q // (100 * WAD * 101 // 100)
    assert policy.get_fee(toward) == expected_fee(edge, 1_000_000) < fallback

    # Liquidity operations and unchanged balances pay fallback.
    for xp in (
        [balance, balance],
        [balance + WAD, balance + WAD],
        [balance - WAD, balance - WAD],
        [balance + WAD, balance],
        [balance, balance - WAD],
    ):
        assert policy.get_fee(xp) == fallback
    # Moving the spot away from the report, or with no edge, pays fallback.
    assert policy.get_fee([balance - 100 * WAD, balance + 99 * WAD]) == fallback
    assert policy.get_fee([balance + 100 * WAD, balance - WAD]) == fallback
    # A stale snapshot pays fallback: D moved without a callback.
    with boa.env.anchor():
        pool.eval("self.D += 1")
        assert policy.get_fee(toward) == fallback
        assert policy.get_fee_with_report(toward, 101 * WAD, 0) == fallback
    # The discount thaws with observation age, not delivery age, and ends at relax_time.
    boa.env.time_travel(blocks=1, block_delta=12)
    assert expected_fee(edge, 1_000_000) < policy.get_fee(toward) == expected_fee(edge, 13_000_000)
    boa.env.time_travel(seconds=relax - 14)
    assert policy.get_fee(toward) == expected_fee(edge, (relax - 1) * 10**6) < fallback
    boa.env.time_travel(seconds=1)
    assert policy.get_fee(toward) == fallback


def test_future_report_has_zero_age(setup):
    _, policy = setup
    candidate = [10**24 + 99 * WAD, 10**24 - 100 * WAD]
    now = boa.env.evm.patch.timestamp * 1_000_000
    policy.deliver_oracle_report(report(101 * WAD, now + 6_000_000), value=1)
    fresh = policy.get_fee_with_report(candidate, 101 * WAD, 0)
    assert policy.get_fee(candidate) == fresh < FEES[2]
    boa.env.time_travel(seconds=12)
    aged = policy.get_fee_with_report(candidate, 101 * WAD, 6_000_000)
    assert policy.get_fee(candidate) == aged > fresh


@pytest.mark.parametrize("report_price", [0, 99 * WAD, 101 * WAD])
@pytest.mark.parametrize("age_us", [0, 1_000_000, 119_000_000, 120_000_000])
def test_hypothetical_report_matches_stored_report(setup, report_price, age_us):
    pool, policy = setup
    balance = 10**24
    candidates = [
        [balance + 99 * WAD, balance - 100 * WAD],
        [balance - 100 * WAD, balance + 99 * WAD],
        [balance, balance],
        [balance + WAD, balance + WAD],
        [balance - WAD, balance - WAD],
    ]
    previews = [policy.get_fee_with_report(xp, report_price, age_us) for xp in candidates]
    with boa.env.anchor():
        observation_us = boa.env.evm.patch.timestamp * 1_000_000 - age_us
        policy.eval(
            f"self.report = Report(asset_price={report_price}, observation_us={observation_us})"
        )
        assert previews == [policy.get_fee(xp) for xp in candidates]


@pytest.mark.parametrize("coin_in", [0, 1])
@pytest.mark.parametrize("dx", [10**21, 10**22, 10**23])
def test_report_behind_the_spot_pays_fallback(setup, coin_in, dx):
    pool, policy = setup
    math_contract = boa.load("contracts/main/StableswapMath.vy")
    xp = [10**24, 10**24]
    xp[coin_in] += dx
    xp[1 - coin_in] = math_contract.get_y(pool.A(), 0, xp, pool.D(), 1 - coin_in)[0]
    # The report is on the wrong side of the starting marginal price.
    policy.deliver_oracle_report(report(99 * WAD if coin_in == 0 else 101 * WAD), value=1)
    assert policy.get_fee(xp) == FEES[2]


def test_zero_edge_pays_fallback_with_corrective_marginal_prices(setup):
    pool, policy = setup
    balance = 10**24
    report_price = 100 * WAD + WAD // 2
    candidate = [balance + 101 * WAD, balance - 100 * WAD]
    # This synthetic quote is off the invariant, but passes the marginal-price gate.
    p_before = get_p([balance, balance], pool.D(), pool.A()) * 100
    p_after = get_p(candidate, pool.D(), pool.A()) * 100
    assert p_before < p_after <= report_price
    assert 101 * WAD >= 100 * WAD * report_price // (100 * WAD)  # No reported edge.
    policy.deliver_oracle_report(report(report_price), value=1)
    assert policy.get_fee(candidate) == FEES[2]


def test_corrective_check_uses_synced_amplification(setup):
    pool, policy = setup
    balance, D = 10**24, pool.D()
    # Synthetic, off-invariant endpoint with a ~35 bp edge: 289 in for 290 * 1.00003 out.
    candidate = [balance + 289 * WAD, balance - 290 * WAD]
    # A flatter curve (higher A) moves the marginal price less for the same trade.
    p_low = get_p(candidate, D, 100_000) * 100
    p_high = get_p(candidate, D, 400_000) * 100
    assert 100 * WAD < p_high < p_low
    report_price = (p_low + p_high) // 2
    policy.deliver_oracle_report(report(report_price), value=1)
    assert policy.cached_A() == 100_000
    assert policy.get_fee(candidate) == FEES[2]  # Passes the report at A = 100_000.
    pool.eval("self.A = 400_000")
    assert policy.get_fee(candidate) == FEES[2]  # The policy prices with its cached A ...
    policy.sync(sender=boa.env.generate_address())  # ... until anyone syncs it.
    assert policy.cached_A() == 400_000
    assert policy.get_fee(candidate) < FEES[2]  # Stops short of the report at A = 400_000.


# ---------------------------------- Reports ----------------------------------


def test_report_admission(setup):
    pool, policy = setup
    now = boa.env.evm.patch.timestamp * 1_000_000
    state = policy.state()
    policy.deliver_oracle_report(report(100 * WAD, now - 1_000_000), value=1)
    assert tuple(policy.report()) == (100 * WAD, now - 1_000_000)
    assert policy.state() == state  # Delivery checkpoints nothing.
    saved = policy.report()
    for observation in (now - 1_000_000, now - 1_000_001):
        with boa.reverts("observation not newer"):
            policy.deliver_oracle_report(report(100 * WAD, observation), value=1)
    for payload, reason in (
        (report(100 * WAD, now - 12_000_001), "report too old"),
        (report(100 * WAD, now + 6_000_001), "report time"),
        (report(100 * WAD, now, now + 6_000_001), "report time"),
        (report(100 * WAD, now, now - 1), "report time"),
        (report(100 * WAD, now, feed=1), "feed"),
        (report(100 * WAD, now, channel=1), "channel"),
        (report(100 * WAD, now)[:-1], "report length"),
        (b"\xff" + report(100 * WAD, now)[1:], "verification failed"),
    ):
        with boa.reverts(reason):
            policy.deliver_oracle_report(payload, value=1)
    assert policy.report() == saved
    # Twocrypto's price_scale() is nonreentrant: no delivery inside a pool operation.
    pool.eval("self.locked = True")
    with boa.reverts("locked"):
        policy.deliver_oracle_report(report(100 * WAD, now), value=1)


def test_report_admission_is_settable(setup):
    _, policy = setup
    now = boa.env.evm.patch.timestamp * 1_000_000
    # Tighter windows (no message ahead of the block) and ETH-like price bounds.
    policy.set_oracle_config(
        oracle(policy.oracle()[0], past=2_000_000, future=0, low=50 * WAD, high=200 * WAD)
    )
    for payload, reason in (
        (report(100 * WAD, now - 2_000_001), "report too old"),
        (report(100 * WAD, now, now + 1), "report time"),
        (report(100 * WAD, now + 1), "report time"),
        (report(50 * WAD - 10**10, now), "price bounds"),
        (report(200 * WAD + 10**10, now), "price bounds"),
    ):
        with boa.reverts(reason):
            policy.deliver_oracle_report(payload, value=1)
    policy.deliver_oracle_report(report(200 * WAD, now - 2_000_000), value=1)
    assert tuple(policy.report()) == (200 * WAD, now - 2_000_000)
    policy.deliver_oracle_report(report(50 * WAD, now), value=1)
    assert tuple(policy.report()) == (50 * WAD, now)


def test_report_rejects_short_authenticated_payload(setup):
    pool, _ = setup
    verifier = boa.loads(VERIFIER.replace("slice(report, 71, 41)", "slice(report, 71, 40)"))
    policy = deploy(pool, verifier=verifier)
    with boa.reverts("payload length"):
        policy.deliver_oracle_report(report(100 * WAD), value=1)


# ---------------------------------- Driver -----------------------------------


class LeanDriver:
    """
    report_lean.hpp get_price_scale/update_state in floating point (half-gap
    step law): the observation is the stored report while its age is below
    report_lifetime_s, else the pool's last_prices.
    """

    def __init__(self, driver=DRIVER):
        self.fast_hl, self.slow_hl, self.gate, self.cap, self.lifetime = driver
        self.gate /= WAD
        self.cap /= WAD
        self.ts = self.fast = self.slow = self.scale = None

    def observation(self, now, last_report, last_prices):
        price, observation_us = last_report
        age = max(now * 10**6 - observation_us, 0)
        return price / WAD if price and age < self.lifetime * 10**6 else last_prices / WAD

    def emas(self, observation, now):
        dt = now - self.ts
        if dt == 0:
            return self.fast, self.slow
        o = min(max(observation, self.scale / 2), 2 * self.scale)
        af = math.exp(-math.log(2) * dt / self.fast_hl)
        a_s = math.exp(-math.log(2) * dt / self.slow_hl)
        return o * (1 - af) + self.fast * af, o * (1 - a_s) + self.slow * a_s

    def target(self, now, last_report, last_prices):
        o = self.observation(now, last_report, last_prices)
        fast, slow = self.emas(o, now)
        target = fast
        if self.gate > 0:
            w = min(1.0, abs(fast / slow - 1) / self.gate)
            target = fast + w * (o - fast)
        move = min(abs(target - self.scale) / 2, self.cap * self.scale)
        return self.scale + 5 * move if target >= self.scale else self.scale - 5 * move

    def update(self, now, last_report, last_prices, price_oracle, price_scale):
        if self.scale is None:
            self.fast = self.slow = price_oracle / WAD
        else:
            self.fast, self.slow = self.emas(self.observation(now, last_report, last_prices), now)
        self.ts, self.scale = now, price_scale / WAD


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize(
    "driver",
    [
        DRIVER,
        (600, 600, 0, WAD // 10_000, 0),
        (7_200, 10_800, WAD // 1_000, 60 * WAD // 10_000, 14_400),
    ],
)
def test_driver_matches_report_lean_reference(seed, driver):
    rng = random.Random(seed)
    with boa.env.anchor():
        pool = boa.loads(POOL_MOCK)
        policy = deploy(pool, driver=driver)
        lean = LeanDriver(driver=driver)
        assert policy.get_price_scale() == 0 and policy.get_emas() == [0, 0]

        scale = spot = 100 * WAD
        oracle = 99 * WAD
        for step in range(60):
            now = boa.env.evm.patch.timestamp
            push(policy, pool, scale, spot, oracle)
            lean.update(now, tuple(policy.report()), spot, oracle, scale)
            fast, slow = policy.get_emas()
            assert math.isclose(fast / WAD, lean.fast, rel_tol=1e-12)
            assert math.isclose(slow / WAD, lean.slow, rel_tol=1e-12)

            boa.env.time_travel(seconds=rng.choice([0, 1, 12, 12, 60, 600, 3_600, 7_200]))
            spot = spot * (1000 + rng.randint(-30, 30)) // 1000
            pool.eval(f"self.last_prices = {spot}")
            if rng.random() < 0.4:
                observed = boa.env.evm.patch.timestamp * 10**6 - rng.randrange(12_000_000)
                if observed > policy.report().observation_us:
                    price = spot * (10_000 + rng.randint(-50, 50)) // 10_000
                    policy.deliver_oracle_report(report(price, observed), value=1)
            target = policy.get_price_scale()
            expected = lean.target(boa.env.evm.patch.timestamp, tuple(policy.report()), spot)
            assert math.isclose(target / WAD, expected, rel_tol=1e-12, abs_tol=1e-15 * scale / WAD)
            # The pool steps one fifth of the requested gap.
            scale = scale + (target - scale) // 5


def test_observed_price_is_report_for_its_lifetime(setup):
    pool, policy = setup
    toward = [10**24 + 99 * WAD, 10**24 - 100 * WAD]  # coin0 in, toward the report
    pool.eval(f"self.last_prices = {90 * WAD}")
    boa.env.time_travel(seconds=1)
    policy.deliver_oracle_report(report(101 * WAD), value=1)
    assert policy.internal._observed_report() == 101 * WAD
    assert policy.get_fee(toward) < FEES[2]
    # relax_time ends the fee discount only: the EMAs keep observing the report.
    boa.env.time_travel(seconds=FEES[3])
    assert policy.get_fee(toward) == FEES[2]
    assert policy.internal._observed_report() == 101 * WAD
    boa.env.time_travel(seconds=DRIVER[4] - FEES[3] - 1)
    assert policy.internal._observed_report() == 101 * WAD
    boa.env.time_travel(seconds=1)
    assert policy.internal._observed_report() == 0


def test_zero_report_lifetime_never_observes_a_report(setup):
    pool, policy = setup
    toward = [10**24 + 99 * WAD, 10**24 - 100 * WAD]
    policy.set_policy_config(config(driver=DRIVER[:4] + (0,)))
    pool.eval(f"self.last_prices = {90 * WAD}")
    boa.env.time_travel(seconds=1)
    # Even a report observed after block.timestamp (age 0): fees still use it.
    policy.deliver_oracle_report(
        report(101 * WAD, boa.env.evm.patch.timestamp * 10**6 + 1), value=1
    )
    assert policy.get_fee(toward) < FEES[2]
    assert policy.internal._observed_report() == 0


def test_target_weight_and_step_cap(setup):
    pool, policy = setup
    scale = 100 * WAD
    cap_move = scale * DRIVER[3] // WAD
    # Fresh attachment: fast == slow == oracle, so the target is the fast EMA.
    with boa.env.anchor():
        pool.eval(f"self.last_prices = {150 * WAD}")
        assert policy.get_price_scale() == scale  # dt = 0: EMAs and target unchanged.
    # A large move: trend >= gate, the target is the observation, the cap binds.
    for price, sign in ((150 * WAD, 1), (60 * WAD, -1)):
        with boa.env.anchor():
            boa.env.time_travel(seconds=3_600)
            pool.eval(f"self.last_prices = {price}")
            fast, slow = policy.get_emas()
            assert abs(fast - slow) * WAD // slow >= DRIVER[2]
            assert policy.get_price_scale() == scale + sign * 5 * cap_move
    # Below the cap half the gap is requested, five times over.
    with boa.env.anchor():
        boa.env.time_travel(seconds=60)
        pool.eval(f"self.last_prices = {100 * WAD + 10**15}")
        fast, slow = policy.get_emas()
        trend = (fast - slow) * WAD // slow
        assert 0 < trend < DRIVER[2]
        target = fast + (100 * WAD + 10**15 - fast) * trend // DRIVER[2]
        assert 0 < target - scale < 2 * cap_move
        assert policy.get_price_scale() == scale + 5 * ((target - scale) // 2)


def test_half_gap_step_law():
    """report_lean's move = min(gap / 2, step_cap * scale), around the knee gap = 2 * cap."""
    with boa.env.anchor():
        pool = boa.loads(POOL_MOCK)
        policy = deploy(pool, driver=DRIVER[:2] + (0,) + DRIVER[3:])  # Gate off: target = fast.
        push(policy, pool)
        scale = 100 * WAD
        cap = scale * DRIVER[3] // WAD

        def ask(target):
            policy.eval(f"self.state.fast_ema = {target}")  # dt = 0: the EMAs as stored.
            return policy.get_price_scale()

        assert ask(scale) == ask(scale + 1) == ask(scale - 1) == scale  # Half a wei rounds down.
        for sign in (1, -1):
            for gap, move in (
                (cap * 19 // 10, cap * 19 // 20),
                (2 * cap, cap),
                (cap * 21 // 10, cap),
            ):
                assert ask(scale + sign * gap) == scale + sign * 5 * move


def test_zero_trend_gate_follows_the_fast_ema():
    with boa.env.anchor():
        pool = boa.loads(POOL_MOCK)
        policy = deploy(pool, driver=DRIVER[:2] + (0, 60 * WAD // 10_000) + DRIVER[4:])
        push(policy, pool)
        boa.env.time_travel(seconds=600)
        pool.eval(f"self.last_prices = {101 * WAD}")
        fast, _ = policy.get_emas()
        assert policy.get_price_scale() == 100 * WAD + 5 * ((fast - 100 * WAD) // 2)


# Argon's vectors: report_lean.hpp evaluated with uint256 arithmetic for candidate
# 3192329 (pool A = 50_000), driver targets updated to the half-gap step law, aged
# fees to the floored surcharge plus one unit (one unit more at the exact roots of
# 12 s and 75 s). Each
# driver vector's report arrives with its own touch (age 0), so any positive
# report_lifetime observes it.
CANDIDATE_FEES = (50_000_000, 85 * WAD // 100, 180_000_000, 300)
CANDIDATE_DRIVER = (7_200, 10_800, 4 * WAD // 1_000, 2 * WAD // 1_000, 5_400)
# (name, snapshot xp, snapshot D, price_scale, quoted xp, report price, report age us, live D, fee)
REPORT_LEAN_FEE_VECTORS = [
    (
        "fresh_age0_corrective_coin0_in_100bp_edge",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [1010000000000000000000000, 990016640086811370346251],
        2525000000000000000000,
        0,
        2000000000000000000000000,
        77631040,
    ),
    (
        "future_report_minus2s_zero_age_coin0_in",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [1010000000000000000000000, 990016640086811370346251],
        2525000000000000000000,
        -2000000,
        2000000000000000000000000,
        77631040,
    ),
    (
        "fresh_edge_below_base_fee_returns_base",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [1010000000000000000000000, 990016640086811370346251],
        2510000000000000000000,
        0,
        2000000000000000000000000,
        50000000,
    ),
    (
        "fresh_age0_corrective_coin1_in_100bp_edge",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [990016640086811370346251, 1010000000000000000000000],
        2475000000000000000000,
        0,
        2000000000000000000000000,
        78474028,
    ),
    (
        "aged_12s_corrective_coin0_in_w_0p2",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [1010000000000000000000000, 990016640086811370346251],
        2525000000000000000000,
        12000000,
        2000000000000000000000000,
        98104833,
    ),
    (
        "aged_75s_corrective_coin0_in_w_0p5",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [1010000000000000000000000, 990016640086811370346251],
        2525000000000000000000,
        75000000,
        2000000000000000000000000,
        128815521,
    ),
    (
        "aged_100s_non_exact_sqrt_coin0_in",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [1010000000000000000000000, 990016640086811370346251],
        2525000000000000000000,
        100000000,
        2000000000000000000000000,
        136733787,
    ),
    (
        "expired_300s_returns_fallback",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [1010000000000000000000000, 990016640086811370346251],
        2525000000000000000000,
        300000000,
        2000000000000000000000000,
        180000000,
    ),
    (
        "non_corrective_wrong_side_returns_fallback",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [1010000000000000000000000, 990016640086811370346251],
        2475000000000000000000,
        0,
        2000000000000000000000000,
        180000000,
    ),
    (
        "non_corrective_overshoot_returns_fallback",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [1050000000000000000000000, 950413929685570330293889],
        2502000000000000000000,
        0,
        2000000000000000000000000,
        180000000,
    ),
    (
        "liquidity_deposit_returns_fallback",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [1001000000000000000000000, 1001000000000000000000000],
        2525000000000000000000,
        0,
        2000000000000000000000000,
        180000000,
    ),
    (
        "liquidity_withdrawal_returns_fallback",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [999000000000000000000000, 999000000000000000000000],
        2525000000000000000000,
        0,
        2000000000000000000000000,
        180000000,
    ),
    (
        "stale_D_mismatch_returns_fallback",
        [1000000000000000000000000, 1000000000000000000000000],
        2000000000000000000000000,
        2500000000000000000000,
        [1010000000000000000000000, 990016640086811370346251],
        2525000000000000000000,
        0,
        2000000000000000000000001,
        180000000,
    ),
]
# (name, dt since the last update or None before attachment, fast, slow, price_scale,
#  touch report, pool last_prices, price_oracle, target, fast after, slow after)
REPORT_LEAN_DRIVER_VECTORS = [
    (
        "uninitialized_first_touch_seeds_oracle",
        None,
        0,
        0,
        0,
        0,
        2500000000000000000000,
        2495000000000000000000,
        0,
        2495000000000000000000,
        2495000000000000000000,
    ),
    (
        "dt0_equal_emas_weight_zero_hold",
        0,
        2500000000000000000000,
        2500000000000000000000,
        2500000000000000000000,
        2520000000000000000000,
        2510000000000000000000,
        2500000000000000000000,
        2500000000000000000000,
        2500000000000000000000,
        2500000000000000000000,
    ),
    (
        "dt0_partial_trend_w_0p5_step_cap_binds_with_report",
        0,
        2505000000000000000000,
        2500000000000000000000,
        2500000000000000000000,
        2515000000000000000000,
        2502000000000000000000,
        2500000000000000000000,
        2525000000000000000000,
        2505000000000000000000,
        2500000000000000000000,
    ),
    (
        "dt0_partial_trend_w_0p2_step_cap_not_binding_no_report",
        0,
        2502000000000000000000,
        2500000000000000000000,
        2500000000000000000000,
        0,
        2507000000000000000000,
        2500000000000000000000,
        2507500000000000000000,
        2502000000000000000000,
        2500000000000000000000,
    ),
    (
        "dt600_full_trend_w_1_upward_cap_binds_with_report",
        600,
        2515000000000000000000,
        2500000000000000000000,
        2500000000000000000000,
        2550000000000000000000,
        2530000000000000000000,
        2510000000000000000000,
        2525000000000000000000,
        2516964399056140727640,
        2501888808155292743000,
    ),
    (
        "dt1800_full_trend_w_1_downward_cap_binds_no_report",
        1800,
        2480000000000000000000,
        2500000000000000000000,
        2500000000000000000000,
        0,
        2440000000000000000000,
        2470000000000000000000,
        2475000000000000000000,
        2473635856610148581720,
        2493453923088420358240,
    ),
    (
        "dt3600_extreme_obs_clamped_for_ema_unclamped_for_target",
        3600,
        2500000000000000000000,
        2500000000000000000000,
        2500000000000000000000,
        6000000000000000000000,
        6000000000000000000000,
        2500000000000000000000,
        2525000000000000000000,
        3232233047033631190000,
        3015748685039750657500,
    ),
]


@pytest.mark.parametrize("vector", REPORT_LEAN_FEE_VECTORS, ids=lambda v: v[0])
def test_fee_matches_report_lean_vectors(vector):
    _, old, D, scale, xp, price, age_us, live_D, expected = vector
    with boa.env.anchor():
        pool = boa.loads(POOL_MOCK)
        pool.eval("self.A = 50_000")
        policy = deploy(pool, fees=CANDIDATE_FEES, driver=CANDIDATE_DRIVER)
        now = boa.env.evm.patch.timestamp
        policy.eval(
            f"self.state = State(last_update_ts={now}, fast_ema={scale}, slow_ema={scale},"
            f" price_scale={scale}, xp={old}, D={D})"
        )
        policy.eval(
            f"self.report = Report(asset_price={price}, observation_us={now * 10**6 - age_us})"
        )
        pool.eval(f"self.D = {live_D}")
        assert policy.get_fee(xp) == expected


@pytest.mark.parametrize("vector", REPORT_LEAN_DRIVER_VECTORS, ids=lambda v: v[0])
def test_driver_matches_report_lean_vectors(vector):
    _, dt, fast, slow, scale, touch_report, last_prices, oracle, target, fast_after, slow_after = (
        vector
    )
    with boa.env.anchor():
        pool = boa.loads(POOL_MOCK)
        policy = deploy(pool, fees=CANDIDATE_FEES, driver=CANDIDATE_DRIVER)
        now = boa.env.evm.patch.timestamp
        last = 0 if dt is None else now - dt
        policy.eval(
            f"self.state = State(last_update_ts={last}, fast_ema={fast}, slow_ema={slow},"
            f" price_scale={scale}, xp=[10**24, 10**24], D=2 * 10**24)"
        )
        if touch_report:
            policy.eval(
                f"self.report = Report(asset_price={touch_report}, observation_us={now * 10**6})"
            )
        pool.eval(f"self.last_prices = {last_prices}")
        assert policy.get_price_scale() == target
        push(policy, pool, scale=scale or oracle, spot=last_prices, oracle=oracle)
        assert (policy.state().fast_ema, policy.state().slow_ema) == (fast_after, slow_after)


# report_lean.hpp at twocrypto-cpp 6d1d8a9 (ChallengeFeePolicy<double>) for candidate
# 521415 with the listed report_lifetime_s: one touch with a stored report of the
# listed age (negative: observed after the block). Printed by a C++ program that
# calls the header's get_price_scale and update_state; floating point, so compared to
# 1e-12. Prices in USD.
LIFETIME_FEES = (50_000_000, 675 * WAD // 1_000, 175_000_000, 300)
LIFETIME_DRIVER = (4_800, 9_600, 7 * WAD // 1_000, 5 * WAD // 1_000)  # report_lifetime per vector
# (name, report_lifetime, dt, fast, slow, price_scale, stored report (0: dropped), its
#  age in seconds, pool last_prices, price_oracle, target, fast after, slow after)
REPORT_LIFETIME_VECTORS = [
    (
        "stored_report_600s_old_inside_lifetime",
        5400,
        600,
        2500,
        2490,
        2500,
        2550,
        600,
        2520,
        2500,
        2562.5,
        2504.1497978397661,
        2492.5438031580857,
    ),
    (
        "stored_report_5399s_old_inside_lifetime",
        5400,
        3600,
        2500,
        2500,
        2500,
        2530,
        5399,
        2470,
        2500,
        2543.8611673435366,
        2512.1618932749593,
        2506.8668376188812,
    ),
    (
        "stored_report_5400s_old_expired_last_prices",
        5400,
        3600,
        2500,
        2500,
        2500,
        2530,
        5400,
        2470,
        2500,
        2456.0647065330168,
        2487.8381067250407,
        2493.1331623811193,
    ),
    (
        "report_with_this_touch_full_trend",
        5400,
        12,
        2530,
        2490,
        2500,
        2560,
        0,
        2545,
        2500,
        2562.5,
        2530.0519410220786,
        2490.0606241111113,
    ),
    (
        "future_report_3s_ahead_counts_as_age_0",
        5400,
        60,
        2504,
        2500,
        2500,
        2512,
        -3,
        2490,
        2500,
        2514.7238565852831,
        2504.0690153002988,
        2500.0518735948008,
    ),
    (
        "zero_lifetime_ignores_a_fresh_report",
        0,
        600,
        2500,
        2490,
        2500,
        2550,
        0,
        2520,
        2500,
        2531.4618768467267,
        2501.6599191359064,
        2491.2719015790431,
    ),
    (
        "dropped_report_price_uses_last_prices",
        5400,
        600,
        2500,
        2490,
        2500,
        0,
        10,
        2440,
        2500,
        2437.5,
        2495.0202425922803,
        2487.8801640349288,
    ),
    (
        "stored_report_below_scale_partial_trend",
        5400,
        1800,
        2496,
        2500,
        2500,
        2480,
        900,
        2510,
        2500,
        2471.6263181669956,
        2492.3376866032636,
        2497.5625216037333,
    ),
]


@pytest.mark.parametrize("vector", REPORT_LIFETIME_VECTORS, ids=lambda v: v[0])
def test_driver_matches_report_lean_lifetime_vectors(vector):
    (
        _,
        lifetime,
        dt,
        fast,
        slow,
        scale,
        price,
        age,
        last_prices,
        oracle,
        target,
        fast_after,
        slow_after,
    ) = vector
    with boa.env.anchor():
        pool = boa.loads(POOL_MOCK)
        policy = deploy(pool, fees=LIFETIME_FEES, driver=LIFETIME_DRIVER + (lifetime,))
        now = boa.env.evm.patch.timestamp
        policy.eval(
            f"self.state = State(last_update_ts={now - dt}, fast_ema={fast * WAD}, slow_ema={slow * WAD},"
            f" price_scale={scale * WAD}, xp=[10**24, 10**24], D=2 * 10**24)"
        )
        policy.eval(
            f"self.report = Report(asset_price={price * WAD}, observation_us={(now - age) * 10**6})"
        )
        pool.eval(f"self.last_prices = {last_prices * WAD}")
        assert math.isclose(policy.get_price_scale() / WAD, target, rel_tol=1e-12)
        push(policy, pool, scale=scale * WAD, spot=last_prices * WAD, oracle=oracle * WAD)
        assert math.isclose(policy.state().fast_ema / WAD, fast_after, rel_tol=1e-12)
        assert math.isclose(policy.state().slow_ema / WAD, slow_after, rel_tol=1e-12)


# -------------------------------- Governance ---------------------------------


def test_constructor_validation():
    with boa.env.anchor():
        pool = boa.loads(POOL_MOCK)
        amm = boa.loads(AMM_MOCK, pool.address, pool.address)
        verifier = boa.loads(VERIFIER)
        base = dict(
            pool=pool.address,
            amm=amm.address,
            pyth=verifier.address,
            feed_id=2,
            channel=3,
            emergency_admin=EMERGENCY,
            fees=FEES,
            fast=3_600,
            slow=7_200,
            gate=DRIVER[2],
            cap=DRIVER[3],
            lifetime=DRIVER[4],
            tolerance=TOLERANCE,
        )

        def attempt(**changes):
            a = {**base, **changes}
            driver = (a["fast"], a["slow"], a["gate"], a["cap"], a["lifetime"])
            return POLICY.deploy(
                a["pool"],
                a["amm"],
                a["feed_id"],
                a["emergency_admin"],
                oracle(a["pyth"], a["channel"]),
                config(a["fees"], driver, a["tolerance"]),
            )

        zero = "0x0000000000000000000000000000000000000000"
        for changes, reason in (
            (dict(pyth=zero), "verifier"),
            (dict(pyth=boa.env.generate_address("no code")), "verifier"),
            (dict(emergency_admin=zero), "emergency admin=0"),
            (dict(feed_id=0), "feed id"),
            (dict(channel=0), "channel"),
            (dict(channel=5), "channel"),
            (dict(fast=599), "fast half-life"),
            (dict(fast=7_201), "fast half-life"),
            (dict(slow=604_801), "slow half-life"),
            (dict(gate=WAD // 10 + 1), "trend gate"),
            (dict(cap=0), "step cap"),
            (dict(cap=60 * WAD // 10_000 + 1), "step cap"),
            (dict(lifetime=14_401), "report lifetime"),
            (dict(tolerance=WAD // 1000 + 1), "ratio tolerance"),
            (dict(fees=(10**5 - 1,) + FEES[1:]), "base fee"),
            (dict(fees=(FEES[2] + 1,) + FEES[1:]), "base fee"),
            (dict(fees=FEES[:2] + (Q // 10 + 1, FEES[3])), "fallback fee"),
            (dict(fees=(FEES[0], WAD + 1) + FEES[2:]), "capture"),
            (dict(fees=FEES[:3] + (0,)), "relax time"),
            (dict(fees=FEES[:3] + (3_601,)), "relax time"),
            (
                dict(amm=boa.loads(AMM_MOCK, verifier.address, pool.address).address),
                "amm collateral",
            ),
            (
                dict(amm=boa.loads(AMM_MOCK, pool.address, verifier.address).address),
                "amm stablecoin",
            ),
        ):
            with boa.reverts(reason):
                attempt(**changes)
        pool.eval("self.precision0 = 100")
        with boa.reverts("pool precision"):
            attempt()
        pool.eval("self.precision0 = 1")
        pool.eval("self.admin_fee = 1")
        with boa.reverts("admin fee"):
            attempt()
        pool.eval("self.admin_fee = 0")
        policy = attempt(
            fast=600,
            slow=600,
            gate=0,
            cap=60 * WAD // 10_000,
            lifetime=14_400,
            tolerance=WAD // 1000,
        )
        assert policy.owner() == boa.env.eoa
        assert attempt(lifetime=0).config()[1][4] == 0


def test_owner_sets_policy_config(setup):
    _, policy = setup
    new = config(
        (10 * 10**6, 69 * WAD // 100, 150 * 10**6, 300),
        (1_800, 3_600, WAD // 100, WAD // 1_000, 600),
        5 * 10**14,
    )
    stranger = boa.env.generate_address()
    with boa.reverts("ownable: caller is not the owner"):
        policy.set_policy_config(new, sender=stranger)
    # The setter runs the constructor's bounds on every part.
    for bad, reason in (
        (config(fees=(new[0][0], WAD + 1) + new[0][2:]), "capture"),
        (config(driver=(599,) + DRIVER[1:]), "fast half-life"),
        (config(driver=DRIVER[:3] + (0,) + DRIVER[4:]), "step cap"),
        (config(driver=DRIVER[:4] + (14_401,)), "report lifetime"),
        (config(tolerance=WAD // 1000 + 1), "ratio tolerance"),
    ):
        with boa.reverts(reason):
            policy.set_policy_config(bad)
    policy.set_policy_config(new)
    assert policy.get_logs()[-1].config == new
    assert policy.config() == new
    dao = boa.env.generate_address("dao")
    policy.transfer_ownership(dao)
    assert policy.owner() == dao
    with boa.reverts("ownable: caller is not the owner"):
        policy.set_policy_config(config())
    policy.set_policy_config(config(), sender=dao)
    assert policy.config() == config()


def test_driver_config_applies_from_the_next_touch(setup):
    pool, policy = setup
    boa.env.time_travel(seconds=1_800)
    pool.eval(f"self.last_prices = {104 * WAD}")
    before = policy.get_emas()
    driver = (900, 1_800, WAD // 1_000, 60 * WAD // 10_000, DRIVER[4])
    policy.set_policy_config(config(driver=driver))
    # No checkpoint: the new half-lives cover the whole interval since the last touch.
    lean = LeanDriver(driver=driver)
    lean.update(boa.env.evm.patch.timestamp - 1_800, (0, 0), 100 * WAD, 100 * WAD, 100 * WAD)
    fast, slow = lean.emas(104.0, boa.env.evm.patch.timestamp)
    after = policy.get_emas()
    assert after != before
    assert math.isclose(after[0] / WAD, fast, rel_tol=1e-12)
    assert math.isclose(after[1] / WAD, slow, rel_tol=1e-12)
    # trend_gate and step_cap shape the very next target.
    expected = lean.target(boa.env.evm.patch.timestamp, (0, 0), 104 * WAD)
    assert math.isclose(policy.get_price_scale() / WAD, expected, rel_tol=1e-12)
    assert policy.get_price_scale() == 100 * WAD + 5 * (100 * WAD * driver[3] // WAD)


def test_owner_sets_oracle_config(setup):
    pool, policy = setup
    candidate = [10**24 + 99 * WAD, 10**24 - 100 * WAD]
    policy.deliver_oracle_report(report(101 * WAD), value=1)
    observed = policy.report().observation_us
    assert policy.get_fee(candidate) < FEES[2]
    other = boa.loads(VERIFIER)
    for sender in (boa.env.generate_address(), EMERGENCY):  # The emergency admin only kills.
        with boa.reverts("ownable: caller is not the owner"):
            policy.set_oracle_config(oracle(other.address, 1), sender=sender)
    for bad, reason in (
        (oracle(boa.env.generate_address("no code"), 1), "verifier"),
        (oracle(other.address, 0), "channel"),
        (oracle(other.address, 5), "channel"),
        (oracle(other.address, 1, past=12_000_001), "past window"),
        (oracle(other.address, 1, future=6_000_001), "future window"),
        (oracle(other.address, 1, low=10**6 - 1), "price bounds"),
        (oracle(other.address, 1, high=10**30 + 1), "price bounds"),
        (oracle(other.address, 1, low=10**20, high=10**20 - 1), "price bounds"),
    ):
        with boa.reverts(reason):
            policy.set_oracle_config(bad)

    policy.set_oracle_config(oracle(other.address, 1))
    assert policy.get_logs()[-1].oracle == oracle(other.address, 1)
    assert policy.oracle() == oracle(other.address, 1)
    # A new source drops the stored price and keeps the replay watermark.
    assert tuple(policy.report()) == (0, observed)
    assert policy.get_fee(candidate) == FEES[2]
    assert policy.internal._observed_report() == 0
    boa.env.time_travel(seconds=1)
    with boa.reverts("channel"):
        policy.deliver_oracle_report(report(101 * WAD, channel=3), value=1)
    policy.deliver_oracle_report(report(101 * WAD, channel=1), value=1)
    assert policy.get_fee(candidate) < FEES[2]
    with boa.reverts("observation not newer"):
        policy.deliver_oracle_report(report(101 * WAD, observed, channel=1), value=1)
    # Reports now go through the new verifier: this one wants a fee of 2.
    policy.set_oracle_config(
        oracle(boa.loads(VERIFIER.replace("msg.value == 1", "msg.value == 2")).address, 1)
    )
    boa.env.time_travel(seconds=1)
    with boa.reverts("verification failed"):
        policy.deliver_oracle_report(report(101 * WAD, channel=1), value=1)


def test_kill_switch(setup):
    pool, policy = setup
    candidate = [10**24 + 99 * WAD, 10**24 - 100 * WAD]
    boa.env.time_travel(seconds=600)
    pool.eval(f"self.last_prices = {120 * WAD}")
    faulty = report(101 * WAD)
    policy.deliver_oracle_report(faulty, value=1)
    observed = policy.report().observation_us
    assert FEES[0] <= policy.get_fee(candidate) < FEES[2]
    assert policy.internal._observed_report() == 101 * WAD

    with boa.reverts("access"):
        policy.set_killed(True, sender=boa.env.generate_address())
    policy.set_killed(True, sender=EMERGENCY)
    assert policy.is_killed()
    # Zero hands the pool back its native fee and price_scale target.
    assert policy.get_fee(candidate) == policy.get_fee_with_report(candidate, 101 * WAD, 0) == 0
    assert policy.get_price_scale() == 0
    with boa.reverts("killed"):
        policy.deliver_oracle_report(report(101 * WAD), value=1)
    # The price is dropped and its time kept: callbacks run on the pool's spot.
    assert tuple(policy.report()) == (0, observed)
    assert policy.internal._observed_report() == 0
    push(policy, pool, spot=120 * WAD)
    assert policy.state().last_update_ts == boa.env.evm.patch.timestamp

    policy.set_killed(False)  # The owner may revive it, as may the emergency admin.
    assert not policy.is_killed()
    assert policy.get_price_scale() > 100 * WAD
    assert policy.get_fee(candidate) == FEES[2]  # No discount before a new report.
    assert policy.internal._observed_report() == 0
    with boa.reverts("observation not newer"):
        policy.deliver_oracle_report(faulty, value=1)  # The dropped report stays dropped.
    boa.env.time_travel(seconds=1)
    policy.deliver_oracle_report(report(101 * WAD), value=1)
    assert policy.get_fee(candidate) < FEES[2]


def test_zero_balance_view_quote_pays_fallback(setup):
    _, policy = setup
    # A synthetic quote that empties coin1 with a ~10 bp edge reaches the corrective check.
    candidate = [10**24 + 1009 * 10**21, 0]
    assert policy.get_fee_with_report(candidate, 101 * WAD, 0) == FEES[2]


# ------------------------------ LT deposit gate ------------------------------


@pytest.fixture
def market(pool_with_deposit, factory_admin, coins, user):
    """A seeded LevAMM book on a real pool, with the policy attached."""
    with boa.env.anchor():
        pool = pool_with_deposit
        market = boa.loads(MARKET_MOCK, pool.address)
        boa.deal(coins[0], market, 10**30)
        boa.deal(coins[1], market, 10**27)
        # 10 BTC and 15k USD of debt: a 2x book, booked before the gate exists.
        market.deposit(10 * WAD, 15_000 * WAD)
        # YieldBasis pools run without a pool admin fee (Twocrypto defaults to 50%).
        pool.set_fee_parameters(pool.reserved_profit_fraction(), 0, sender=factory_admin)
        policy = deploy(pool, amm=market)
        pool.set_policy_contract(policy, sender=factory_admin)
        with boa.env.prank(user):
            pool.approve(market, 2**256 - 1)
        for coin in coins:  # The fixture user deposited everything it had.
            boa.deal(coin, user, 10**25)
        yield SimpleNamespace(pool=pool, market=market, policy=policy, coins=coins)


def proportional_debt(pool, market, assets):
    """Debt keeping the book's ratio: debt == lp_minted(debt, assets) * D / C (secant)."""
    collateral, amm_debt = market.collateral_amount(), market.get_debt()

    def f(debt):
        return pool.calc_token_amount([debt, assets], True) * amm_debt // collateral

    b0 = assets * pool.balances(0) // pool.balances(1)
    b1 = f(b0)
    for _ in range(8):
        g0, g1 = b1 - b0, f(b1) - b1
        if g1 == 0 or g1 == g0:
            break
        b0, b1 = b1, b1 - g1 * (b1 - b0) // (g1 - g0)
    return b1


def admitted(pool, market, assets, debt):
    """The gate's own arithmetic, predicted from pool views (no admin fee)."""
    added_lp = pool.calc_token_amount([debt, assets], True)
    proportional = added_lp * market.get_debt() // market.collateral_amount()
    return abs(debt - proportional) * WAD <= proportional * TOLERANCE


def assert_caches_follow_ledgers(m):
    assert m.policy.cached_supply() == m.pool.user_supply()
    assert m.policy.state().xp[0] == m.pool.balances(0)
    gap = m.pool.balanceOf(m.market) - m.market.collateral_amount()
    assert m.policy.amm_surplus() == max(gap, 0)
    assert m.policy.state().D == m.pool.D()


def test_lt_deposit_must_keep_ratio(market):
    pool, amm = market.pool, market.market
    assets = WAD
    debt = proportional_debt(pool, amm, assets)
    assert admitted(pool, amm, assets, debt)
    # Any other debt is a fee-free LevAMM trade: rejected, small or large.
    for bad in (
        0,
        debt * 99 // 100,
        debt * 101 // 100,
        debt * 19995 // 20000,
        debt * 20005 // 20000,
    ):
        assert not admitted(pool, amm, assets, bad)
        with boa.reverts("LT deviation"):
            amm.deposit(assets, bad)
    # Around the band the contract agrees with the predicted arithmetic.
    for step in range(-30, 31, 3):
        candidate = debt + debt * step // 1_000_000
        with boa.env.anchor():
            if admitted(pool, amm, assets, candidate):
                amm.deposit(assets, candidate)
            else:
                with boa.reverts("LT deviation"):
                    amm.deposit(assets, candidate)

    ratio_before = amm.get_debt() * WAD // amm.collateral_amount()
    amm.deposit(assets, debt)
    ratio_after = amm.get_debt() * WAD // amm.collateral_amount()
    assert abs(ratio_after - ratio_before) * WAD <= ratio_before * TOLERANCE
    assert_caches_follow_ledgers(market)
    # Leaving is not gated.
    amm.withdraw(WAD // 3)
    assert_caches_follow_ledgers(market)


def test_lt_deposit_during_a_rebalance(market, user):
    pool, amm, coins = market.pool, market.market, market.coins
    # Move the spot and let the EMAs follow, so that the next touch rebalances.
    boa.deal(coins[1], user, 100 * WAD)
    with boa.env.prank(user):
        pool.exchange(1, 0, 100 * WAD, 0)
    boa.env.time_travel(seconds=1_800)
    scale = pool.price_scale()
    debt = proportional_debt(pool, amm, WAD)
    with boa.reverts("LT deviation"):
        amm.deposit(WAD, debt * 1_001 // 1_000)
    amm.deposit(WAD, debt)
    assert pool.price_scale() != scale  # tweak_price rebalanced inside the deposit.
    assert_caches_follow_ledgers(market)


def test_lt_gate_with_an_admin_fee(market, factory_admin):
    pool, amm = market.pool, market.market
    rpf = pool.reserved_profit_fraction()
    # Governance turns on a pool admin fee, which the policy is not told about.
    pool.set_fee_parameters(rpf, 5 * 10**9, sender=factory_admin)
    for _ in range(3):  # Swaps make the pool accrue admin fees in both coins.
        boa.deal(market.coins[1], boa.env.eoa, 10 * WAD)
        market.coins[1].approve(pool, 2**256 - 1)
        pool.exchange(1, 0, 10 * WAD, 0)
        boa.env.time_travel(seconds=600)
    assert pool.admin_balances(0) > 0
    # An add now moves a slice of the deposit to admin_balances that the gate does
    # not see. In this imbalanced pool it is about 1.07 bp of the debt, so the exact
    # deposit fails the 1 bp tolerance (a deposit borrowing about that much more would
    # pass). Larger deviations still fail.
    debt = proportional_debt(pool, amm, WAD)
    with boa.reverts("LT deviation"):
        amm.deposit(WAD, debt)
    with boa.reverts("LT deviation"):
        amm.deposit(WAD, debt * 10_010 // 10_000)
    # Borrowing about the unseen slice more passes: the bias is this add's own admin
    # charge, bounded by it plus the tolerance.
    amm.deposit(WAD, debt * 10_002 // 10_000)
    assert_caches_follow_ledgers(market)
    # Back at zero, with the accrued admin balances still there, deposits are measured exactly.
    pool.set_fee_parameters(rpf, 0, sender=factory_admin)
    debt = proportional_debt(pool, amm, WAD)
    with boa.reverts("LT deviation"):
        amm.deposit(WAD, debt * 10_002 // 10_000)
    amm.deposit(WAD, debt)
    assert_caches_follow_ledgers(market)


def test_other_pool_operations_are_not_gated(market, user):
    pool, amm, coins = market.pool, market.market, market.coins
    with boa.env.prank(user):
        # An add at any ratio that mints to its caller is not an LT deposit.
        lp = pool.add_liquidity([1_000 * WAD, 0], 0)
        assert_caches_follow_ledgers(market)
        # VirtualPool: add to itself, then sell the LP to the LevAMM.
        amm.buy_lp(lp)
        assert_caches_follow_ledgers(market)
        boa.deal(coins[0], user, 10_000 * WAD)
        pool.exchange(0, 1, 10_000 * WAD, 0)
        assert_caches_follow_ledgers(market)
        pool.remove_liquidity(pool.balanceOf(user) // 100, [0, 0])
        assert_caches_follow_ledgers(market)
        pool.remove_liquidity_one_coin(pool.balanceOf(user) // 100, 0, 0)
        assert_caches_follow_ledgers(market)
        # Donation: user supply is unchanged.
        pool.add_liquidity([100 * WAD, 0], 0, "0x0000000000000000000000000000000000000000", True)
        assert_caches_follow_ledgers(market)


def test_lp_gift_misclassifies_adds_until_sync(market, user):
    pool, amm, policy = market.pool, market.market, market.policy
    gift = 100 * WAD  # About 8k USD of LP; the add below mints about 13 LP.
    with boa.env.prank(user):
        pool.transfer(amm, gift)
        # The gift makes a smaller add to the user look like an LT deposit.
        with boa.reverts("LT deviation"):
            pool.add_liquidity([1_000 * WAD, 0], 0)
    # A gift never hides an LT deposit: an off-ratio one still fails.
    debt = proportional_debt(pool, amm, WAD)
    with boa.reverts("LT deviation"):
        amm.deposit(WAD, debt * 101 // 100)

    policy.sync(sender=boa.env.generate_address())
    assert policy.amm_surplus() == gift
    with boa.env.prank(user):
        pool.add_liquidity([1_000 * WAD, 0], 0)
    with boa.reverts("LT deviation"):
        amm.deposit(WAD, debt * 101 // 100)
    amm.deposit(WAD, proportional_debt(pool, amm, WAD))
    assert_caches_follow_ledgers(market)


def test_sync_refuses_inside_a_pool_operation(setup):
    pool, policy = setup
    pool.eval("self.locked = True")
    with boa.reverts("locked"):
        policy.sync()


def test_sync_before_attachment_leaves_the_gate_unseeded(market, user, factory_admin):
    pool, amm = market.pool, market.market
    fresh = deploy(pool, amm=amm)
    fresh.sync(sender=boa.env.generate_address())
    assert fresh.cached_supply() == 0 and list(fresh.state().xp) == [0, 0]
    # Before the attachment vote lands: an LT deposit, and an LP gift of its size
    # that would make it look like an LT deposit against no recorded stable ledger.
    supply = pool.user_supply()
    amm.deposit(WAD, proportional_debt(pool, amm, WAD))
    with boa.env.prank(user):
        pool.transfer(amm, pool.user_supply() - supply)
    pool.set_policy_contract(fresh, sender=factory_admin)
    assert_caches_follow_ledgers(SimpleNamespace(pool=pool, market=amm, policy=fresh))


@pytest.mark.parametrize("repair", ["sync", "revive"])
def test_resync_repairs_a_failed_removal_callback(market, user, repair):
    pool, amm, policy = market.pool, market.market, market.policy
    # A balanced removal whose best-effort callback fails (here: the policy's
    # code reverts for the duration of the removal, its storage untouched).
    working = boa.env.get_code(policy.address)
    failing = boa.loads(
        "@external\ndef update_pool_state(a: uint256[2], b: uint256, c: uint256, d: uint256, "
        'e: uint256, f: uint256, g: uint256, h: uint256):\n    raise "down"'
    )
    boa.env.set_code(policy.address, boa.env.get_code(failing.address))
    try:
        pool.remove_liquidity(WAD, [0, 0], sender=user, gas=2_000_000)
    finally:
        boa.env.set_code(policy.address, working)
    assert policy.state().xp[0] > pool.balances(0) and policy.cached_supply() > pool.user_supply()
    if repair == "sync":
        policy.sync(sender=boa.env.generate_address())
    else:
        policy.set_killed(True, sender=EMERGENCY)
        policy.set_killed(False, sender=EMERGENCY)
    assert_caches_follow_ledgers(market)
    scale = pool.price_scale()
    assert policy.state().xp[1] == pool.balances(1) * pool.precisions()[1] * scale // WAD
    assert policy.state().price_scale == scale
    # The gate checks against the repaired baselines: the book's ratio and nothing else.
    debt = proportional_debt(pool, amm, WAD)
    with boa.reverts("LT deviation"):
        amm.deposit(WAD, debt * 10_002 // 10_000)
    amm.deposit(WAD, debt)
    assert_caches_follow_ledgers(market)


def test_removals_do_not_read_the_levamm(market, user):
    pool, amm, _ = market.pool, market.market, market.policy
    online = boa.env.get_code(amm.address)
    offline = boa.loads(
        '@external\n@view\ndef collateral_amount() -> uint256:\n    raise "offline"'
    )
    boa.env.set_code(amm.address, boa.env.get_code(offline.address))
    try:
        with boa.env.prank(user):
            pool.remove_liquidity(pool.balanceOf(user) // 100, [0, 0])
            pool.remove_liquidity_one_coin(
                pool.balanceOf(user) // 100, 0, 0
            )  # Its callback must succeed.
    finally:
        boa.env.set_code(amm.address, online)
    assert_caches_follow_ledgers(market)


def test_ratio_tolerance_is_settable(market):
    pool, amm, policy = market.pool, market.market, market.policy
    debt = proportional_debt(pool, amm, WAD)
    off = debt * 10_005 // 10_000  # 5 bp above the book's ratio
    with boa.reverts("LT deviation"):
        amm.deposit(WAD, off)
    policy.set_policy_config(config(tolerance=10 * TOLERANCE))
    amm.deposit(WAD, off)
    assert_caches_follow_ledgers(market)


def test_gate_is_off_while_killed_and_rereads_ledgers_on_revival(market, user):
    pool, amm, policy = market.pool, market.market, market.policy
    policy.set_killed(True, sender=EMERGENCY)
    # Killed: an off-ratio LT deposit goes through and the gate's caches go stale.
    amm.deposit(WAD, proportional_debt(pool, amm, WAD) * 101 // 100)
    with boa.env.prank(user):
        pool.add_liquidity([1_000 * WAD, 0], 0)
        pool.exchange(0, 1, 1_000 * WAD, 0)
        pool.transfer(amm, 10**15)  # An LP gift to the LevAMM.
    amm.withdraw(WAD // 10)
    assert policy.cached_supply() != pool.user_supply()
    # Reviving re-reads the ledgers, so the gate checks the next deposit against them.
    policy.set_killed(False, sender=EMERGENCY)
    assert_caches_follow_ledgers(market)
    debt = proportional_debt(pool, amm, WAD)
    with boa.reverts("LT deviation"):
        amm.deposit(WAD, debt * 101 // 100)
    amm.deposit(WAD, debt)
    assert_caches_follow_ledgers(market)


def test_balanced_removal_callback_fits_its_gas(market):
    """The pool forwards 300k gas to the best-effort removal callback."""
    pool, amm, policy = market.pool, market.market, market.policy
    amm.withdraw(WAD // 10)
    assert_caches_follow_ledgers(market)  # The real callback succeeded.

    # Worst removal path: user supply changed, every slot cold.
    policy.eval(f"self.cached_supply = {pool.user_supply() + 1}")
    xp = list(policy.state().xp)
    args = (xp, pool.price_scale(), pool.price_oracle(), pool.last_prices(), WAD, WAD, pool.D(), 0)
    boa.env.time_travel(seconds=3_600)
    policy.update_pool_state(*args, sender=pool.address, gas=300_000)
    used = policy._computation.get_gas_used()
    # boa keeps slots warm and dirty across calls, so add what a fresh transaction
    # pays on top: a cold read of every slot the callback touches (14 policy: state 7,
    # is_killed, report 2, report_lifetime, 2 half-lives, cached_supply; 2 pool), and a
    # full reset for the 8 slots it can write. A removal reads nothing from the LevAMM.
    worst = used + 16 * 2_100 + 8 * 2_900
    assert worst < 150_000, (used, worst)


# --------------------------------- Real pool ---------------------------------


@pytest.mark.parametrize("coin_in, report_price", [(0, 1510), (1, 1490), (0, 1800), (1, 1200)])
def test_real_pool_quote_swap_and_withdrawal(market, user, coin_in, report_price):
    pool, policy, coins = market.pool, market.policy, market.coins
    fallback = FEES[2]
    policy.deliver_oracle_report(report(report_price * WAD), value=1)
    boa.env.time_travel(blocks=1, block_delta=1)
    coin_out = 1 - coin_in
    dx = 100 * WAD if coin_in == 0 else WAD // 10
    boa.deal(coins[coin_in], user, dx)
    expected = pool.get_dy(coin_in, coin_out, dx)
    with boa.env.prank(user):
        assert pool.exchange(coin_in, coin_out, dx, expected) == expected
    assert policy.state().D == pool.D()
    # Toward the report the swap is discounted; the reverse trade pays fallback.
    boa.deal(coins[coin_out], user, 10 * dx)
    xp_now = list(policy.state().xp)
    assert policy.get_fee(xp_now) == fallback
    with boa.env.prank(user):
        pool.remove_liquidity(pool.balanceOf(user) // 1000, [0, 0])
        assert policy.state().D == pool.D()
        pool.remove_liquidity_one_coin(pool.balanceOf(user) // 1000, 1, 0)
        assert policy.state().D == pool.D()
    assert_caches_follow_ledgers(market)


def test_amplification_ramp(market, user, factory_admin):
    """During an A ramp a swap pays fallback_fee while a get_dy quote may not."""
    pool, policy, coins = market.pool, market.policy, market.coins
    # At equal value D is the same for any A, so imbalance the pool first: then
    # the ramp makes the pool re-solve D before it asks for the fee.
    boa.deal(coins[1], user, 300 * WAD)
    with boa.env.prank(user):
        pool.exchange(1, 0, 300 * WAD, 0)
    end = boa.env.evm.patch.timestamp + 86_400
    pool.ramp_A_gamma(pool.A() * 2, pool.gamma(), end, sender=factory_admin)
    dx = 1_000 * WAD

    def swap():
        # A report beyond the spot: buying coin1 with coin0 is corrective.
        policy.deliver_oracle_report(report(pool.last_prices() * 1003 // 1000), value=1)
        boa.deal(coins[0], user, dx)
        quote = pool.get_dy(0, 1, dx)
        with boa.env.prank(user):
            received = pool.exchange(0, 1, dx, 0)
        fee = [log for log in pool.get_logs() if hasattr(log, "tokens_bought")][-1].fee
        return quote, received, fee * Q // (received + fee)

    boa.env.time_travel(seconds=3_600)
    with boa.env.anchor():
        quote, received, rate = swap()
        # The swap re-solved D and paid fallback; the quote kept the old D and its discount.
        assert FEES[2] - 1 <= rate <= FEES[2]
        assert received < quote
    # After the ramp's last checkpoint and a sync(), quotes and swaps agree again.
    boa.env.time_travel(seconds=86_400)
    boa.deal(coins[1], user, WAD)
    with boa.env.prank(user):
        pool.exchange(1, 0, WAD // 100, 0)
    policy.sync()
    assert policy.cached_A() == pool.A()
    quote, received, rate = swap()
    assert received == quote
    assert rate < FEES[2] - 1


# -------------------------------- Deployment ---------------------------------


def test_deployment_script(market):
    pool, amm = market.pool, market.market
    verifier = boa.loads(VERIFIER)
    dao = boa.env.generate_address("yb dao")
    cfg = SimpleNamespace(
        pool=pool.address,
        amm=amm.address,
        feed_id=2,
        oracle=oracle(verifier.address),
        emergency_admin=EMERGENCY,
        owner=dao,
        config=config(),
        policy=None,
    )
    policy = deploy_script(POLICY, cfg)
    assert policy.owner() == dao
    assert policy.config() == config()
    assert (policy.POOL(), policy.AMM(), policy.oracle()) == (
        pool.address,
        amm.address,
        oracle(verifier.address),
    )
    assert policy.ctor_calldata
    # A resumed run reuses the deployment and checks it again.
    cfg.policy = policy.address
    assert deploy_script(POLICY, cfg).address == policy.address
    # A run interrupted before the ownership transfer finishes it on resume.
    pending = POLICY.deploy(*constructor_args(cfg))
    assert pending.owner() == boa.env.eoa
    cfg.policy = pending.address
    assert deploy_script(POLICY, cfg).owner() == dao
    cfg.policy = policy.address
    cfg.config = config(fees=FEES[:3] + (FEES[3] + 1,))
    with pytest.raises(RuntimeError):
        deploy_script(POLICY, cfg)


# --------------------------------- Fork tests --------------------------------


@pytest.mark.skipif(os.getenv("ORACLIZED_PYTH_FORK") != "1", reason="opt-in RPC test")
def test_signed_report_against_pinned_pyth_verifier():
    pin = PYTH_PIN
    with boa.swap_env(boa.Env()):
        boa.fork(os.environ["ETH_RPC_URL"], block_identifier=pin.block, cache_dir=None)
        assert boa.env.evm.patch.chain_id == pin.chain_id
        assert boa.env.evm.patch.timestamp == pin.block_timestamp
        code_hash = "0x" + keccak(boa.env.get_code(pin.implementation)).hex()
        assert code_hash == pin.implementation_codehash
        # Ingress-only pool stub. The real-pool tests above use the real pool and math.
        pool = boa.loads(POOL_MOCK)
        policy = POLICY.deploy(
            pool.address,
            boa.loads(AMM_MOCK, pool.address, pool.address).address,
            2,
            EMERGENCY,
            oracle(pin.verifier),
            config(),
        )
        boa.env.set_balance(boa.env.eoa, WAD)
        signed = SIGNED_REPORT
        fee = policy.verification_fee()
        assert fee == pin.verification_fee_wei
        # Pyth rejects underpayment; its excess refund cannot enter this policy.
        for incorrect_fee in (fee - 1, fee + 1):
            with boa.reverts():
                policy.deliver_oracle_report(signed, value=incorrect_fee)
        policy.deliver_oracle_report(signed, value=fee)
        assert tuple(policy.report()) == (SIGNED_PRICE, SIGNED_OBSERVATION_US)
        with boa.reverts("observation not newer"):
            policy.deliver_oracle_report(signed, value=fee)
        with boa.reverts():
            policy.deliver_oracle_report(
                signed[:20] + bytes([signed[20] ^ 1]) + signed[21:], value=fee
            )


# ABI-only stubs for the production YieldBasis market.
LT_STUB = """
@external
def deposit(assets: uint256, debt: uint256, min_shares: uint256, receiver: address) -> uint256:
    return 0

@external
def withdraw(shares: uint256, min_assets: uint256, receiver: address) -> uint256:
    return 0

@external
def emergency_withdraw(shares: uint256, receiver: address, owner: address) -> (uint256, int256):
    return 0, 0

@external
@view
def admin() -> address:
    return empty(address)
"""
AMM_STUB = """
@external
@view
def collateral_amount() -> uint256:
    return 0

@external
@view
def get_debt() -> uint256:
    return 0

@external
@view
def fee() -> uint256:
    return 0
"""
VPOOL_STUB = """
@external
def exchange(i: uint256, j: uint256, in_amount: uint256, min_out: uint256) -> uint256:
    return 0
"""
ERC20_STUB = """
@external
def approve(spender: address, amount: uint256) -> bool:
    return True

@external
@view
def balanceOf(account: address) -> uint256:
    return 0

@external
@payable
def deposit():
    pass
"""
TOTAL_SUPPLY_STUB = """
@external
@view
def totalSupply() -> uint256:
    return 0
"""
FORK_BLOCK = 26_206_129
VPOOL_ADDRESS = "0x772cfF0BE38A6ED31aeAe479cbcb26D54B8404CF"
OWNER_PROXY = "0x97aA696e37659Fb4f0B53824246d802Df40E980A"  # Pool admin (Curve DAO).


@pytest.mark.skipif(os.getenv("ORACLIZED_YB_FORK") != "1", reason="opt-in RPC test")
def test_production_market_fork():
    """Deploy with the production CONFIG, attach, and run real LT and pool flows."""
    with boa.swap_env(boa.Env()):
        boa.fork(os.environ["ETH_RPC_URL"], block_identifier=FORK_BLOCK)
        deployer = boa.env.generate_address()
        boa.env.eoa = deployer
        policy = deploy_script(POLICY, SimpleNamespace(**{**vars(PRODUCTION), "policy": None}))
        assert policy.owner() == PRODUCTION.owner
        assert boa.env.get_code(PRODUCTION.owner) and boa.env.get_code(PRODUCTION.emergency_admin)

        pool = POOL_DEPLOYER.at(PRODUCTION.pool)
        amm = boa.loads_partial(AMM_STUB).at(PRODUCTION.amm)
        lt = boa.loads_partial(LT_STUB).at(PRODUCTION.lt)
        vpool = boa.loads_partial(VPOOL_STUB).at(VPOOL_ADDRESS)
        weth = boa.loads_partial(ERC20_STUB).at(pool.coins(1))
        crvusd = boa.loads_partial(ERC20_STUB + TOTAL_SUPPLY_STUB).at(pool.coins(0))
        assert pool.POLICY() == "0x0000000000000000000000000000000000000000"
        # The printed calls: the Curve vote (attach, RPF) and YieldBasis' LevAMM fee.
        # LT accepts its admin, the YieldBasis factory, or that factory's admin.
        lt_admin = boa.loads_partial(LT_STUB).at(lt.admin()).admin()
        for target, data, _ in companion_calls(policy.address, PRODUCTION, pool.admin_fee()):
            boa.env.raw_call(
                target, sender=OWNER_PROXY if target == pool.address else lt_admin, data=data
            )
        assert pool.POLICY() == policy.address
        assert pool.reserved_profit_fraction() == PRODUCTION.reserved_profit_fraction
        assert pool.admin_fee() == 0
        assert amm.fee() == PRODUCTION.amm_fee
        m = SimpleNamespace(pool=pool, market=amm, policy=policy)
        assert_caches_follow_ledgers(m)
        assert policy.amm_surplus() == 0
        scale = pool.price_scale()
        assert abs(policy.get_price_scale() - scale) <= 5 * scale * PRODUCTION.config[1][3] // WAD

        user = boa.env.generate_address()
        boa.env.set_balance(user, 1_001 * WAD)
        weth.deposit(value=1_000 * WAD, sender=user)  # WETH: wrap ETH.
        # emergency_withdraw pulls crvUSD from the caller when the debt exceeds the LP's share.
        boa.deal(crvusd, user, 100_000 * WAD)
        assets = 10 * WAD
        with boa.env.prank(user):
            crvusd.approve(lt, 2**256 - 1)
            weth.approve(lt, 2**256 - 1)
            weth.approve(vpool, 2**256 - 1)
            weth.approve(pool, 2**256 - 1)
            debt = proportional_debt(pool, amm, assets)
            # The frontend's debt (assets * price_oracle) and any off-ratio debt fail.
            for bad in (assets * pool.price_oracle() // WAD, debt * 10_003 // 10_000):
                with boa.reverts("LT deviation"):
                    lt.deposit(assets, bad, 0, user)
            shares = lt.deposit(assets, debt, 0, user)
            assert shares > 0
            assert_caches_follow_ledgers(m)
            # Leaving is not gated: the fixed-out and the balanced (best-effort) paths.
            lt.withdraw(shares // 2, 0, user)
            assert_caches_follow_ledgers(m)
            lt.emergency_withdraw(shares - shares // 2, user, user)
            assert_caches_follow_ledgers(m)
            # VirtualPool's WETH -> crvUSD adds liquidity to itself: not an LT deposit.
            assert vpool.exchange(1, 0, WAD, 0) > 0
            assert_caches_follow_ledgers(m)
            # Without a report a swap pays fallback_fee.
            fee_before = pool.fee()
            assert fee_before == PRODUCTION.config[0][2]
            pool.exchange(1, 0, WAD, 0)
            assert_caches_follow_ledgers(m)

        policy.set_killed(True, sender=PRODUCTION.emergency_admin)
        assert pool.fee() != PRODUCTION.config[0][2]  # Native mid/out curve.
        with boa.env.prank(user):
            pool.exchange(1, 0, WAD, 0)
            # Killed: the LT gate is off.
            lt.deposit(assets, proportional_debt(pool, amm, assets) * 10_003 // 10_000, 0, user)
        # Reviving re-reads the ledgers and the gate is back.
        policy.set_killed(False, sender=PRODUCTION.emergency_admin)
        assert_caches_follow_ledgers(m)
        with boa.env.prank(user):
            debt = proportional_debt(pool, amm, assets)
            with boa.reverts("LT deviation"):
                lt.deposit(assets, debt * 10_003 // 10_000, 0, user)
            lt.deposit(assets, debt, 0, user)
        assert_caches_follow_ledgers(m)
