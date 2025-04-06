# pragma version ~=0.4.1
"""
@title Twocrypto
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2025 - all rights reserved
@notice A Curve AMM pool for 2 unpegged assets (e.g. WETH, USD).
@dev All prices in the AMM are with respect to the first token in the pool.
"""

# The AMM contract is also the LP token.
from ethereum.ercs import IERC20
implements: IERC20  

from ethereum.ercs import IERC20Detailed
implements: IERC20Detailed

import lp_token
initializes: lp_token
exports: (
    lp_token.transfer,
    lp_token.transferFrom,
    lp_token.approve,
    lp_token.balanceOf,
    lp_token.allowance,
    lp_token.totalSupply,
    lp_token.name,
    lp_token.symbol,
    lp_token.decimals,
)

from snekmate.tokens import erc20
uses: erc20 # erc20 is initialized by the lp_token module.

import packing_utils as utils

# --------------------------------- Interfaces -------------------------------

interface Math:
    def wad_exp(_power: int256) -> uint256: view
    def newton_D(
        ANN: uint256,
        gamma: uint256,
        x_unsorted: uint256[N_COINS],
        K0_prev: uint256
    ) -> uint256: view
    def get_y(
        ANN: uint256,
        gamma: uint256,
        x: uint256[N_COINS],
        D: uint256,
        i: uint256,
    ) -> uint256[2]: view
    def get_p(
        _xp: uint256[N_COINS],
        _D: uint256,
        _A_gamma: uint256[2],
    ) -> uint256: view

interface Factory:
    def admin() -> address: view
    def fee_receiver() -> address: view
    def views_implementation() -> address: view

interface Views:
    def calc_token_amount(
        amounts: uint256[N_COINS], deposit: bool, swap: address
    ) -> uint256: view
    def get_dy(
        i: uint256, j: uint256, dx: uint256, swap: address
    ) -> uint256: view
    def get_dx(
        i: uint256, j: uint256, dy: uint256, swap: address
    ) -> uint256: view


# ------------------------------- Events -------------------------------------

event TokenExchange:
    buyer: indexed(address)
    sold_id: uint256
    tokens_sold: uint256
    bought_id: uint256
    tokens_bought: uint256
    fee: uint256
    price_scale: uint256

event AddLiquidity:
    provider: indexed(address)
    token_amounts: uint256[N_COINS]
    fee: uint256
    token_supply: uint256
    price_scale: uint256

event RemoveLiquidity:
    provider: indexed(address)
    token_amounts: uint256[N_COINS]
    token_supply: uint256

event RemoveLiquidityOne:
    provider: indexed(address)
    token_amount: uint256
    coin_index: uint256
    coin_amount: uint256
    approx_fee: uint256
    price_scale: uint256

event RemoveLiquidityImbalance:
    provider: indexed(address)
    lp_token_amount: uint256
    token_amounts: uint256[N_COINS]
    approx_fee: uint256
    price_scale: uint256

event NewParameters:
    mid_fee: uint256
    out_fee: uint256
    fee_gamma: uint256
    allowed_extra_profit: uint256
    adjustment_step: uint256
    ma_time: uint256

event RampAgamma:
    initial_A: uint256
    future_A: uint256
    initial_gamma: uint256
    future_gamma: uint256
    initial_time: uint256
    future_time: uint256

event StopRampA:
    current_A: uint256
    current_gamma: uint256
    time: uint256

event ClaimAdminFee:
    admin: indexed(address)
    tokens: uint256[N_COINS]


# ----------------------- Storage/State Variables ----------------------------

N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18  # <------- The precision to convert to.
PRECISIONS: immutable(uint256[N_COINS])

MATH: public(immutable(Math))
coins: public(immutable(address[N_COINS]))
factory: public(immutable(Factory))

cached_price_scale: uint256  # <------------------------ Internal price scale.
cached_price_oracle: uint256  # <------- Price target given by moving average.

last_prices: public(uint256)
last_timestamp: public(uint256)    # idx 0 is for prices, idx 1 is for xcp.

initial_A_gamma: public(uint256)
initial_A_gamma_time: public(uint256)

future_A_gamma: public(uint256)
future_A_gamma_time: public(uint256)  # <------ Time when ramping is finished.
#         This value is 0 (default) when pool is first deployed, and only gets
#        populated by block.timestamp + future_time in `ramp_A_gamma` when the
#                      ramping process is initiated. After ramping is finished
#      (i.e. self.future_A_gamma_time < block.timestamp), the variable is left
#                                                            and not set to 0.

balances: public(uint256[N_COINS])
D: public(uint256)
xcp_profit: public(uint256)
xcp_profit_a: public(uint256)  # <--- Full profit at last claim of admin fees.

virtual_price: public(uint256)  # <------ Cached (fast to read) virtual price.
#                          The cached `virtual_price` is also used internally.

# Params that affect how price_scale get adjusted :
packed_rebalancing_params: public(uint256)  # <---------- Contains rebalancing
#               parameters allowed_extra_profit, adjustment_step, and ma_time.

# Fee params that determine dynamic fees:
packed_fee_params: public(uint256)  # <---- Packs mid_fee, out_fee, fee_gamma.

ADMIN_FEE: public(constant(uint256)) = 5 * 10**9  # <----- 50% of earned fees.
MIN_FEE: constant(uint256) = 5 * 10**5  # <-------------------------- 0.5 BPS.
MAX_FEE: constant(uint256) = 10 * 10**9
NOISE_FEE: constant(uint256) = 10**5  # <---------------------------- 0.1 BPS.

# ----------------------- Admin params ---------------------------------------

last_admin_fee_claim_timestamp: uint256
admin_lp_virtual_balance: uint256

MIN_RAMP_TIME: constant(uint256) = 86400
MIN_ADMIN_FEE_CLAIM_INTERVAL: constant(uint256) = 86400

A_MULTIPLIER: constant(uint256) = 10000
MIN_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER // 10
MAX_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER * 1000
MAX_A_CHANGE: constant(uint256) = 10
MIN_GAMMA: constant(uint256) = 10**10
MAX_GAMMA: constant(uint256) = 199 * 10**15 # 1.99 * 10**17

version: public(constant(String[8])) = "v2.1.0"

# ----------------------- Contract -------------------------------------------

@deploy
def __init__(
    _name: String[64],
    _symbol: String[32],
    _coins: address[N_COINS],
    _math: address,
    _salt: bytes32, # not used, left for compatibility with legacy factory
    packed_precisions: uint256,
    packed_gamma_A: uint256,
    packed_fee_params: uint256,
    packed_rebalancing_params: uint256,
    initial_price: uint256,
):

    MATH = Math(_math)

    factory = Factory(msg.sender)
    lp_token.__init__(_name, _symbol)
    coins = _coins

    PRECISIONS = utils.unpack_2(packed_precisions)  # <-- Precisions of coins.

    # --------------- Validate A and gamma parameters here and not in factory.
    gamma_A: uint256[2] = utils.unpack_2(packed_gamma_A)  # gamma is at idx 0.

    assert gamma_A[0] > MIN_GAMMA-1, "gamma<MIN"
    assert gamma_A[0] < MAX_GAMMA+1, "gamma>MAX"

    assert gamma_A[1] > MIN_A-1, "A<MIN"
    assert gamma_A[1] < MAX_A+1, "A>MAX"

    self.initial_A_gamma = packed_gamma_A
    self.future_A_gamma = packed_gamma_A
    # ------------------------------------------------------------------------

    self.packed_rebalancing_params = packed_rebalancing_params  # <-- Contains
    #               rebalancing params: allowed_extra_profit, adjustment_step,
    #                                                         and ma_exp_time.

    self.packed_fee_params = packed_fee_params  # <-------------- Contains Fee
    #                                  params: mid_fee, out_fee and fee_gamma.

    self.cached_price_scale = initial_price
    self.cached_price_oracle = initial_price
    self.last_prices = initial_price
    self.last_timestamp = block.timestamp
    self.xcp_profit_a = 10**18

    log IERC20.Transfer(sender=empty(address), receiver=self, value=0)  # <------- Fire empty transfer from
    #                                       0x0 to self for indexers to catch.


