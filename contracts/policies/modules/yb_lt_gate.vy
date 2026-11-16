# pragma version 0.4.3

"""
@title YB LT Gate

@notice Keeps LT deposits into a YieldBasis market's Twocrypto pool on the
        LevAMM book's ratio. A policy initializes it, calls _update from its
        pool callback and _sync from its sync(), and exports its getters.

@dev LT.deposit(assets, debt) lets the caller pick the debt, and a debt off the
     LevAMM book's ratio is a fee-free trade against its holders. The fair
     deposit has

         debt == added_lp * old_debt / old_collateral

     LT mints the LP to the LevAMM, the pool calls back, and only then does LT
     book it: the LevAMM still reports the old book, and a revert unwinds the
     deposit. added_lp is the growth of pool.user_supply(), and the debt the
     growth of the pool's stablecoin balance, exact while the pool's admin fee
     is zero (checked at deployment). Should governance set one, the deposit's
     admin share goes unseen: an exact deposit can fail, and one can carry that
     share of extra debt beyond the tolerance.

     A balanced removal's callback is best-effort. If it fails, cached_supply
     stays above the pool's supply, and until _sync an LT deposit that mints
     less LP than that removal burned looks like an exit and goes unchecked.
     After every successful update cached_supply equals pool.user_supply(), so
     a keeper calls the policy's sync() whenever they differ while it is live.

@license Copyright (c) Curve.Fi, 2026 - all rights reserved

@author curve.fi
"""

################################################################
#                           CONSTANTS                          #
################################################################

PRECISION: constant(uint256) = 10**18
MAX_RATIO_TOLERANCE: constant(uint256) = PRECISION // 1000  # 10 bp

################################################################
#                          INTERFACES                          #
################################################################

interface Pool:
    def admin_fee() -> uint256: view
    def balanceOf(account: address) -> uint256: view
    def coins(i: uint256) -> address: view
    def precisions() -> uint256[2]: view
    def user_supply() -> uint256: view


interface LevAMM:
    def COLLATERAL() -> address: view
    def STABLECOIN() -> address: view
    def collateral_amount() -> uint256: view
    def get_debt() -> uint256: view

################################################################
#                            EVENTS                            #
################################################################

event SetRatioTolerance:
    ratio_tolerance: uint256

################################################################
#                            STORAGE                           #
################################################################

POOL: immutable(address)
AMM: public(immutable(address))  # the LevAMM that holds the pool's LP as collateral

# WAD tolerance around an LT deposit's proportional debt: it absorbs interest and
# trades between quoting and inclusion. 0 requires exact equality.
ratio_tolerance: public(uint256)
cached_supply: public(uint256)  # pool.user_supply() as of the last update; 0 until attached
amm_surplus: public(uint256)  # LP gifted to the LevAMM, as of the last add or sync

################################################################
#                         CONSTRUCTOR                          #
################################################################

@deploy
def __init__(pool: address, amm: address, ratio_tolerance: uint256):
    """
    @param pool Twocrypto pool; coin0 is the LevAMM's stablecoin
    @param amm LevAMM that holds the pool's LP as collateral
    @param ratio_tolerance Initial tolerance, WAD
    """
    # One market: the LevAMM's collateral is this pool's LP, and its stablecoin
    # is coin0, which the pool holds unscaled
    assert staticcall LevAMM(amm).COLLATERAL() == pool, "amm collateral"
    assert staticcall LevAMM(amm).STABLECOIN() == staticcall Pool(pool).coins(0), "amm stablecoin"
    assert (staticcall Pool(pool).precisions())[0] == 1, "pool precision"
    # The gate measures deposited debt exactly only without a pool admin fee
    assert staticcall Pool(pool).admin_fee() == 0, "admin fee"

    POOL = pool
    AMM = amm
    self._set_ratio_tolerance(ratio_tolerance)

################################################################
#                      INTERNAL FUNCTIONS                      #
################################################################

@internal
def _update(stable: uint256, old_stable: uint256):
    """
    @dev Gate the operation the pool just made; revert on an off-ratio LT deposit.
    @param stable The pool's stablecoin balance after the operation
    @param old_stable The pool's stablecoin balance as of the previous update or sync
    """
    # Swaps and donations leave user LP supply unchanged
    supply: uint256 = staticcall Pool(POOL).user_supply()
    old_supply: uint256 = self.cached_supply
    if supply == old_supply and old_supply != 0:
        return
    self.cached_supply = supply
    # Exits reduce booked collateral and LP holdings together, preserving gifts
    if supply < old_supply:
        return

    # LP the LevAMM holds beyond its booked collateral: gifts, plus a deposit
    # minted but not yet booked
    lp_balance: uint256 = staticcall Pool(POOL).balanceOf(AMM)
    collateral: uint256 = staticcall LevAMM(AMM).collateral_amount()
    surplus: uint256 = lp_balance - min(lp_balance, collateral)
    old_surplus: uint256 = self.amm_surplus

    # Nothing recorded yet: record only. At attachment the surplus is gifts. The
    # first add to an empty pool meets an empty book, whose LP is that add's own
    # unbooked LT deposit, not a gift.
    if old_supply == 0:
        if collateral == 0:
            surplus = 0
    else:
        added_lp: uint256 = supply - old_supply
        # An LT deposit leaves its minted LP unbooked on the LevAMM. An unrecorded
        # gift can make another add look like one, never the reverse.
        if surplus >= old_surplus + added_lp:
            surplus -= added_lp
            # An empty book has no ratio to keep and no holders to trade against
            if collateral != 0:
                added_debt: uint256 = stable - min(stable, old_stable)
                proportional: uint256 = added_lp * staticcall LevAMM(AMM).get_debt() // collateral
                deviation: uint256 = max(added_debt, proportional) - min(added_debt, proportional)
                assert (
                    deviation * PRECISION <= proportional * self.ratio_tolerance
                ), "LT deviation"

    if surplus != old_surplus:
        self.amm_surplus = surplus


@internal
def _sync(attached: bool):
    """
    @dev Re-read the baselines: the user supply once attached (before, the first
         update seeds it with the policy's snapshot), and the LevAMM's gifts.
         Trusts LT, the LevAMM and the tokens not to call it during an
         unfinished LP transfer or book update.
    """
    if attached:
        self.cached_supply = staticcall Pool(POOL).user_supply()
    lp_balance: uint256 = staticcall Pool(POOL).balanceOf(AMM)
    collateral: uint256 = staticcall LevAMM(AMM).collateral_amount()
    self.amm_surplus = lp_balance - min(lp_balance, collateral)


@internal
def _set_ratio_tolerance(ratio_tolerance: uint256):
    assert ratio_tolerance <= MAX_RATIO_TOLERANCE, "ratio tolerance"
    self.ratio_tolerance = ratio_tolerance
    log SetRatioTolerance(ratio_tolerance=ratio_tolerance)
