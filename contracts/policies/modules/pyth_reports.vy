# pragma version 0.4.3

"""
@title Pyth Reports
@notice coin1's USD price for a policy, from a PythReportBank's newest record
        of a Pyth Lazer feed: optionally times a Curve pool's price_oracle
        basis, within owner-set price bounds.
@dev The report is the bank's newest record of FEED_ID on CHANNEL, read when
     used. With BASIS_POOL set (0 is off), coin1's price is the feed's times
     that Curve stableswap-ng pool's price_oracle(0), or divided by it with
     INVERT_BASIS: say WBTC/USD from BTC/USD and WBTC in cbBTC, cbBTC counting
     as BTC. The basis is read live, and only for a report the caller can use:
     present and younger than the caller's maximum age. The basis is capped to
     move coin1's price at most 10% from the feed's. The report is absent when
     the price is outside the bounds, which apply at every use. Its time is the
     feed's observation.

     The bank's verifier decides which prices are authentic. The basis pool's
     price_oracle is an EMA of its own trades: moving it is accepted, and the
     cap bounds what it can do. The policy checks its kill switch before
     calling here, so a killed policy reads neither. Prices have 18 decimals
     (1e18 = $1); Pyth times are microseconds.
@license Copyright (c) Curve.Fi, 2026 - all rights reserved
@author curve.fi
"""

################################################################
#                           CONSTANTS                          #
################################################################

PRECISION: constant(uint256) = 10**18
# Hard limits for the price bounds
MIN_REPORT_PRICE: constant(uint256) = 10**6  # $1e-12
MAX_REPORT_PRICE: constant(uint256) = 10**30  # $1e12
# coin1's price is the feed's times a basis capped to [MIN_BASIS, MAX_BASIS]: 10% at most
MIN_BASIS: constant(uint256) = 9 * PRECISION // 10
MAX_BASIS: constant(uint256) = 11 * PRECISION // 10
# Inverted, the basis is PRECISION**2 / price_oracle(0): the cap on price_oracle(0)
# itself, rounded inward
MIN_INVERTED_ORACLE: constant(uint256) = (PRECISION * PRECISION + MAX_BASIS - 1) // MAX_BASIS
MAX_INVERTED_ORACLE: constant(uint256) = PRECISION * PRECISION // MIN_BASIS

################################################################
#                          INTERFACES                          #
################################################################

interface ReportBank:  # (price, observation_us)
    def latest(feed_id: uint32, channel: uint8) -> (uint256, uint256): view


interface BasisPool:  # Curve stableswap-ng: price_oracle(0) is coin1 in coin0
    def coins(i: uint256) -> address: view
    def price_oracle(i: uint256) -> uint256: view

################################################################
#                            STRUCTS                           #
################################################################

# Sanity bounds on coin1's USD price; a price outside is absent
struct PriceBounds:
    min_price: uint256
    max_price: uint256


struct Report:
    asset_price: uint256  # coin1 in USD; 0 when absent
    observation_us: uint256  # the feed's Pyth update time
    age_us: uint256  # now less observation_us; 0 for an observation after the block

################################################################
#                            EVENTS                            #
################################################################

event SetPriceBounds:
    bounds: PriceBounds

################################################################
#                            STORAGE                           #
################################################################

BANK: public(immutable(address))  # PythReportBank
FEED_ID: public(immutable(uint32))  # Pyth Lazer feed priced in USD; ids are stable
CHANNEL: public(immutable(uint8))  # 1 real_time, 2 fixed_rate@50ms, 3 @200ms, 4 @1000ms
BASIS_POOL: public(immutable(address))  # 0: none
INVERT_BASIS: public(immutable(bool))  # coin1 is the feed's price over price_oracle(0)

price_bounds: public(PriceBounds)

################################################################
#                         CONSTRUCTOR                          #
################################################################