# ------------------- Token transfers in and out of the AMM ------------------


@internal
def _transfer_in(
    _coin_idx: uint256,
    _dx: uint256,
    sender: address,
    expect_optimistic_transfer: bool,
) -> uint256:
    """
    @notice Transfers `_coin` from `sender` to `self` and calls `callback_sig`
            if it is not empty.
    @params _coin_idx uint256 Index of the coin to transfer in.
    @params dx amount of `_coin` to transfer into the pool.
    @params sender address to transfer `_coin` from.
    @params expect_optimistic_transfer bool True if pool expects user to transfer.
            This is only enabled for exchange_received.
    @return The amount of tokens received.
    """
    coin_balance: uint256 = staticcall IERC20(coins[_coin_idx]).balanceOf(self)

    if expect_optimistic_transfer:  # Only enabled in exchange_received:
        # it expects the caller of exchange_received to have sent tokens to
        # the pool before calling this method.

        # If someone donates extra tokens to the contract: do not acknowledge.
        # We only want to know if there are dx amount of tokens. Anything extra,
        # we ignore. This is why we need to check if received_amounts (which
        # accounts for coin balances of the contract) is atleast dx.
        # If we checked for received_amounts == dx, an extra transfer without a
        # call to exchange_received will break the method.
        dx: uint256 = coin_balance - self.balances[_coin_idx]
        assert dx >= _dx, "user didn't give us coins"

        # Adjust balances
        self.balances[_coin_idx] += dx

        return dx

    # ----------------------------------------------- ERC20 transferFrom flow.

    # EXTERNAL CALL
    assert extcall IERC20(coins[_coin_idx]).transferFrom(
        sender,
        self,
        _dx,
        default_return_value=True
    ), "transferFrom failed"

    dx: uint256 = staticcall IERC20(coins[_coin_idx]).balanceOf(self) - coin_balance
    self.balances[_coin_idx] += dx
    return dx


@internal
def _transfer_out(_coin_idx: uint256, _amount: uint256, receiver: address):
    """
    @notice Transfer a single token from the pool to receiver.
    @params _coin_idx uint256 Index of the token to transfer out
    @params _amount Amount of token to transfer out
    @params receiver Address to send the tokens to
    """

    # Adjust balances before handling transfers:
    self.balances[_coin_idx] -= _amount

    # EXTERNAL CALL
    assert extcall IERC20(coins[_coin_idx]).transfer(
        receiver,
        _amount,
        default_return_value=True
    ), "transfer failed"


# -------------------------- AMM Main Functions ------------------------------


@external
@nonreentrant
def exchange(
    i: uint256,
    j: uint256,
    dx: uint256,
    min_dy: uint256,
    receiver: address = msg.sender
) -> uint256:
    """
    @notice Exchange using wrapped native token by default
    @param i Index value for the input coin
    @param j Index value for the output coin
    @param dx Amount of input coin being swapped in
    @param min_dy Minimum amount of output coin to receive
    @param receiver Address to send the output coin to. Default is msg.sender
    @return uint256 Amount of tokens at index j received by the `receiver
    """
    # _transfer_in updates self.balances here:
    dx_received: uint256 = self._transfer_in(
        i,
        dx,
        msg.sender,
        False
    )

    # No ERC20 token transfers occur here:
    out: uint256[3] = self._exchange(
        i,
        j,
        dx_received,
        min_dy,
    )

    # _transfer_out updates self.balances here. Update to state occurs before
    # external calls:
    self._transfer_out(j, out[0], receiver)

    # log:
    log TokenExchange(buyer=msg.sender, sold_id=i, tokens_sold=dx_received, bought_id=j, tokens_bought=out[0], fee=out[1], price_scale=out[2])

    return out[0]


@external
@nonreentrant
def exchange_received(
    i: uint256,
    j: uint256,
    dx: uint256,
    min_dy: uint256,
    receiver: address = msg.sender,
) -> uint256:
    """
    @notice Exchange: but user must transfer dx amount of coin[i] tokens to pool first.
            Pool will not call transferFrom and will only check if a surplus of
            coins[i] is greater than or equal to `dx`.
    @dev Use-case is to reduce the number of redundant ERC20 token
         transfers in zaps. Primarily for dex-aggregators/arbitrageurs/searchers.
         Note for users: please transfer + exchange_received in 1 tx.
    @param i Index value for the input coin
    @param j Index value for the output coin
    @param dx Amount of input coin being swapped in
    @param min_dy Minimum amount of output coin to receive
    @param receiver Address to send the output coin to
    @return uint256 Amount of tokens at index j received by the `receiver`
    """
    # _transfer_in updates self.balances here:
    dx_received: uint256 = self._transfer_in(
        i,
        dx,
        msg.sender,
        True  # <---- expect_optimistic_transfer is set to True here.
    )

    # No ERC20 token transfers occur here:
    out: uint256[3] = self._exchange(
        i,
        j,
        dx_received,
        min_dy,
    )

    # _transfer_out updates self.balances here. Update to state occurs before
    # external calls:
    self._transfer_out(j, out[0], receiver)

    # log:
    log TokenExchange(buyer=msg.sender, sold_id=i, tokens_sold=dx_received, bought_id=j, tokens_bought=out[0], fee=out[1], price_scale=out[2])

    return out[0]


