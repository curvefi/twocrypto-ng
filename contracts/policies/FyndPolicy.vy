# pragma version 0.4.3
# pragma optimize gas
"""
@title FyndPolicy
@notice Twocrypto policy for Fynd-routed swaps. Every operation pays default_fee,
        except a swap that Fynd's router arms with a grant signed by Fynd's
        controller key: it pays the granted fee, at least min_fee.
@dev Vyper port of Fynd's FyndCurvePolicy sketch (28 Oct 2026) without its Pyth
     floor and revenue share fields. The policy checks who signed a grant, not
     what the trade is worth: LPs rely on Fynd to price each grant.

     CALLERS
         router            submit_grant, in the swap's transaction, before it
         pool              get_fee, get_price_scale, update_pool_state
         anyone            views
         owner (Curve)     set_controller, set_router, set_fees, set_killed, ownership
         emergency admin   set_killed

     GRANTS
     An EIP-712 Grant signed by the `controller` key (ECDSA, no contract wallets)
     admits one swap in its direction and input range; a coin1 input can read 1
     wei below the amount sent. The router submits it with the address that
     called the router, which must be the grant's taker, at most
     MAX_GRANT_WINDOW before its deadline. Each nonce works once. Arming records
     the pool's balances, which the swap's must differ from in the granted
     direction and range. The pool's callback after the next operation clears
     the grant, as do a kill and the end of the transaction: every operation that
     changes the pool's balances or price_scale calls back. Liquidity operations
     pay default_fee and clear it.

     UNITS
     Fees in FEE_PRECISION (1e10 = 100%).
"""
from snekmate.auth import ownable
from snekmate.utils import ecdsa
from snekmate.utils import eip712_domain_separator as eip712

initializes: ownable
initializes: eip712
exports: (
    ownable.owner,
    ownable.transfer_ownership,
    ownable.renounce_ownership,
    eip712.eip712Domain,
)


interface Pool:
    def balances(i: uint256) -> uint256: view
    def precisions() -> uint256[N_COINS]: view
    def price_scale() -> uint256: view  # Nonreentrant: reverts inside a pool operation.


N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18
FEE_PRECISION: constant(uint256) = 10**10  # Twocrypto fee units: 10**10 = 100%.
MIN_FEE: constant(uint256) = 10**5  # Twocrypto MIN_FEE (0.1 bp); a fee of 0 means the pool's own.
MAX_DEFAULT_FEE: constant(uint256) = FEE_PRECISION // 10  # 10%
MAX_GRANT_WINDOW: constant(uint256) = 120  # seconds from submission to the grant's deadline

# Lets Fynd's indexer tag the pool.
IS_FYND_EXCLUSIVE: public(constant(bool)) = True

GRANT_TYPEHASH: public(constant(bytes32)) = keccak256(
    "Grant(address taker,uint8 coin_in,uint256 min_amount_in,uint256 max_amount_in,uint256 fee,uint64 nonce,uint32 deadline)"
)


struct Grant:
    taker: address  # the router's caller
    coin_in: uint8  # pool index of the input coin
    min_amount_in: uint256  # input range, in the input coin's units
    max_amount_in: uint256
    fee: uint256  # FEE_PRECISION
    nonce: uint64
    deadline: uint32  # unix seconds


struct ArmedGrant:
    coin_in: uint256
    min_amount_in: uint256
    max_amount_in: uint256
    fee: uint256
    xp: uint256[N_COINS]  # the pool's balances when armed, coin1 scaled by price_scale
    price_scale: uint256


POOL: public(immutable(address))
EMERGENCY_ADMIN: public(immutable(address))
PRECISIONS: immutable(uint256[N_COINS])

controller: public(address)  # Fynd's signing key
router: public(address)  # Fynd's router, the only caller of submit_grant
default_fee: public(uint256)  # fee of every operation without a grant
min_fee: public(uint256)  # lowest fee of a granted swap
is_killed: public(bool)
used_nonces: HashMap[uint256, uint256]  # nonce // 256 => bitmap of used nonces

armed: transient(bool)
armed_grant: transient(ArmedGrant)


event GrantArmed:
    taker: indexed(address)
    nonce: uint64
    coin_in: uint8
    fee: uint256


event SetController:
    controller: address


event SetRouter:
    router: address


event SetFees:
    default_fee: uint256
    min_fee: uint256


event SetKilled:
    is_killed: bool


@deploy
def __init__(
    pool: address,
    controller: address,
    router: address,
    emergency_admin: address,
    default_fee: uint256,
    min_fee: uint256,
):
    """
    @param pool Twocrypto pool
    @param controller Fynd's signing key
    @param router Fynd's router
    @param emergency_admin May kill and revive the policy, as may the owner
    @param default_fee Fee without a grant; the deployer becomes the owner
    @param min_fee Lowest fee of a granted swap
    """
    assert pool.is_contract, "pool"
    assert emergency_admin != empty(address), "emergency admin=0"

    POOL = pool
    EMERGENCY_ADMIN = emergency_admin
    PRECISIONS = staticcall Pool(pool).precisions()

    ownable.__init__()
    eip712.__init__("FyndPolicy", "1")
    self._set_controller(controller)
    self._set_router(router)
    self._set_fees(default_fee, min_fee)


# ----------------------------------- Grants ------------------------------------


