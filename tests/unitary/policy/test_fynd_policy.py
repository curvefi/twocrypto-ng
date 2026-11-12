"""FyndPolicy on a real Twocrypto pool: a default fee, and signed grants for Fynd.

The pool is the pilot's shape: a 6-decimal USD coin and WETH, A = 10, reserved
profit fraction 25% and admin fee 50%. A router stand-in arms grants and swaps in
one transaction, as Fynd's router does. Grants are signed with eth_account's
EIP-712 encoder, which checks the policy's hashing independently.
"""

import boa
import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from tests.conftest import _deploy_pool
from tests.utils.constants import ERC20_DEPLOYER, MATH_DEPLOYER, POOL_DEPLOYER

POLICY = boa.load_partial("contracts/main/FyndPolicy.vy")

WAD = 10**18
FEE_PRECISION = 10**10
DEFAULT_FEE = 100_000_000  # 1%
MIN_GRANT_FEE = 10**6  # 1 bp
GRANT_FEE = 5 * 10**6  # 5 bp
RPF = 2_500_000_000  # reserved profit fraction 25%
ADMIN_FEE = 5_000_000_000  # 50%
PRICE = 2_000 * WAD
CONTROLLER = Account.from_key(b"\x01" * 32)
EMERGENCY = boa.env.generate_address("emergency")

ROUTER = """
struct Grant:
    taker: address
    coin_in: uint8
    min_amount_in: uint256
    max_amount_in: uint256
    fee: uint256
    nonce: uint64
    deadline: uint32

interface Policy:
    def submit_grant(grant: Grant, signature: Bytes[65], taker: address): nonpayable

interface Pool:
    def POLICY() -> address: view
    def coins(i: uint256) -> address: view
    def exchange(i: uint256, j: uint256, dx: uint256, min_dy: uint256, receiver: address) -> uint256: nonpayable
    def add_liquidity(amounts: uint256[2], min_mint_amount: uint256, receiver: address) -> uint256: nonpayable

interface ERC20:
    def approve(spender: address, amount: uint256) -> bool: nonpayable

POOL: immutable(Pool)

@deploy
def __init__(pool: Pool):
    POOL = pool
    for i: uint256 in range(2):
        extcall ERC20(staticcall pool.coins(i)).approve(pool.address, max_value(uint256))

@internal
def _arm(grant: Grant, signature: Bytes[65]):
    extcall Policy(staticcall POOL.POLICY()).submit_grant(grant, signature, msg.sender)

@external
def swap(grant: Grant, signature: Bytes[65], i: uint256, j: uint256, dx: uint256, swaps: uint256) -> uint256:
    self._arm(grant, signature)
    dy: uint256 = 0
    for k: uint256 in range(swaps, bound=2):
        dy += extcall POOL.exchange(i, j, dx, 0, msg.sender)
    return dy

@external
def add(grant: Grant, signature: Bytes[65], amounts: uint256[2]) -> uint256:
    self._arm(grant, signature)
    return extcall POOL.add_liquidity(amounts, 0, msg.sender)

@external
def arm_twice(grant: Grant, signature: Bytes[65], other: Grant, other_signature: Bytes[65]):
    self._arm(grant, signature)
    self._arm(other, other_signature)

@external
def plain_swap(i: uint256, j: uint256, dx: uint256, swaps: uint256) -> uint256:
    dy: uint256 = 0
    for k: uint256 in range(swaps, bound=2):
        dy += extcall POOL.exchange(i, j, dx, 0, msg.sender)
    return dy

@external
def plain_add(amounts: uint256[2]) -> uint256:
    return extcall POOL.add_liquidity(amounts, 0, msg.sender)
"""


# ---------------------------------- Fixtures ----------------------------------


def deploy_policy(pool_contract, router_contract, **overrides):
    args = dict(
        pool=pool_contract.address,
        controller=CONTROLLER.address,
        router=router_contract.address,
        emergency_admin=EMERGENCY,
        default_fee=DEFAULT_FEE,
        min_fee=MIN_GRANT_FEE,
    )
    args.update(overrides)
    return POLICY.deploy(*args.values())