@external
@nonreentrant
def add_liquidity(
    amounts: uint256[N_COINS],
    min_mint_amount: uint256,
    receiver: address = msg.sender
) -> uint256:
    """
    @notice Adds liquidity into the pool.
    @param amounts Amounts of each coin to add.
    @param min_mint_amount Minimum amount of LP to mint.
    @param receiver Address to send the LP tokens to. Default is msg.sender
    @return uint256 Amount of LP tokens received by the `receiver
    """


    assert amounts[0] + amounts[1] > 0, "no coins to add"

    # --------------------- Get prices, balances -----------------------------

    old_balances: uint256[N_COINS] = self.balances

    ########################## TRANSFER IN <-------

    amounts_received: uint256[N_COINS] = empty(uint256[N_COINS])
    # This variable will contain the old balances + the amounts received.
    balances: uint256[N_COINS] = self.balances
    for i: uint256 in range(N_COINS):
        if amounts[i] > 0:
            # Updates self.balances here:
            amounts_received[i] = self._transfer_in(
                i,
                amounts[i],
                msg.sender,
                False,  # <--------------------- Disable optimistic transfers.
            )
            balances[i] += amounts_received[i]

    price_scale: uint256 = self.cached_price_scale
    xp: uint256[N_COINS] = self._xp(balances, price_scale)
    old_xp: uint256[N_COINS] = self._xp(old_balances, price_scale)

    # amountsp (amounts * p) contains the scaled `amounts_received` of each coin.
    amountsp: uint256[N_COINS] = empty(uint256[N_COINS])
    for i: uint256 in range(N_COINS):
        if amounts_received[i] > 0:
            amountsp[i] = xp[i] - old_xp[i]
    # -------------------- Calculate LP tokens to mint -----------------------

    A_gamma: uint256[2] = self._A_gamma()

    old_D: uint256 = 0
    if self._is_ramping():
        # Recalculate D if A and/or gamma are ramping because the shape of
        # the bonding curve is changing.
        old_D = staticcall MATH.newton_D(A_gamma[0], A_gamma[1], old_xp, 0)
    else:
        old_D = self.D

    D: uint256 = staticcall MATH.newton_D(A_gamma[0], A_gamma[1], xp, 0)

    token_supply: uint256 = erc20.totalSupply
    d_token: uint256 = 0
    if old_D > 0:
        d_token = token_supply * D // old_D - token_supply
    else:
        d_token = self._xcp(D, price_scale)  # <----- Making initial virtual price equal to 1.

    assert d_token > 0, "nothing minted"

    d_token_fee: uint256 = 0
    if old_D > 0:

        d_token_fee = (
            self._calc_token_fee(amountsp, xp) * d_token // 10**10 + 1
        )

        d_token -= d_token_fee
        token_supply += d_token
        erc20._mint(receiver, d_token)
        self.admin_lp_virtual_balance += unsafe_div(ADMIN_FEE * d_token_fee, 10**10)

        price_scale = self.tweak_price(A_gamma, xp, D)

    else:

        # (re)instatiating an empty pool:

        self.D = D
        self.virtual_price = 10**18
        self.xcp_profit = 10**18
        self.xcp_profit_a = 10**18

        erc20._mint(receiver, d_token)

    assert d_token >= min_mint_amount, "slippage"

    # ---------------------------------------------- Log and claim admin fees.

    log AddLiquidity(
        provider=receiver,
        token_amounts=amounts_received,
        fee=d_token_fee,
        token_supply=token_supply,
        price_scale=price_scale
    )

    return d_token


@external
@nonreentrant
def remove_liquidity(
    amount: uint256,
    min_amounts: uint256[N_COINS],
    receiver: address = msg.sender,
) -> uint256[N_COINS]:
    """
    @notice This withdrawal method is very safe, does no complex math since
            tokens are withdrawn in balanced proportions. No fees are charged.
    @param amount Amount of LP tokens to burn
    @param min_amounts Minimum amounts of tokens to withdraw
    @param receiver Address to send the withdrawn tokens to
    @return uint256[3] Amount of pool tokens received by the `receiver`
    """

    # -------------------------------------------------------- Burn LP tokens.

    # We cache the total supply to avoid multiple SLOADs. It is important to do
    # this before the burnFrom call, as the burnFrom call will reduce the supply.
    total_supply: uint256 = erc20.totalSupply
    erc20._burn(msg.sender, amount)

    # There are two cases for withdrawing tokens from the pool.
    #   Case 1. Withdrawal does not empty the pool.
    #           In this situation, D is adjusted proportional to the amount of
    #           LP tokens burnt. ERC20 tokens transferred is proportional
    #           to : (AMM balance * LP tokens in) / LP token total supply
    #   Case 2. Withdrawal empties the pool.
    #           In this situation, all tokens are withdrawn and the invariant
    #           is reset.

    withdraw_amounts: uint256[N_COINS] = empty(uint256[N_COINS])

    adjusted_amount: uint256 = amount
    if amount == total_supply:  # <----------------------------------- Case 2.

        for i: uint256 in range(N_COINS):

            withdraw_amounts[i] = self.balances[i]

    else:  # <-------------------------------------------------------- Case 1.
        # To prevent rounding errors, favor LPs a tiny bit.
        adjusted_amount -= 1

        for i: uint256 in range(N_COINS):
            withdraw_amounts[i] = self.balances[i] * adjusted_amount // total_supply
            assert withdraw_amounts[i] >= min_amounts[i], "slippage"

    D: uint256 = self.D
    # Reduce D proportionally to the amount of tokens leaving. Since withdrawals
    # are balanced, this is a simple subtraction. If amount == total_supply,
    # D will be 0.
    self.D = D - unsafe_div(D * adjusted_amount, total_supply)

    # ---------------------------------- Transfers ---------------------------

    for i: uint256 in range(N_COINS):
        # _transfer_out updates self.balances here. Update to state occurs
        # before external calls:
        self._transfer_out(i, withdraw_amounts[i], receiver)

    # We intentionally use the unadjusted `amount` here as the amount of lp
    # tokens burnt is `amount`, regardless of the rounding error.
    log RemoveLiquidity(provider=msg.sender, token_amounts=withdraw_amounts, token_supply=total_supply - amount)

    return withdraw_amounts

@external
@nonreentrant
def remove_liquidity_fixed_out(
    token_amount: uint256,
    i: uint256,
    amount_i: uint256,
    min_amount_j: uint256,
    receiver: address = msg.sender
) -> uint256:
    """
    @notice Withdrawal where amount of token i is specified
    @param token_amount LP Token amount to burn
    @param i Index of the coin to withdraw
    @param amount_i exact amount of token i which will be withdrawn
    @param min_amount_j Minimum amount of token j=1-i to withdraw.
    @param receiver Address to send the withdrawn tokens to
    @return Amount of tokens at index j=1-i received by the `receiver`
    """
    return self._remove_liquidity_fixed_out(
        token_amount,
        i,
        amount_i,
        min_amount_j,
        receiver,
    )


@external
@nonreentrant
def remove_liquidity_one_coin(
    lp_token_amount: uint256,
    i: uint256,
    min_amount: uint256,
    receiver: address = msg.sender
) -> uint256:
    """
    @notice Withdraw liquidity in a single coin.
    @param lp_token_amount Amount of LP tokens to burn.
    @param i Index of the coin to withdraw.
    @param min_amount Minimum amount of coin[i] to withdraw.
    @param receiver Address to send the withdrawn tokens to
    @return Amount of coin[i] tokens received by the `receiver`
    """
    return self._remove_liquidity_fixed_out(
        lp_token_amount,
        1 - i, # Here we flip i because we want to constrain the other coin to be zero.
        0, # We set the amount of coin[1 - i] to be withdrawn to 0.
        min_amount,
        receiver,
    )


@internal
def _remove_liquidity_fixed_out(
    token_amount: uint256,
    i: uint256,
    amount_i: uint256,
    min_amount_j: uint256,
    receiver: address,
) -> uint256:

    self._claim_admin_fees()

    A_gamma: uint256[2] = self._A_gamma()

    # Amount of coin[j] withdrawn.
    dy: uint256 = 0
    # New value of D after the withdrawal.
    D: uint256 = 0
    # New scaled balances after the withdrawal.
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    approx_fee: uint256 = 0

    # ------------------------------------------------------------------------

    dy, D, xp, approx_fee = self._calc_withdraw_fixed_out(
        A_gamma,
        token_amount,
        i,
        amount_i,
    )

    assert dy >= min_amount_j, "slippage"

    # ---------------------------- State Updates -----------------------------

    erc20._burn(msg.sender, token_amount)

    price_scale: uint256 = self.tweak_price(A_gamma, xp, D)

    self._transfer_out(i, amount_i, receiver)
    self._transfer_out(1 - i, dy, receiver)

    token_amounts: uint256[N_COINS] = empty(uint256[N_COINS])
    token_amounts[i] = amount_i
    token_amounts[1-i] = dy

    log RemoveLiquidityImbalance(
        provider=msg.sender,
        lp_token_amount=token_amount,
        token_amounts=token_amounts,
        approx_fee=approx_fee * token_amount // PRECISION,
        price_scale=price_scale
    )

    return dy


