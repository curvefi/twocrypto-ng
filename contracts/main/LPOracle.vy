# pragma version 0.4.3
"""
@title FXSwapLPOracle
@author Curve.Fi
@license MIT
@notice LP oracle for Twocrypto(FXSwap)-style pools.
@dev Reuses stable bisection solver and adjusts for pool internal price scaling.
"""

from curve_std.stableswap import lp_oracle_2


interface IFXSwap:
    def A() -> uint256: view
    def virtual_price() -> uint256: view
    def price_scale() -> uint256: view
    def price_oracle() -> uint256: view
    def D() -> uint256: view
    def totalSupply() -> uint256: view


PRECISION: constant(uint256) = 10**18
N_COINS: constant(uint256) = 2
POOL_A_PRECISION: constant(uint256) = 10_000


@internal
@view
def _sanity_check(pool: IFXSwap):
    assert pool.address != empty(address)
    assert staticcall pool.A() >= POOL_A_PRECISION, "Bad A value"
    assert staticcall pool.virtual_price() > 0
    assert staticcall pool.price_scale() > 0
    assert staticcall pool.price_oracle() > 0

@view
@external
def sanity_check(_pool: IFXSwap) -> bool:
    """
    @notice Validates core pool parameters required by this oracle.
    @param _pool Address of the Twocrypto(FXSwap)-style pool.
    @return bool True if all sanity checks pass, otherwise reverts.
    """
    self._sanity_check(_pool)
    return True


@internal
@view
def _scaled_A_raw(pool: IFXSwap) -> uint256:
    # Pool stores A as: A_true * N_COINS**(N_COINS-1) * 10_000.
    # Solver expects: A_true * solver.A_PRECISION.
    A_pool: uint256 = staticcall pool.A()
    return unsafe_div(
        A_pool * lp_oracle_2.A_PRECISION,
        N_COINS**(N_COINS-1) * POOL_A_PRECISION
    )

@internal
@view
def _scaled_price(pool: IFXSwap) -> uint256:
    # Pool invariant is computed on balances scaled by price_scale.
    # Convert oracle price into that scaled coordinate system.
    p_oracle: uint256 = staticcall pool.price_oracle()
    p_scale: uint256 = staticcall pool.price_scale()
    return unsafe_div(p_oracle * PRECISION, p_scale)

@internal
@view
def _portfolio_value(pool: IFXSwap, i: uint256=0) -> uint256:
    assert i < N_COINS

    p_oracle: uint256 = staticcall pool.price_oracle()
    p_scale: uint256 = staticcall pool.price_scale()

    x_py: uint256 = lp_oracle_2._portfolio_value(self._scaled_A_raw(pool), p_oracle * PRECISION // p_scale)

    if i == 1:
        return x_py * PRECISION // p_oracle
    return x_py


@view
@external
def portfolio_value(_pool: IFXSwap, _i: uint256=0) -> uint256:
    """
    @notice Returns the pool portfolio value in the selected coin numeraire.
    @param _pool Address of the Twocrypto(FXSwap)-style pool.
    @param _i Coin index used as the numeraire, where 0 or 1 are supported.
    @return uint256 Portfolio value scaled to 1e18 in coin `_i` units.
    """
    return self._portfolio_value(_pool, _i)


@internal
@view
def _lp_price(pool: IFXSwap, i: uint256=0) -> uint256:
    D: uint256 = staticcall pool.D()
    total_supply: uint256 = staticcall pool.totalSupply()
    return self._portfolio_value(pool, i) * D // total_supply


@view
@external
def lp_price(_pool: IFXSwap, _i: uint256=0) -> uint256:
    """
    @notice Returns LP token price in the selected coin numeraire.
    @param _pool Address of the Twocrypto(FXSwap)-style pool.
    @param _i Coin index used as the numeraire, where 0 or 1 are supported.
    @return uint256 LP price scaled to 1e18 in coin `_i` units.
    """
    return self._lp_price(_pool, _i)