@external
def submit_grant(grant: Grant, signature: Bytes[65], taker: address):
    """
    @notice Arm `grant` for this transaction's next pool operation. Router only.
    @param signature The controller's EIP-712 signature of `grant`
    @param taker The address that called the router
    """
    assert msg.sender == self.router, "router"
    assert not self.is_killed, "killed"
    assert not self.armed, "armed"
    assert taker == grant.taker, "taker"
    deadline: uint256 = convert(grant.deadline, uint256)
    assert block.timestamp <= deadline, "expired"
    assert deadline <= block.timestamp + MAX_GRANT_WINDOW, "deadline"
    assert convert(grant.coin_in, uint256) < N_COINS, "coin"
    self._use_nonce(grant.nonce)

    digest: bytes32 = eip712._hash_typed_data_v4(keccak256(abi_encode(GRANT_TYPEHASH, grant)))
    # Reverts on a malformed signature; the controller is never empty.
    assert ecdsa._recover_sig(digest, signature) == self.controller, "signature"

    # price_scale() is nonreentrant: arming reverts inside a pool operation.
    price_scale: uint256 = staticcall Pool(POOL).price_scale()
    self.armed = True
    self.armed_grant = ArmedGrant(
        coin_in=convert(grant.coin_in, uint256),
        min_amount_in=grant.min_amount_in,
        max_amount_in=grant.max_amount_in,
        fee=grant.fee,
        # As Twocrypto._xp computes it.
        xp=[
            staticcall Pool(POOL).balances(0) * PRECISIONS[0],
            staticcall Pool(POOL).balances(1) * PRECISIONS[1] * price_scale // PRECISION,
        ],
        price_scale=price_scale,
    )
    log GrantArmed(taker=taker, nonce=grant.nonce, coin_in=grant.coin_in, fee=grant.fee)


@internal
def _use_nonce(nonce: uint64):
    word: uint256 = convert(nonce, uint256) >> 8
    bit: uint256 = 1 << (convert(nonce, uint256) & 255)
    bitmap: uint256 = self.used_nonces[word]
    assert bitmap & bit == 0, "nonce"
    self.used_nonces[word] = bitmap | bit


@external
@view
def is_nonce_used(nonce: uint64) -> bool:
    return self.used_nonces[convert(nonce, uint256) >> 8] & (1 << (convert(nonce, uint256) & 255)) != 0


# ------------------------------------- Fee -------------------------------------


@external
@view
def get_fee(xp: uint256[N_COINS]) -> uint256:
    """
    @notice Fee of the pool operation in progress: for the swap an armed grant
            admits, the granted fee, at least min_fee; default_fee for
            everything else.
    @param xp Pool balances after the operation and before its fee, coin1 scaled
           by price_scale
    @return FEE_PRECISION fee
    """
    if not self.armed:
        return self.default_fee

    grant: ArmedGrant = self.armed_grant
    old_xp: uint256[N_COINS] = grant.xp
    # A grant admits only a swap: one balance rises and the other falls.
    if xp[0] >= old_xp[0] and xp[1] >= old_xp[1]:
        return self.default_fee
    if xp[0] <= old_xp[0] and xp[1] <= old_xp[1]:
        return self.default_fee

    coin_in: uint256 = 0 if xp[0] > old_xp[0] else 1
    assert coin_in == grant.coin_in, "direction"
    amount_in: uint256 = xp[coin_in] - old_xp[coin_in]
    if coin_in == 1:
        amount_in = amount_in * PRECISION // grant.price_scale
    amount_in //= PRECISIONS[coin_in]
    assert amount_in >= grant.min_amount_in and amount_in <= grant.max_amount_in, "amount"

    return max(grant.fee, self.min_fee)


# --------------------------------- Pool hooks ----------------------------------


@external
@pure
def get_price_scale() -> uint256:
    """@notice 0: the pool keeps its own price_scale target."""
    return 0


@external
def update_pool_state(
    _xp: uint256[N_COINS],
    _price_scale: uint256,
    _price_oracle: uint256,
    _last_prices: uint256,
    _virtual_price: uint256,
    _xcp_profit: uint256,
    _D: uint256,
    _oracle_timestamp: uint256,
):
    """
    @notice Pool callback after every operation: clear the armed grant.
    @dev A balanced removal calls back best-effort with 300k gas, which this
         never runs out of.
    """
    assert msg.sender == POOL, "pool"
    self.armed = False


# --------------------------------- Governance ----------------------------------


@external
def set_controller(controller: address):
    """@notice Replace Fynd's signing key. Owner only."""
    ownable._check_owner()
    self._set_controller(controller)


@external
def set_router(router: address):
    """@notice Replace Fynd's router. Owner only."""
    ownable._check_owner()
    self._set_router(router)


@external
def set_fees(default_fee: uint256, min_fee: uint256):
    """@notice Set the fee without a grant and the lowest granted fee. Owner only."""
    ownable._check_owner()
    self._set_fees(default_fee, min_fee)


@external
def set_killed(is_killed: bool):
    """
    @notice Kill (True) or revive the policy. Owner or emergency admin.
    @dev While killed, no grant can be armed, so every operation pays default_fee.
         Killing also clears a grant armed earlier in the same transaction.
    """
    assert msg.sender == EMERGENCY_ADMIN or msg.sender == ownable.owner, "access"
    if is_killed:
        self.armed = False
    self.is_killed = is_killed
    log SetKilled(is_killed=is_killed)


@internal
def _set_controller(controller: address):
    assert controller != empty(address), "controller=0"
    self.controller = controller
    log SetController(controller=controller)


@internal
def _set_router(router: address):
    assert router != empty(address), "router=0"
    self.router = router
    log SetRouter(router=router)


@internal
def _set_fees(default_fee: uint256, min_fee: uint256):
    assert MIN_FEE <= min_fee and min_fee <= default_fee, "min fee"
    assert default_fee <= MAX_DEFAULT_FEE, "default fee"
    self.default_fee = default_fee
    self.min_fee = min_fee
    log SetFees(default_fee=default_fee, min_fee=min_fee)