@internal
def _exchange(
    i: uint256,
    j: uint256,
    dx_received: uint256,
    min_dy: uint256,
) -> uint256[3]:

    assert i != j, "same coin"
    assert dx_received > 0, "zero dx"

    A_gamma: uint256[2] = self._A_gamma()
    balances: uint256[N_COINS] = self.balances
    dy: uint256 = 0

    y: uint256 = balances[j]
    x0: uint256 = balances[i] - dx_received  # old xp[i]

    price_scale: uint256 = self.cached_price_scale
    xp: uint256[N_COINS] = self._xp(balances, price_scale)

    # ----------- Update invariant if A, gamma are undergoing ramps ---------

    if self._is_ramping():

        x0 *= PRECISIONS[i]

        if i > 0:
            x0 = unsafe_div(x0 * price_scale, PRECISION)

        x1: uint256 = xp[i]  # <------------------ Back up old value in xp ...
        xp[i] = x0                                                         # |
        self.D = staticcall MATH.newton_D(A_gamma[0], A_gamma[1], xp, 0)   # |
        xp[i] = x1  # <-------------------------------------- ... and restore.

    # ----------------------- Calculate dy and fees --------------------------

    D: uint256 = self.D
    y_out: uint256[2] = staticcall MATH.get_y(A_gamma[0], A_gamma[1], xp, D, j)
    dy = xp[j] - y_out[0]
    xp[j] -= dy
    dy -= 1

    if j > 0:
        dy = dy * PRECISION // price_scale
    dy //= PRECISIONS[j]

    fee: uint256 = unsafe_div(self._fee(xp) * dy, 10**10)
    dy -= fee  # <--------------------- Subtract fee from the outgoing amount.
    assert dy >= min_dy, "slippage"
    y -= dy

    y *= PRECISIONS[j]
    if j > 0:
        y = unsafe_div(y * price_scale, PRECISION)
    xp[j] = y  # <------------------------------------------------- Update xp.

    # ------ Tweak price_scale with good initial guess for newton_D ----------

    # Technically a swap wouldn't require to recompute D, however since we're taking
    # fees, we need to update D to reflect the new balances.
    D = staticcall MATH.newton_D(A_gamma[0], A_gamma[1], xp, y_out[1])

    price_scale = self.tweak_price(A_gamma, xp, D)

    return [dy, fee, price_scale]


@internal
def tweak_price(
    A_gamma: uint256[2],
    _xp: uint256[N_COINS],
    D: uint256,
) -> uint256:
    """
    @notice Updates price_oracle, last_price and conditionally adjusts
            price_scale. This is called whenever there is an unbalanced
            liquidity operation: _exchange, add_liquidity, or
            remove_liquidity_fixed_out.
    @dev Contains main liquidity rebalancing logic, by tweaking `price_scale`.
    @param A_gamma Array of A and gamma parameters.
    @param _xp Array of current balances.
    @param new_D New D value.
    """

    # ---------------------------- Read storage ------------------------------

    price_oracle: uint256 = self.cached_price_oracle
    last_prices: uint256 = self.last_prices
    price_scale: uint256 = self.cached_price_scale
    rebalancing_params: uint256[3] = utils.unpack_3(self.packed_rebalancing_params)
    # Contains: allowed_extra_profit, adjustment_step, ma_time. -----^

    # ------------------ Update Price Oracle if needed -----------------------

    last_timestamp: uint256 = self.last_timestamp
    alpha: uint256 = 0
    if last_timestamp < block.timestamp:  # 0th index is for price_oracle.

        #   The moving average price oracle is calculated using the last_price
        #      of the trade at the previous block, and the price oracle logged
        #              before that trade. This can happen only once per block.

        # ------------------ Calculate moving average params -----------------

        alpha = staticcall MATH.wad_exp(
            -convert(
                unsafe_div(
                    unsafe_sub(block.timestamp, last_timestamp) * 10**18,
                    rebalancing_params[2]  # <----------------------- ma_time.
                ),
                int256,
            )
        )

        # ---------------------------------------------- Update price oracles.

        # ----------------- We cap state price that goes into the EMA with
        #                                                 2 x price_scale.
        price_oracle = unsafe_div(
            min(last_prices, 2 * price_scale) * (10**18 - alpha) +
            price_oracle * alpha,  # ^-------- Cap spot price into EMA.
            10**18
        )

        self.cached_price_oracle = price_oracle
        self.last_timestamp = block.timestamp

    #  `price_oracle` is used further on to calculate its vector distance from
    # price_scale. This distance is used to calculate the amount of adjustment
    # to be done to the price_scale.
    # ------------------------------------------------------------------------

    # Here we update the spot price, please notice that this value is unsafe
    # and can be manipulated.
    self.last_prices = unsafe_div(
        staticcall MATH.get_p(_xp, D, A_gamma) * price_scale,
        10**18
    )

    # ---------- Update profit numbers without price adjustment first --------

    xcp_profit: uint256 = 10**18
    virtual_price: uint256 = 10**18

    # `totalSupply` will not change during this function call.
    total_supply: uint256 = erc20.totalSupply
    old_virtual_price: uint256 = self.virtual_price
    if old_virtual_price > 0:
        xcp: uint256 = self._xcp(D, price_scale)

        # We increase the virtual price by 1 to avoid off by one rounding
        # errors. While this can lead to a small profit overestimation,
        # given virtual_price has 18 decimals, this is negligible.
        virtual_price = 10**18 * xcp // total_supply + 1

        # Safe to do unsafe_div as old_virtual_price > 0.
        old_xcp_profit: uint256 = self.xcp_profit
        xcp_profit = unsafe_div(
            old_xcp_profit * virtual_price,
            old_virtual_price
        )

        # If A and gamma are not being ramped, we only allow the virtual price to
        # to increase.
        # This is does not imply that the virtual price will have increased at the
        # end of this function: it can still decrease if the pool rebalances.
        if not (virtual_price > old_virtual_price):
            # If A and gamma are being ramped, we allow the virtual price to decrease,
            # as changing the shape of the bonding curve causes losses in the pool.
            assert self._is_ramping(), "virtual price decreased"

    self.xcp_profit = xcp_profit

    # ------------ Rebalance liquidity if there's enough profits to adjust it:
    #
    # Mathematical basis for rebalancing condition:
    # 1. xcp_profit compounds as (1+r)^n, where r is some hypothetical growth rate
    # 2. We reserve half of the growth for LPs: (1+r/2)^n, rest is used to rebalance the pool
    # 3. (Using taylor expansions) (1+r/2)^n ~= (1+r)^(n/2) = sqrt((1+r)^n)
    # 4. Therefore half-rate growth equals sqrt(xcp_profit)
    #
    # Rebalancing condition transformation:
    # virtual_price > sqrt(xcp_profit) + allowed_extra_profit
    # (virtual_price - allowed_extra_profit)^2 > xcp_profit
    #
    # The allowed_extra_profit parameter prevents reverting gas-wasting rebalances
    # by ensuring sufficient profit margin
    if (virtual_price - rebalancing_params[0])**2 > xcp_profit * 10**18:
        # allowed_extra_profit ---^
        # Calculate the vector distance between price_scale and price_oracle.
        norm: uint256 = unsafe_div(
            unsafe_mul(price_oracle, 10**18), price_scale
        )
        if norm > 10**18:
            norm = unsafe_sub(norm, 10**18)
        else:
            norm = unsafe_sub(10**18, norm)
        adjustment_step: uint256 = max(
            rebalancing_params[1], unsafe_div(norm, 5)
        )  #           ^------------------------------------- adjustment_step.

        # We only adjust prices if the vector distance between price_oracle
        # and price_scale is large enough. This check ensures that no rebalancing
        # occurs if the distance is low i.e. the pool prices are pegged to the
        # oracle prices.
        if norm > adjustment_step:
            # Calculate new price scale.
            p_new: uint256 = unsafe_div(
                price_scale * unsafe_sub(norm, adjustment_step) +
                adjustment_step * price_oracle,
                norm
            )  # <---- norm is non-zero and gt adjustment_step; unsafe = safe.

            # ---------------- Update stale xp (using price_scale) with p_new.

            xp: uint256[N_COINS] = [
                _xp[0],
                unsafe_div(_xp[1] * p_new, price_scale)
            ]

            # ------------------------------------------ Update D with new xp.
            new_D: uint256 = staticcall MATH.newton_D(A_gamma[0], A_gamma[1], xp, 0)

            # ------------------------------------- Convert xp to real prices.

            xcp: uint256 = self._xcp(new_D, p_new)

            # unsafe_div because we did safediv before (if vp>1e18)
            new_virtual_price: uint256 = unsafe_div(
                10**18 * xcp, total_supply
            )

            # If we've got enough profit we rebalance the liquidity in the
            # pool by moving the price_scale closer to the oracle price.
            if (
                new_virtual_price > 10**18 and
                new_virtual_price ** 2 > xcp_profit * 10**18
            ):

                self.D = new_D
                self.virtual_price = new_virtual_price
                self.cached_price_scale = p_new

                return p_new

    # If we end up here price_scale was not adjusted. So we update the state
    # with the virtual price and D we calculated before attempting a rebalance.
    self.D = D
    self.virtual_price = virtual_price

    return price_scale