@deploy
def __init__(
    bank: address,
    feed_id: uint32,
    channel: uint8,
    basis_pool: address,
    invert_basis: bool,
    coin1: address,
    bounds: PriceBounds,
):
    """
    @param bank PythReportBank that stores the reports
    @param feed_id Pyth Lazer feed of coin1/USD, or of the asset it wraps
    @param channel Pyth Lazer channel of the reports
    @param basis_pool Curve stableswap-ng pool whose price_oracle(0) prices
           coin1 in the feed's asset, or its inverse; 0 for none
    @param invert_basis True when price_oracle(0) prices the feed's asset in coin1
    @param coin1 The policy pool's coin1, which the basis pool must hold
    @param bounds Initial price bounds
    """
    assert bank.is_contract, "bank"
    assert feed_id > 0, "feed id"
    # The four channels Pyth Lazer defines (PythLazerStructs.Channel)
    assert channel >= 1 and channel <= 4, "channel"
    if basis_pool == empty(address):
        assert not invert_basis, "invert basis"
    else:
        # The pool prices coin1 as its coin1, or inverted as its coin0. Near
        # parity a wrong pool or orientation would pass any price check.
        coin1_index: uint256 = 0 if invert_basis else 1
        assert staticcall BasisPool(basis_pool).coins(coin1_index) == coin1, "basis coin"
        # Rejects a pool without price_oracle(uint256); a depeg past the cap is
        # capped, not refused
        oracle: uint256 = staticcall BasisPool(basis_pool).price_oracle(0)

    BANK = bank
    FEED_ID = feed_id
    CHANNEL = channel
    BASIS_POOL = basis_pool
    INVERT_BASIS = invert_basis
    self._set_price_bounds(bounds)

################################################################
#                      INTERNAL FUNCTIONS                      #
################################################################

@internal
@view
def _stored_report(max_age_us: uint256) -> Report:
    """
    @dev The bank's record as a report: price 0 when the record is empty, at
         least max_age_us old, or rejected by _coin1_price. The first two come
         first, so a report the caller cannot use never reads the basis pool.
    """
    price: uint256 = 0
    observation_us: uint256 = 0
    price, observation_us = staticcall ReportBank(BANK).latest(FEED_ID, CHANNEL)
    time_us: uint256 = block.timestamp * 1_000_000
    age_us: uint256 = time_us - min(time_us, observation_us)
    if price == 0 or age_us >= max_age_us:
        return Report(asset_price=0, observation_us=observation_us, age_us=age_us)
    return Report(
        asset_price=self._coin1_price(price), observation_us=observation_us, age_us=age_us
    )


@internal
@view
def _coin1_price(feed_price: uint256) -> uint256:
    """
    @dev coin1 in USD from the feed's price: times the capped price_oracle(0),
         or over it with INVERT_BASIS, rounded down once; 0 when the result is
         outside the price bounds
    """
    price: uint256 = feed_price
    if BASIS_POOL != empty(address):
        # Out of bounds whatever the basis, and the product could overflow. The
        # bank's prices are below 2**123; a quote's price is anything.
        if feed_price > max_value(uint256) // MAX_INVERTED_ORACLE:
            return 0
        oracle: uint256 = staticcall BasisPool(BASIS_POOL).price_oracle(0)
        if INVERT_BASIS:
            oracle = min(max(oracle, MIN_INVERTED_ORACLE), MAX_INVERTED_ORACLE)
            price = feed_price * PRECISION // oracle
        else:
            oracle = min(max(oracle, MIN_BASIS), MAX_BASIS)
            price = feed_price * oracle // PRECISION
    bounds: PriceBounds = self.price_bounds
    if price < bounds.min_price or price > bounds.max_price:
        return 0
    return price


@internal
def _set_price_bounds(bounds: PriceBounds):
    assert (
        MIN_REPORT_PRICE <= bounds.min_price
        and bounds.min_price <= bounds.max_price
        and bounds.max_price <= MAX_REPORT_PRICE
    ), "price bounds"
    self.price_bounds = bounds
    log SetPriceBounds(bounds=bounds)
