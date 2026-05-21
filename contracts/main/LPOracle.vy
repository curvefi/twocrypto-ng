# pragma version 0.4.3
# pragma optimize gas
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
    def last_timestamp() -> uint256: view
    def initial_A_gamma() -> uint256: view
    def initial_A_gamma_time() -> uint256: view
    def future_A_gamma() -> uint256: view
    def future_A_gamma_time() -> uint256: view
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
    assert staticcall pool.A() >= N_COINS**(N_COINS-1) * POOL_A_PRECISION, "Bad A value"
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
def _A_at_last_timestamp(pool: IFXSwap) -> uint256:
    # In case of stale pool price_oracle converges to last price and D is cached at last timestamp.
    #   If pool ramps A parameter the calculated invariant variables will be off,
    #   so we calculate them at one timestamp(of last interaction).
    # Replicates Twocrypto._A_gamma() but evaluates it at pool.last_timestamp().
    t: uint256 = staticcall pool.last_timestamp()
    future_t: uint256 = staticcall pool.future_A_gamma_time()
    future_A: uint256 = staticcall pool.future_A_gamma() >> 128

    if t >= future_t:
        return future_A

    initial_A: uint256 = staticcall pool.initial_A_gamma() >> 128
    initial_t: uint256 = staticcall pool.initial_A_gamma_time()

    if t <= initial_t:
        return initial_A

    # Interpolate linearly in the same way as Twocrypto._A_gamma().
    duration: uint256 = future_t - initial_t
    elapsed: uint256 = t - initial_t
    remaining: uint256 = duration - elapsed

    return unsafe_div(initial_A * remaining + future_A * elapsed, duration)


@internal
@view
def _scaled_A_raw_from_A(A_pool: uint256) -> uint256:
    # Pool stores A as: A_true * N_COINS**(N_COINS-1) * 10_000.
    # Solver expects: A_true * solver.A_PRECISION.
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

    x_py: uint256 = lp_oracle_2._portfolio_value(
        self._scaled_A_raw_from_A(self._A_at_last_timestamp(pool)),
        p_oracle * PRECISION // p_scale,
    )

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