@internal
def _claim_admin_fees():
    """
    @notice Claims admin fees and sends it to fee_receiver set in the factory.
    @dev Functionally similar to:
         1. Calculating admin's share of fees,
         2. minting LP tokens,
         3. admin claims underlying tokens via remove_liquidity.
    """

    # --------------------- Check if fees can be claimed ---------------------

    # Disable fee claiming if:
    # 1. If time passed since last fee claim is less than
    #    MIN_ADMIN_FEE_CLAIM_INTERVAL.
    # 2. Pool parameters are being ramped.

    last_claim_time: uint256 = self.last_admin_fee_claim_timestamp
    if (
        unsafe_sub(block.timestamp, last_claim_time) < MIN_ADMIN_FEE_CLAIM_INTERVAL or
        self._is_ramping()
    ):
        return

    xcp_profit: uint256 = self.xcp_profit  # <---------- Current pool profits.
    xcp_profit_a: uint256 = self.xcp_profit_a  # <- Profits at previous claim.
    current_lp_token_supply: uint256 = erc20.totalSupply

    # Do not claim admin fees if:
    # 1. insufficient profits accrued since last claim, and
    # 2. there are less than 10**18 (or 1 unit of) lp tokens, else it can lead
    #    to manipulated virtual prices.

    if xcp_profit <= xcp_profit_a or current_lp_token_supply < 10**18:
        return

    # ---------- Conditions met to claim admin fees: compute state. ----------

    A_gamma: uint256[2] = self._A_gamma()
    D: uint256 = self.D
    vprice: uint256 = self.virtual_price
    price_scale: uint256 = self.cached_price_scale
    fee_receiver: address = staticcall factory.fee_receiver()
    balances: uint256[N_COINS] = self.balances

    #  Admin fees are calculated as follows.
    #      1. Calculate accrued profit since last claim. `xcp_profit`
    #         is the current profits. `xcp_profit_a` is the profits
    #         at the previous claim.
    #      2. Take out admin's share, which is hardcoded at 5 * 10**9.
    #         (50% => half of 100% => 10**10 / 2 => 5 * 10**9).
    #      3. Since half of the profits go to rebalancing the pool, we
    #         are left with half; so divide by 2.

    fees: uint256 = unsafe_div(
        unsafe_sub(xcp_profit, xcp_profit_a) * ADMIN_FEE, 2 * 10**10
    )

    # ------------------------------ Claim admin fees by minting admin's share
    #                                                of the pool in LP tokens.

    # This is the admin fee tokens claimed in self.add_liquidity. We add it to
    # the LP token share that the admin needs to claim:
    admin_share: uint256 = self.admin_lp_virtual_balance
    frac: uint256 = 0
    if fee_receiver != empty(address) and fees > 0:

        # -------------------------------- Calculate admin share to be minted.
        frac = vprice * 10**18 // (vprice - fees) - 10**18
        admin_share += current_lp_token_supply * frac // 10**18

        # ------ Subtract fees from profits that will be used for rebalancing.
        xcp_profit -= fees * 2

    # ------------------- Recalculate virtual_price following admin fee claim.
    total_supply_including_admin_share: uint256 = (
        current_lp_token_supply + admin_share
    )
    vprice = (
        10**18 * self._xcp(D, price_scale) //
        total_supply_including_admin_share
    )

    # Do not claim fees if doing so causes virtual price to drop below 10**18.
    if vprice < 10**18:
        return

    # ---------------------------- Update State ------------------------------

    # Set admin virtual LP balances to zero because we claimed:
    self.admin_lp_virtual_balance = 0

    self.xcp_profit = xcp_profit
    self.last_admin_fee_claim_timestamp = block.timestamp

    # Since we reduce balances: virtual price goes down
    self.virtual_price = vprice

    # Adjust D after admin seemingly removes liquidity
    self.D = D - unsafe_div(D * admin_share, total_supply_including_admin_share)

    if xcp_profit > xcp_profit_a:
        self.xcp_profit_a = xcp_profit  # <-------- Cache last claimed profit.

    # --------------------------- Handle Transfers ---------------------------

    admin_tokens: uint256[N_COINS] = empty(uint256[N_COINS])
    if admin_share > 0:

        for i: uint256 in range(N_COINS):

            admin_tokens[i] = (
                balances[i] * admin_share //
                total_supply_including_admin_share
            )

            # _transfer_out tokens to admin and update self.balances. State
            # update to self.balances occurs before external contract calls:
            self._transfer_out(i, admin_tokens[i], fee_receiver)

        log ClaimAdminFee(admin=fee_receiver, tokens=admin_tokens)


@internal
@view
def _xp(
    balances: uint256[N_COINS],
    price_scale: uint256,
) -> uint256[N_COINS]:
    return [
        balances[0] * PRECISIONS[0],
        unsafe_div(balances[1] * PRECISIONS[1] * price_scale, PRECISION)
    ]

@internal
@view
def _is_ramping() -> bool:
    """
    @notice Checks if A and gamma are ramping.
    @return bool True if A and/or gamma are ramping, False otherwise.
    """
    return self.future_A_gamma_time > block.timestamp