@pytest.fixture(scope="module")
def world(factory, factory_admin, deployer):
    usd = ERC20_DEPLOYER.deploy("USD", "USD", 6)
    weth = ERC20_DEPLOYER.deploy("WETH", "WETH", 18)
    params = {
        "A": 100_000,  # A = 10
        "gamma": 145000000000000,  # unused by StableswapMath
        "mid_fee": 50_000_000,
        "out_fee": 50_000_000,
        "fee_gamma": 230000000000000,
        "adjustment_step_min": 10**12,
        "adjustment_step_max": 5 * 10**15,
        "ma_time": 866,
        "initial_prices": [WAD, PRICE],
    }
    pool = POOL_DEPLOYER.at(_deploy_pool(factory, params, [usd, weth], deployer))
    lp = boa.env.generate_address("lp")
    amounts = [2_000_000 * 10**6, 1_000 * WAD]
    for coin, amount in zip((usd, weth), amounts):
        boa.deal(coin, lp, amount)
        coin.approve(pool, 2**256 - 1, sender=lp)
    pool.add_liquidity(amounts, 0, sender=lp)
    pool.set_fee_parameters(RPF, ADMIN_FEE, sender=factory_admin)

    router = boa.loads(ROUTER, pool.address)
    policy = deploy_policy(pool, router)
    pool.set_policy_contract(policy, sender=factory_admin)

    taker = boa.env.generate_address("taker")
    for coin, amount in zip((usd, weth), (10**15, 10**25)):
        boa.deal(coin, router, amount)
        boa.deal(coin, taker, amount)
        coin.approve(pool, 2**256 - 1, sender=taker)
    return pool, policy, router, taker


@pytest.fixture
def env(world):
    with boa.env.anchor():
        yield world


# ---------------------------------- Helpers -----------------------------------

_nonce = iter(range(10**6))


def now():
    return boa.env.evm.patch.timestamp


def make_grant(taker, coin_in, dx, fee=GRANT_FEE, nonce=None, deadline=None, lo=None, hi=None):
    """A Grant tuple admitting dx of coin_in; coin1 inputs can read 1 wei low."""
    return (
        taker,
        coin_in,
        dx - 1 if lo is None else lo,
        dx if hi is None else hi,
        fee,
        next(_nonce) if nonce is None else nonce,
        now() + 60 if deadline is None else deadline,
    )


def sign(policy, grant, key=CONTROLLER.key):
    fields = ["taker", "coin_in", "min_amount_in", "max_amount_in", "fee", "nonce", "deadline"]
    types = ["address", "uint8", "uint256", "uint256", "uint256", "uint64", "uint32"]
    message = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Grant": [{"name": n, "type": t} for n, t in zip(fields, types)],
        },
        "primaryType": "Grant",
        "domain": {
            "name": "FyndPolicy",
            "version": "1",
            "chainId": boa.env.evm.patch.chain_id,
            "verifyingContract": str(policy.address),
        },
        "message": {n: (str(v) if n == "taker" else v) for n, v in zip(fields, grant)},
    }
    return bytes(Account.sign_message(encode_typed_data(full_message=message), key).signature)


