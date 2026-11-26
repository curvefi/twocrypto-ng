# pragma version 0.4.3

"""
@title RPF Controller

@notice Switches one Twocrypto pool's reserved profit fraction (RPF) between a
        baseline and 100%: the pool keeps a small reserve to pay for
        rebalancing, and no profit beyond it can be spent on rebalancing.

@dev The pool pays for rebalancing out of its virtual price above
     lp_xcp_profit. The gap is that reserve as a fraction:

         gap = virtual_price / lp_xcp_profit - 1

         gap >= harvest_gap    RPF 100%: all new profit is reserved, for LPs
                               less the pool's admin fee, and the gap stops
                               growing
         gap <= restore_gap    baseline RPF: new profit refills the gap
         in between            100% if the pool is at 100%, else baseline

     HARVEST
     A windfall of fees lifts the gap over harvest_gap. At 100% the gap can
     only fall, as rebalances spend it, while all new profit is reserved; at
     restore_gap the baseline is back and profit refills the gap.

         gap
          |             _
          |            / '-.
          |- - - - - -/- - -'-.- - - - - - - - -   harvest_gap
          |          /         '-.
          |         /             '-.
          |- - - - / - - - - - - - - '-. - - - -   restore_gap
          |       /                     '-.
          |_.-._.-                         '-._.-._
          +----------------------------------------> time
           baseline   |     100%       |  baseline
                   update()         update()

     update() sets the pool's RPF through the owner proxy's forward(), at most
     once per min_change_period. The Curve DAO must first permit this contract
     to call set_fee_parameters on the pool. That method also sets the admin
     fee: update() passes the pool's current admin fee back unchanged.

     CALLERS
         anyone            update
         owner (YB DAO)    set_config, ownership

     UNITS
     RPF in FEE_PRECISION (1e10 = 100%). Gaps in PRECISION (1e18 = 100%, 1e14
     is one basis point). Periods in seconds.

@license Copyright (c) Curve.Fi, 2026 - all rights reserved

@author curve.fi
"""

from snekmate.auth import ownable

initializes: ownable
exports: (
    ownable.owner,
    ownable.transfer_ownership,
    ownable.renounce_ownership,
)


interface Pool:
    def virtual_price() -> uint256: view
    def lp_xcp_profit() -> uint256: view
    def reserved_profit_fraction() -> uint256: view
    def admin_fee() -> uint256: view


interface OwnerProxy:
    def forward(_pool: address, _calldata: Bytes[1024]) -> Bytes[1024]: nonpayable


struct Config:
    baseline_rpf: uint256  # FEE_PRECISION: the pool's RPF while the gap refills
    harvest_gap: uint256  # PRECISION: gap at or above which the pool's RPF is 100%
    restore_gap: uint256  # PRECISION: gap at or below which it is the baseline again
    min_change_period: uint256  # seconds between two changes of the pool's RPF


event SetConfig:
    config: Config


PRECISION: constant(uint256) = 10**18
FEE_PRECISION: constant(uint256) = 10**10  # Twocrypto fee units: 10**10 = 100%
FULL_RPF: constant(uint256) = FEE_PRECISION

POOL: public(immutable(Pool))
PROXY: public(immutable(OwnerProxy))  # the pool's admin

config: public(Config)
last_change: public(uint256)  # block.timestamp of the last update()


@deploy
def __init__(pool: address, proxy: address, config: Config):
    """
    @notice The deployer becomes the owner
    @param pool Twocrypto pool whose RPF this contract sets
    @param proxy Owner proxy that is the pool's admin and forwards this
           contract's calls
    @param config Initial config
    """
    assert pool != empty(address), "pool=0"
    assert proxy != empty(address), "proxy=0"
    ownable.__init__()

    POOL = Pool(pool)
    PROXY = OwnerProxy(proxy)
    self._set_config(config)


@external
def update():
    """
    @notice Set the pool's RPF to target_rpf(). Anyone may call.
    @dev Reverts when the pool is already there, within min_change_period of
         the last change, and inside a pool operation, where the pool's
         reentrancy lock rejects set_fee_parameters.
    """
    rpf: uint256 = self._target_rpf()
    assert rpf != staticcall POOL.reserved_profit_fraction(), "no change"
    assert block.timestamp >= self.last_change + self.config.min_change_period, "too soon"
    self.last_change = block.timestamp
    extcall PROXY.forward(
        POOL.address,
        abi_encode(
            rpf,
            staticcall POOL.admin_fee(),
            method_id=method_id("set_fee_parameters(uint256,uint256)"),
        ),
    )


@external
@view
def target_rpf() -> uint256:
    """@notice The RPF update() sets once min_change_period allows, FEE_PRECISION"""
    return self._target_rpf()


@external
def set_config(config: Config):
    """
    @notice Replace the whole config. Owner only.
    @dev Nothing is sent to the pool: the next update() applies the new config,
         a new baseline only outside the 100% mode. A new min_change_period
         counts from the last change.
    """
    ownable._check_owner()
    self._set_config(config)


@internal
@view
def _target_rpf() -> uint256:
    config: Config = self.config
    virtual_price: uint256 = staticcall POOL.virtual_price()
    lp_xcp_profit: uint256 = staticcall POOL.lp_xcp_profit()

    # gap against a threshold, cross-multiplied: an A ramp can leave virtual
    # price under lp_xcp_profit. The low test goes first: an empty pool reads 0, 0.
    if virtual_price * PRECISION <= lp_xcp_profit * (PRECISION + config.restore_gap):
        return config.baseline_rpf
    if virtual_price * PRECISION >= lp_xcp_profit * (PRECISION + config.harvest_gap):
        return FULL_RPF
    # Between the thresholds, stay in the 100% mode once in it
    if staticcall POOL.reserved_profit_fraction() == FULL_RPF:
        return FULL_RPF
    return config.baseline_rpf


@internal
def _set_config(config: Config):
    assert config.baseline_rpf <= FULL_RPF, "baseline rpf"
    # Supported ranges: gaps up to 100%, a period up to a week
    assert config.harvest_gap <= PRECISION, "harvest gap"
    assert config.restore_gap < config.harvest_gap, "restore gap"
    assert config.min_change_period <= 7 * 86_400, "min change period"

    self.config = config
    log SetConfig(config=config)