@view
@internal
def _A_gamma() -> uint256[2]:
    t1: uint256 = self.future_A_gamma_time

    A_gamma_1: uint256 = self.future_A_gamma
    gamma1: uint256 = A_gamma_1 & 2**128 - 1
    A1: uint256 = A_gamma_1 >> 128

    if block.timestamp < t1:

        # --------------- Handle ramping up and down of A --------------------

        A_gamma_0: uint256 = self.initial_A_gamma
        t0: uint256 = self.initial_A_gamma_time

        t1 -= t0
        t0 = block.timestamp - t0
        t2: uint256 = t1 - t0

        A1 = ((A_gamma_0 >> 128) * t2 + A1 * t0) // t1
        gamma1 = ((A_gamma_0 & 2**128 - 1) * t2 + gamma1 * t0) // t1

    return [A1, gamma1]


@internal
@view
def _fee(xp: uint256[N_COINS]) -> uint256:

    # unpack mid_fee, out_fee, fee_gamma
    fee_params: uint256[3] = utils.unpack_3(self.packed_fee_params)

    # warm up variable with sum of balances
    B: uint256 = xp[0] + xp[1]

    # balance indicator that goes from 10**18 (perfect pool balance) to 0 (very imbalanced, 100:1 and worse)
    # N^N * (xp[0] * xp[1]) / (xp[0] + xp[1])**2
    B = PRECISION * N_COINS**N_COINS * xp[0] // B * xp[1] // B

    # regulate slope using fee_gamma
    # fee_gamma * balance_term / (fee_gamma * balance_term + 1 - balance_term)
    B = fee_params[2] * B // (unsafe_div(fee_params[2] * B, 10**18)  + 10**18 - B)

    # mid_fee * B + out_fee * (1 - B)
    return unsafe_div(fee_params[0] * B + fee_params[1] * (10**18 - B), 10**18)


@internal
@pure
def _xcp(D: uint256, price_scale: uint256) -> uint256:
    # We compute xcp according to the formula in the whitepaper:

    # The following explanation relies on the assumption that the
    # balances have already been scaled by the price scale as shown
    # above.

    # The intuition behind this formula comes from the UniV2
    # whitepaper where the initial amount of LP tokens is set to
    # the geometric mean of the balances, in fact xcp stands for
    # x (balances) constant product.

    # Our invariant behaves in such a way that at the center of the
    # bonding curve:
    # (1) D(x, y) = D(x, x) = 2x.
    # In simple terms this mean that at the center the pool behaves exactly
    # like a constant sum AMM.
    # Here we want to treat the pool as a constant product AMM:
    # (2) xy = k (the constant product invariant).
    # (3) x^2 = k (because we are at the center of the curve where x = y).
    # (4) x = D / 2 (because D(x, y) = 2x in (1]).

    # For xp[0] the price scale is 1 (see whitepaper) so we can obtain
    # x[0] directly from [4]
    # For xp[1] the price scale is != 1 so we divide by the price scale
    # that has unit (coin0/coin1) to convert D (coin0) into xp[1] (coin1):
    # (5) x[1] = D / 2 / price_scale.

    # In the end we take the geometric average of the scaled balances:
    # xcp = sqrt(D // (N_COINS * 1) * D // (N_COINS * price_scale))
    # this is equivalent to D // N_COINS * sqrt(price_scale).
    return D * PRECISION // N_COINS // isqrt(PRECISION * price_scale)


@view
@internal
def _calc_token_fee(amounts: uint256[N_COINS], xp: uint256[N_COINS]) -> uint256:
    # fee = sum(amounts_i - avg(amounts)) * fee' / sum(amounts)
    fee: uint256 = unsafe_div(
        unsafe_mul(self._fee(xp), N_COINS),
        unsafe_mul(4, unsafe_sub(N_COINS, 1))
    )

    S: uint256 = 0
    for _x: uint256 in amounts:
        S += _x

    avg: uint256 = unsafe_div(S, N_COINS)
    Sdiff: uint256 = 0

    for _x: uint256 in amounts:
        if _x > avg:
            Sdiff += unsafe_sub(_x, avg)
        else:
            Sdiff += unsafe_sub(avg, _x)

    return fee * Sdiff // S + NOISE_FEE

@view
@external
def calc_withdraw_fixed_out(lp_token_amount: uint256, i: uint256, amount_i: uint256) -> uint256:
    """
    @notice Calculate the amounts of coin[1-i] that will be received for burning the lp
    tokens while specifying the amount of coin[i] to be withdrawn.
    @param lp_token_amount LP Token amount to burn.
    @param i index of the token for which the withdrawal amount is specified.
    @param amount_i exact amount of token i which will be withdrawn.
    @return uint256 Amount of token 1-i received for burning token_amount LP tokens.
    """
    return self._calc_withdraw_fixed_out(
        self._A_gamma(),
        lp_token_amount,
        i,
        amount_i,
    )[0]

@view
@external
def calc_withdraw_one_coin(lp_token_amount: uint256, i: uint256) -> uint256:
    """
    @notice Calculate how much of coin[i] will be received when withdrawing liquidity in a single coin.
    @dev This function uses the logic from _calc_withdraw_fixed_out by setting amount_i to 0.
        This forces the withdrawal to be entirely in the other coin.
    @param lp_token_amount LP Token amount to burn.
    @param i index of the token to be withdrawn
    @return uint256 Amount of coin[i] tokens received for burning token_amount LP tokens.
    """
    return self._calc_withdraw_fixed_out(
        self._A_gamma(),
        lp_token_amount,
        1 - i, # Here we flip i because we want to constrain the other coin to be zero.
        0, # We set the amount of coin[1 - i] to be withdrawn to 0.
    )[0]

@internal
@view
def _calc_withdraw_fixed_out(
    A_gamma: uint256[2],
    lp_token_amount: uint256,
    i: uint256,
    amount_i: uint256,
) -> (uint256, uint256, uint256[N_COINS], uint256):
    """
    Withdraws specified number of LP tokens while amount of coin `i` is also specified
    """

    token_supply: uint256 = erc20.totalSupply
    assert lp_token_amount <= token_supply, "withdraw > supply"

    # Since N_COINS = 2, we don't need to check if i < N_COINS
    # because j = 1 - i will underflow for any i > 1
    j: uint256 = 1 - i

    balances: uint256[N_COINS] = self.balances

    # -------------------------- Calculate D0 and xp -------------------------

    price_scale: uint256 = self.cached_price_scale
    xp: uint256[N_COINS] = self._xp(balances, price_scale)

    D: uint256 = 0
    if self._is_ramping():
        D = staticcall MATH.newton_D(A_gamma[0], A_gamma[1], xp, 0)
    else:
        D = self.D


    # ------------------------------ Amounts calc ----------------------------
    dD: uint256 = unsafe_div(lp_token_amount * D, token_supply)
    xp_new: uint256[N_COINS] = xp

    price_scales: uint256[N_COINS] = [PRECISION * PRECISIONS[0], price_scale * PRECISIONS[1]]

    # amountsp (amounts * p) is the dx and dy amounts that the user will receive
    # after the withdrawal scaled for the price scale (p).
    amountsp: uint256[N_COINS] = empty(uint256[N_COINS])
    # This withdrawal method fixes the amount of token i to be withdrawn,
    # this is why here we don't compute amountsp[i] but we give it as a
    # constraint (after appropriate scaling).
    amountsp[i] = unsafe_div(amount_i * price_scales[i], PRECISION)
    xp_new[i] -= amountsp[i]

    # We compute the position on the y axis after a withdrawal of dD with the constraint
    # that xp_new[i] has been reduced by amountsp[i]. This is the new position on the curve
    # after the withdrawal without applying fees.
    y: uint256 = (staticcall MATH.get_y(A_gamma[0], A_gamma[1], xp_new, D - dD, j))[0]
    amountsp[j] = xp[j] - y
    xp_new[j] = y

    # The only way to compute the fees is to simulate a withdrawal as we have done
    # above and then rewind and apply the fees.
    approx_fee: uint256 = self._calc_token_fee(amountsp, xp_new)
    dD -= dD * approx_fee // 10**10 + 1

    # We reduce D by the withdrawn + fees.
    D -= dD
    # Same reasoning as before except now we're charging fees.
    y = (staticcall MATH.get_y(A_gamma[0], A_gamma[1], xp_new, D, j))[0]
    # We descale y to obtain the amount dy in balances and not scaled balances.
    dy: uint256 = (xp[j] - y) * PRECISION // price_scales[j]
    xp_new[j] = y

    return dy, D, xp_new, approx_fee