def prefee_dy(pool, i, j, dx):
    """The pool's output before its fee, as Twocrypto._exchange computes it (no ramp)."""
    math = MATH_DEPLOYER.at(pool.MATH())
    precisions = pool.precisions()
    price_scale = pool.price_scale()
    balances = [pool.balances(0), pool.balances(1)]
    balances[i] += dx
    xp = [balances[0] * precisions[0], balances[1] * precisions[1] * price_scale // WAD]
    y = math.get_y(pool.A(), pool.gamma(), xp, pool.D(), j)[0]
    dy = xp[j] - y - 1
    if j == 1:
        dy = dy * WAD // price_scale
    return dy // precisions[j]


def charged(pool, fee, i, j, dx):
    """What a swap of dx receives at this fee."""
    dy = prefee_dy(pool, i, j, dx)
    return dy - fee * dy // FEE_PRECISION


def granted_swap(env, i, j, dx, swaps=1, **grant_kwargs):
    _, policy, router, taker = env
    grant = make_grant(taker, i, dx, **grant_kwargs)
    return router.swap(grant, sign(policy, grant), i, j, dx, swaps, sender=taker)


# ----------------------------------- Setup ------------------------------------


def test_deployment(env):
    pool, policy, router, _ = env
    assert (policy.POOL(), policy.controller(), policy.router(), policy.EMERGENCY_ADMIN()) == (
        pool.address,
        CONTROLLER.address,
        router.address,
        EMERGENCY,
    )
    assert (policy.default_fee(), policy.min_fee()) == (DEFAULT_FEE, MIN_GRANT_FEE)
    assert policy.owner() == boa.env.eoa and not policy.is_killed()
    assert policy.IS_FYND_EXCLUSIVE() and policy.get_price_scale() == 0
    # EIP-5267 describes the signing domain.
    _, name, version, chain_id, verifying, _, _ = policy.eip712Domain()
    assert (name, version, chain_id, verifying) == (
        "FyndPolicy",
        "1",
        boa.env.evm.patch.chain_id,
        policy.address,
    )


def test_constructor_checks(env):
    pool, _, router, _ = env
    zero = "0x0000000000000000000000000000000000000000"
    for overrides, reason in (
        (dict(pool=boa.env.generate_address("no code")), "pool"),
        (dict(emergency_admin=zero), "emergency admin=0"),
        (dict(controller=zero), "controller=0"),
        (dict(router=zero), "router=0"),
        (dict(min_fee=10**5 - 1), "min fee"),
        (dict(min_fee=DEFAULT_FEE + 1), "min fee"),
        (dict(default_fee=FEE_PRECISION // 10 + 1, min_fee=10**5), "default fee"),
    ):
        with boa.reverts(reason):
            deploy_policy(pool, router, **overrides)


# -------------------------------- Default fee ---------------------------------


@pytest.mark.parametrize("i", [0, 1])
def test_public_swap_pays_default_fee(env, i):
    pool, _, _, taker = env
    dx = [5_000 * 10**6, 2 * WAD][i]
    expected = charged(pool, DEFAULT_FEE, i, 1 - i, dx)
    assert pool.get_dy(i, 1 - i, dx) == expected
    assert pool.exchange(i, 1 - i, dx, 0, sender=taker) == expected


def test_liquidity_operations_pay_default_fee(env):
    _, policy, router, taker = env
    amounts = [10_000 * 10**6, 0]
    with boa.env.anchor():
        plain = router.plain_add(amounts, sender=taker)
    # A grant does not discount a deposit, even in its own direction.
    grant = make_grant(taker, 0, amounts[0])
    assert router.add(grant, sign(policy, grant), amounts, sender=taker) == plain


# --------------------------------- Grants -------------------------------------


@pytest.mark.parametrize("i", [0, 1])
def test_granted_swap_pays_granted_fee(env, i):
    pool, _, _, _ = env
    dx = [5_000 * 10**6, 2 * WAD][i]
    expected = charged(pool, GRANT_FEE, i, 1 - i, dx)
    assert granted_swap(env, i, 1 - i, dx) == expected


def test_granted_fee_ignores_the_market(env):
    pool, _, _, taker = env
    # Push the pool's WETH price about 3% down with a public sale; buying WETH
    # back is then a bargain, and a grant still pays only its signed fee: the
    # policy has no price to check it against.
    pool.exchange(1, 0, 150 * WAD, 0, sender=taker)
    dx = 50_000 * 10**6
    expected = charged(pool, GRANT_FEE, 0, 1, dx)
    assert granted_swap(env, 0, 1, dx) == expected


def test_min_fee_binds(env):
    pool, _, _, _ = env
    dx = 2 * WAD
    expected = charged(pool, MIN_GRANT_FEE, 1, 0, dx)
    assert granted_swap(env, 1, 0, dx, fee=0) == expected


def test_grant_covers_one_swap(env):
    _, _, router, taker = env
    dx = 2 * WAD
    with boa.env.anchor():
        first = granted_swap(env, 1, 0, dx)
        second = router.plain_swap(1, 0, dx, 1, sender=taker)
    assert granted_swap(env, 1, 0, dx, swaps=2) == first + second


def test_one_armed_grant_per_transaction(env):
    _, policy, router, taker = env
    grant, other = make_grant(taker, 1, WAD), make_grant(taker, 1, WAD)
    with boa.reverts("armed"):
        router.arm_twice(grant, sign(policy, grant), other, sign(policy, other), sender=taker)


def test_only_the_router_arms(env):
    _, policy, router, taker = env
    grant = make_grant(taker, 1, WAD)
    with boa.reverts("router"):
        policy.submit_grant(grant, sign(policy, grant), taker, sender=taker)
    # The grant names its taker: a copied grant fails for anyone else.
    stolen = make_grant(boa.env.generate_address("someone"), 1, WAD)
    with boa.reverts("taker"):
        router.swap(stolen, sign(policy, stolen), 1, 0, WAD, 1, sender=taker)


def test_signature_must_be_the_controllers(env):
    pool, policy, router, taker = env
    grant = make_grant(taker, 1, WAD)
    with boa.reverts("signature"):
        router.swap(grant, sign(policy, grant, key=b"\x02" * 32), 1, 0, WAD, 1, sender=taker)
    # Any changed field breaks the signature: here a higher fee became lower.
    tampered = (*grant[:4], 1, *grant[5:])
    with boa.reverts("signature"):
        router.swap(tampered, sign(policy, grant), 1, 0, WAD, 1, sender=taker)
    # The domain binds the grant to one policy.
    other = deploy_policy(pool, router)
    with boa.reverts("signature"):
        router.swap(grant, sign(other, grant), 1, 0, WAD, 1, sender=taker)
    with boa.reverts():  # not a signature at all
        router.swap(grant, bytes(65), 1, 0, WAD, 1, sender=taker)


def test_nonces_work_once(env):
    _, policy, router, taker = env
    for nonce in (255, 256):
        grant = make_grant(taker, 1, WAD, nonce=nonce)
        assert not policy.is_nonce_used(nonce)
        router.swap(grant, sign(policy, grant), 1, 0, WAD, 1, sender=taker)
        assert policy.is_nonce_used(nonce)
    assert not policy.is_nonce_used(257)
    again = make_grant(taker, 1, WAD, nonce=256)
    with boa.reverts("nonce"):
        router.swap(again, sign(policy, again), 1, 0, WAD, 1, sender=taker)


def test_deadline_window(env):
    for deadline, reason in ((now() - 1, "expired"), (now() + 121, "deadline")):
        with boa.reverts(reason):
            granted_swap(env, 1, 0, WAD, deadline=deadline)
    granted_swap(env, 1, 0, WAD, deadline=now())
    granted_swap(env, 1, 0, WAD, deadline=now() + 120)


def test_direction_and_amount(env):
    _, policy, router, taker = env
    dx = 5_000 * 10**6
    for coin_in, lo, hi, reason in (
        (1, dx - 1, dx, "direction"),
        (0, dx + 1, dx + 2, "amount"),
        (0, dx - 2, dx - 1, "amount"),
    ):
        grant = make_grant(taker, coin_in, dx, lo=lo, hi=hi)
        with boa.reverts(reason):
            router.swap(grant, sign(policy, grant), 0, 1, dx, 1, sender=taker)
    bad_coin = make_grant(taker, 2, dx)
    with boa.reverts("coin"):
        router.swap(bad_coin, sign(policy, bad_coin), 0, 1, dx, 1, sender=taker)
    # A coin0 input reads exactly; the bounds are inclusive.
    granted_swap(env, 0, 1, dx, lo=dx, hi=dx)


def test_grants_work_during_an_a_ramp(env, factory_admin):
    pool, _, router, taker = env
    pool.ramp_A_gamma(pool.A() * 2, pool.gamma(), now() + 86_400, sender=factory_admin)
    boa.env.time_travel(seconds=3_600)
    router.plain_swap(1, 0, WAD, 1, sender=taker)  # the pool checkpoints the ramp
    boa.env.time_travel(seconds=3_600)
    # The swap re-solves D for the ramp; the grant compares balances, not D.
    with boa.env.anchor():
        plain = router.plain_swap(1, 0, 2 * WAD, 1, sender=taker)
    granted = granted_swap(env, 1, 0, 2 * WAD)
    # The same pre-fee output, at 5 bp instead of 1%.
    guess = plain * FEE_PRECISION // (FEE_PRECISION - DEFAULT_FEE)
    dy = next(
        d for d in range(guess - 2, guess + 3) if d - DEFAULT_FEE * d // FEE_PRECISION == plain
    )
    assert granted == dy - GRANT_FEE * dy // FEE_PRECISION


# -------------------------------- Governance ----------------------------------


def test_kill_stops_grants(env):
    pool, policy, router, taker = env
    stranger = boa.env.generate_address("stranger")
    with boa.reverts("access"):
        policy.set_killed(True, sender=stranger)
    policy.set_killed(True, sender=EMERGENCY)
    assert policy.is_killed()
    with boa.reverts("killed"):
        granted_swap(env, 1, 0, WAD)
    expected = charged(pool, DEFAULT_FEE, 1, 0, WAD)
    assert router.plain_swap(1, 0, WAD, 1, sender=taker) == expected
    policy.set_killed(False, sender=EMERGENCY)
    policy.set_killed(True)  # the owner too
    policy.set_killed(False)
    granted_swap(env, 1, 0, WAD)


def test_kill_clears_an_armed_grant(env):
    _, policy, router, taker = env
    # boa keeps transient storage between calls, which stands in for an armed
    # grant and a kill in one transaction.
    grant = make_grant(taker, 1, WAD)
    policy.submit_grant(grant, sign(policy, grant), taker, sender=router.address)
    assert policy.eval("self.armed")
    policy.set_killed(True, sender=EMERGENCY)
    assert not policy.eval("self.armed")


def test_owner_settings(env):
    _, policy, _, _ = env
    new = boa.env.generate_address("new")
    for call in (
        lambda s: policy.set_controller(new, sender=s),
        lambda s: policy.set_router(new, sender=s),
        lambda s: policy.set_fees(DEFAULT_FEE, MIN_GRANT_FEE, sender=s),
    ):
        with boa.reverts("ownable: caller is not the owner"):
            call(EMERGENCY)
    policy.set_fees(2 * DEFAULT_FEE, 10**5)
    assert policy.get_logs()[-1].default_fee == 2 * DEFAULT_FEE
    assert (policy.default_fee(), policy.min_fee()) == (2 * DEFAULT_FEE, 10**5)
    with boa.reverts("min fee"):
        policy.set_fees(DEFAULT_FEE, DEFAULT_FEE + 1)
    with boa.reverts("default fee"):
        policy.set_fees(FEE_PRECISION // 10 + 1, 10**5)
    # A new key invalidates grants signed with the old one.
    policy.set_controller(new)
    assert policy.controller() == new
    with boa.reverts("signature"):
        granted_swap(env, 1, 0, WAD)
    zero = "0x0000000000000000000000000000000000000000"
    with boa.reverts("controller=0"):
        policy.set_controller(zero)
    # A new router: the old one can no longer arm grants.
    policy.set_controller(CONTROLLER.address)
    policy.set_router(new)
    with boa.reverts("router"):
        granted_swap(env, 1, 0, WAD)
    with boa.reverts("router=0"):
        policy.set_router(zero)


def test_only_the_pool_calls_back(env):
    _, policy, _, taker = env
    with boa.reverts("pool"):
        policy.update_pool_state([1, 1], 1, 1, 1, 1, 1, 1, 1, sender=taker)