# ------------------------- AMM View Functions -------------------------------


@internal
@view
def internal_price_oracle() -> uint256:
    """
    @notice Returns the oracle price of the coin at index `k` w.r.t the coin
            at index 0.
    @dev The oracle is an exponential moving average, with a periodicity
         determined by `self.ma_time`. The aggregated prices are cached state
         prices (dy/dx) calculated AFTER the latest trade.
    @param k The index of the coin.
    @return uint256 Price oracle value of kth coin.
    """
    price_oracle: uint256 = self.cached_price_oracle
    price_scale: uint256 = self.cached_price_scale
    last_prices_timestamp: uint256 = self.last_timestamp

    if last_prices_timestamp < block.timestamp:  # <------------ Update moving
        #                                                   average if needed.

        last_prices: uint256 = self.last_prices
        ma_time: uint256 = utils.unpack_3(self.packed_rebalancing_params)[2]
        alpha: uint256 = staticcall MATH.wad_exp(
            -convert(
                unsafe_sub(block.timestamp, last_prices_timestamp) * 10**18 // ma_time,
                int256,
            )
        )

        # ---- We cap state price that goes into the EMA with 2 x price_scale.
        return (
            min(last_prices, 2 * price_scale) * (10**18 - alpha) +
            price_oracle * alpha
        ) // 10**18

    return price_oracle


@external
@view
def fee_receiver() -> address:
    """
    @notice Returns the address of the admin fee receiver.
    @return address Fee receiver.
    """
    return staticcall factory.fee_receiver()


@external
@view
def admin() -> address:
    """
    @notice Returns the address of the pool's admin.
    @return address Admin.
    """
    return staticcall factory.admin()


@external
@view
def calc_token_amount(amounts: uint256[N_COINS], deposit: bool) -> uint256:
    """
    @notice Calculate LP tokens minted or to be burned for depositing or
            removing `amounts` of coins
    @dev Includes fee.
    @param amounts Amounts of tokens being deposited or withdrawn
    @param deposit True if it is a deposit action, False if withdrawn.
    @return uint256 Amount of LP tokens deposited or withdrawn.
    """
    view_contract: address = staticcall factory.views_implementation()
    return staticcall Views(view_contract).calc_token_amount(amounts, deposit, self)


@external
@view
def get_dy(i: uint256, j: uint256, dx: uint256) -> uint256:
    """
    @notice Get amount of coin[j] tokens received for swapping in dx amount of coin[i]
    @dev Includes fee.
    @param i index of input token. Check pool.coins(i) to get coin address at ith index
    @param j index of output token
    @param dx amount of input coin[i] tokens
    @return uint256 Exact amount of output j tokens for dx amount of i input tokens.
    """
    view_contract: address = staticcall factory.views_implementation()
    return staticcall Views(view_contract).get_dy(i, j, dx, self)


@external
@view
def get_dx(i: uint256, j: uint256, dy: uint256) -> uint256:
    """
    @notice Get amount of coin[i] tokens to input for swapping out dy amount
            of coin[j]
    @dev This is an approximate method, and returns estimates close to the input
         amount. Expensive to call on-chain.
    @param i index of input token. Check pool.coins(i) to get coin address at
           ith index
    @param j index of output token
    @param dy amount of input coin[j] tokens received
    @return uint256 Approximate amount of input i tokens to get dy amount of j tokens.
    """
    view_contract: address = staticcall factory.views_implementation()
    return staticcall Views(view_contract).get_dx(i, j, dy, self)


@external
@view
@nonreentrant
def lp_price() -> uint256:
    """
    @notice Calculates the current price of the LP token w.r.t coin at the
            0th index
    @return uint256 LP price.
    """
    return 2 * self.virtual_price * isqrt(self.internal_price_oracle() * 10**18) // 10**18


@external
@view
@nonreentrant
def get_virtual_price() -> uint256:
    """
    @notice Calculates the current virtual price of the pool LP token.
    @dev Not to be confused with `self.virtual_price` which is a cached
         virtual price.
    @return uint256 Virtual Price.
    """
    return 10**18 * self._xcp(self.D, self.cached_price_scale) // erc20.totalSupply


@external
@view
@nonreentrant
def price_oracle() -> uint256:
    """
    @notice Returns the oracle price of the coin at index `k` w.r.t the coin
            at index 0.
    @dev The oracle is an exponential moving average, with a periodicity
         determined by `self.ma_time`. The aggregated prices are cached state
         prices (dy/dx) calculated AFTER the latest trade.
    @return uint256 Price oracle value of kth coin.
    """
    return self.internal_price_oracle()


@external
@view
@nonreentrant
def price_scale() -> uint256:
    """
    @notice Returns the price scale of the coin at index `k` w.r.t the coin
            at index 0.
    @dev Price scale determines the price band around which liquidity is
         concentrated.
    @return uint256 Price scale of coin.
    """
    return self.cached_price_scale


@external
@view
def fee() -> uint256:
    """
    @notice Returns the fee charged by the pool at current state.
    @dev Not to be confused with the fee charged at liquidity action, since
         there the fee is calculated on `xp` AFTER liquidity is added or
         removed.
    @return uint256 fee bps.
    """
    return self._fee(self._xp(self.balances, self.cached_price_scale))




@external
@view
def calc_token_fee(
    amounts: uint256[N_COINS], xp: uint256[N_COINS]
) -> uint256:
    """
    @notice Returns the fee charged on the given amounts for add_liquidity.
    @param amounts The amounts of coins being added to the pool.
    @param xp The current balances of the pool multiplied by coin precisions.
    @return uint256 Fee charged.
    """
    return self._calc_token_fee(amounts, xp)


@view
@external
def A() -> uint256:
    """
    @notice Returns the current pool amplification parameter.
    @return uint256 A param.
    """
    return self._A_gamma()[0]


@view
@external
def gamma() -> uint256:
    """
    @notice Returns the current pool gamma parameter.
    @return uint256 gamma param.
    """
    return self._A_gamma()[1]


@view
@external
def mid_fee() -> uint256:
    """
    @notice Returns the current mid fee
    @return uint256 mid_fee value.
    """
    return utils.unpack_3(self.packed_fee_params)[0]


@view
@external
def out_fee() -> uint256:
    """
    @notice Returns the current out fee
    @return uint256 out_fee value.
    """
    return utils.unpack_3(self.packed_fee_params)[1]


@view
@external
def fee_gamma() -> uint256:
    """
    @notice Returns the current fee gamma
    @return uint256 fee_gamma value.
    """
    return utils.unpack_3(self.packed_fee_params)[2]


@view
@external
def allowed_extra_profit() -> uint256:
    """
    @notice Returns the current allowed extra profit
    @return uint256 allowed_extra_profit value.
    """
    return utils.unpack_3(self.packed_rebalancing_params)[0]


@view
@external
def adjustment_step() -> uint256:
    """
    @notice Returns the current adjustment step
    @return uint256 adjustment_step value.
    """
    return utils.unpack_3(self.packed_rebalancing_params)[1]


@view
@external
def ma_time() -> uint256:
    """
    @notice Returns the current moving average time in seconds
    @dev To get time in seconds, the parameter is multipled by ln(2)
         One can expect off-by-one errors here.
    @return uint256 ma_time value.
    """
    return utils.unpack_3(self.packed_rebalancing_params)[2] * 694 // 1000


@view
@external
def precisions() -> uint256[N_COINS]:  # <-------------- For by view contract.
    """
    @notice Returns the precisions of each coin in the pool.
    @return uint256[3] precisions of coins.
    """
    return PRECISIONS


@external
@view
def fee_calc(xp: uint256[N_COINS]) -> uint256:  # <----- For by view contract.
    """
    @notice Returns the fee charged by the pool at current state.
    @param xp The current balances of the pool multiplied by coin precisions.
    @return uint256 Fee value.
    """
    return self._fee(xp)


# ------------------------- AMM Admin Functions ------------------------------


@external
def ramp_A_gamma(
    future_A: uint256, future_gamma: uint256, future_time: uint256
):
    """
    @notice Initialise Ramping A and gamma parameter values linearly.
    @dev Only accessible by factory admin, and only
    @param future_A The future A value.
    @param future_gamma The future gamma value.
    @param future_time The timestamp at which the ramping will end.
    """
    assert msg.sender == staticcall factory.admin(), "only owner"
    assert not self._is_ramping(), "ramp undergoing"
    assert future_time > block.timestamp + MIN_RAMP_TIME - 1, "ramp time<min"

    A_gamma: uint256[2] = self._A_gamma()
    initial_A_gamma: uint256 = A_gamma[0] << 128
    initial_A_gamma = initial_A_gamma | A_gamma[1]

    assert future_A > MIN_A - 1, "A<min"
    assert future_A < MAX_A + 1, "A>max"
    assert future_gamma > MIN_GAMMA - 1, "gamma<min"
    assert future_gamma < MAX_GAMMA + 1, "gamme>max"

    ratio: uint256 = 10**18 * future_A // A_gamma[0]
    assert ratio < 10**18 * MAX_A_CHANGE + 1, "A change too high"
    assert ratio > 10**18 // MAX_A_CHANGE - 1, "A change too low"

    ratio = 10**18 * future_gamma // A_gamma[1]
    assert ratio < 10**18 * MAX_A_CHANGE + 1, "gamma change too high"
    assert ratio > 10**18 // MAX_A_CHANGE - 1, "gamma change too low"

    self.initial_A_gamma = initial_A_gamma
    self.initial_A_gamma_time = block.timestamp

    future_A_gamma: uint256 = future_A << 128
    future_A_gamma = future_A_gamma | future_gamma
    self.future_A_gamma_time = future_time
    self.future_A_gamma = future_A_gamma

    log RampAgamma(
        initial_A=A_gamma[0],
        future_A=future_A,
        initial_gamma=A_gamma[1],
        future_gamma=future_gamma,
        initial_time=block.timestamp,
        future_time=future_time
    )


@external
def stop_ramp_A_gamma():
    """
    @notice Stop Ramping A and gamma parameters immediately.
    @dev Only accessible by factory admin.
    """
    assert msg.sender == staticcall factory.admin(), "only owner"

    A_gamma: uint256[2] = self._A_gamma()
    current_A_gamma: uint256 = A_gamma[0] << 128
    current_A_gamma = current_A_gamma | A_gamma[1]
    self.initial_A_gamma = current_A_gamma
    self.future_A_gamma = current_A_gamma
    self.initial_A_gamma_time = block.timestamp
    self.future_A_gamma_time = block.timestamp

    # ------ Now (block.timestamp < t1) is always False, so we return saved A.

    log StopRampA(current_A=A_gamma[0], current_gamma=A_gamma[1], time=block.timestamp)


@external
@nonreentrant
def apply_new_parameters(
    _new_mid_fee: uint256,
    _new_out_fee: uint256,
    _new_fee_gamma: uint256,
    _new_allowed_extra_profit: uint256,
    _new_adjustment_step: uint256,
    _new_ma_time: uint256,
):
    """
    @notice Commit new parameters.
    @dev Only accessible by factory admin.
    @param _new_mid_fee The new mid fee.
    @param _new_out_fee The new out fee.
    @param _new_fee_gamma The new fee gamma.
    @param _new_allowed_extra_profit The new allowed extra profit.
    @param _new_adjustment_step The new adjustment step.
    @param _new_ma_time The new ma time. ma_time is time_in_seconds/ln(2).
    """
    assert msg.sender == staticcall factory.admin(), "only owner"

    # ----------------------------- Set fee params ---------------------------

    new_mid_fee: uint256 = _new_mid_fee
    new_out_fee: uint256 = _new_out_fee
    new_fee_gamma: uint256 = _new_fee_gamma

    current_fee_params: uint256[3] = utils.unpack_3(self.packed_fee_params)

    if new_out_fee < MAX_FEE + 1:
        assert new_out_fee > MIN_FEE - 1, "fee is out of range"
    else:
        new_out_fee = current_fee_params[1]

    if new_mid_fee > MAX_FEE:
        new_mid_fee = current_fee_params[0]
    assert new_mid_fee <= new_out_fee, "mid-fee is too high"

    if new_fee_gamma < 10**18:
        assert new_fee_gamma > 0, "fee_gamma out of range [1 .. 10**18]"
    else:
        new_fee_gamma = current_fee_params[2]

    self.packed_fee_params = utils.pack_3([new_mid_fee, new_out_fee, new_fee_gamma])

    # ----------------- Set liquidity rebalancing parameters -----------------

    new_allowed_extra_profit: uint256 = _new_allowed_extra_profit
    new_adjustment_step: uint256 = _new_adjustment_step
    new_ma_time: uint256 = _new_ma_time

    current_rebalancing_params: uint256[3] = utils.unpack_3(self.packed_rebalancing_params)

    if new_allowed_extra_profit > 10**18:
        new_allowed_extra_profit = current_rebalancing_params[0]

    if new_adjustment_step > 10**18:
        new_adjustment_step = current_rebalancing_params[1]

    if new_ma_time < 872542:  # <----- Calculated as: 7 * 24 * 60 * 60 / ln(2)
        assert new_ma_time > 86, "MA time should be longer than 60/ln(2)"
    else:
        new_ma_time = current_rebalancing_params[2]

    self.packed_rebalancing_params = utils.pack_3(
        [new_allowed_extra_profit, new_adjustment_step, new_ma_time]
    )

    # ---------------------------------- LOG ---------------------------------

    log NewParameters(
        mid_fee=new_mid_fee,
        out_fee=new_out_fee,
        fee_gamma=new_fee_gamma,
        allowed_extra_profit=new_allowed_extra_profit,
        adjustment_step=new_adjustment_step,
        ma_time=new_ma_time
    )
