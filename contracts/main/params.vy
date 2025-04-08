# pragma version 0.4.1

from interfaces import ITwocrypto
from interfaces import ITwocryptoFactory
from interfaces import ITwocryptoView

import packing_utils as utils
import constants as c

factory: public(immutable(ITwocryptoFactory))
packed_rebalancing_params: public(uint256)
packed_fee_params: public(uint256)
initial_A_gamma: public(uint256)
initial_A_gamma_time: public(uint256)
future_A_gamma: public(uint256)
future_A_gamma_time: public(uint256)

@deploy
def __init__(_factory: address, packed_gamma_A: uint256, packed_fee_params: uint256, packed_rebalancing_params: uint256):
    """
    @notice Constructor for the Twocrypto contract.
    @param _factory The address of the factory contract.
    """
    factory = ITwocryptoFactory(_factory)

    self.packed_rebalancing_params = packed_rebalancing_params
    self.packed_fee_params = packed_fee_params

    gamma_A: uint256[2] = utils.unpack_2(packed_gamma_A)

    assert gamma_A[0] > c.MIN_GAMMA-1, "gamma<MIN"
    assert gamma_A[0] < c.MAX_GAMMA+1, "gamma>MAX"

    assert gamma_A[1] > c.MIN_A-1, "A<MIN"
    assert gamma_A[1] < c.MAX_A+1, "A>MAX"

    self.initial_A_gamma = packed_gamma_A
    self.future_A_gamma = packed_gamma_A


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
    assert msg.sender == self._admin(), "only owner"
    assert not self._is_ramping(), "ramp undergoing"
    assert future_time > block.timestamp + c.MIN_RAMP_TIME - 1, "ramp time<min"

    A_gamma: uint256[2] = self._A_gamma() # [A, gamma]

    # TODO refactor checks so that they can be shared across functions
    assert future_A > c.MIN_A - 1, "A<min"
    assert future_A < c.MAX_A + 1, "A>max"
    assert future_gamma > c.MIN_GAMMA - 1, "gamma<min"
    assert future_gamma < c.MAX_GAMMA + 1, "gamma>max"

    ratio: uint256 = 10**18 * future_A // A_gamma[0] # A
    assert ratio < 10**18 * c.MAX_A_CHANGE + 1, "A change too high"
    assert ratio > 10**18 // c.MAX_A_CHANGE - 1, "A change too low"

    ratio = 10**18 * future_gamma // A_gamma[1] # gamma
    assert ratio < 10**18 * c.MAX_GAMMA_CHANGE + 1, "gamma change too high"
    assert ratio > 10**18 // c.MAX_GAMMA_CHANGE - 1, "gamma change too low"

    self.initial_A_gamma = utils.pack_2(A_gamma[1], A_gamma[0]) # [gamma, A]
    self.initial_A_gamma_time = block.timestamp

    self.future_A_gamma = utils.pack_2(future_gamma, future_A) # [gamma, A]
    self.future_A_gamma_time = future_time

    log ITwocrypto.RampAgamma(
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
    @dev Only accessible by admin.
    """
    assert msg.sender == self._admin(), "only owner"

    A_gamma: uint256[2] = self._A_gamma()
    packed_gamma_A: uint256 = utils.pack_2(A_gamma[1], A_gamma[0]) # [gamma, A]
    self.initial_A_gamma = packed_gamma_A
    self.future_A_gamma = packed_gamma_A
    self.initial_A_gamma_time = block.timestamp
    self.future_A_gamma_time = block.timestamp

    # ------ Now (block.timestamp < t1) is always False, so we return saved A.

    log ITwocrypto.StopRampA(current_A=A_gamma[0], current_gamma=A_gamma[1], time=block.timestamp)


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
    assert msg.sender == self._admin(), "only owner"

    # ----------------------------- Set fee params ---------------------------

    new_mid_fee: uint256 = _new_mid_fee
    new_out_fee: uint256 = _new_out_fee
    new_fee_gamma: uint256 = _new_fee_gamma

    current_fee_params: uint256[3] = utils.unpack_3(self.packed_fee_params)

    if new_out_fee < c.MAX_FEE + 1:
        assert new_out_fee > c.MIN_FEE - 1, "fee is out of range"
    else:
        new_out_fee = current_fee_params[1]

    if new_mid_fee > c.MAX_FEE:
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

    log ITwocrypto.NewParameters(
        mid_fee=new_mid_fee,
        out_fee=new_out_fee,
        fee_gamma=new_fee_gamma,
        allowed_extra_profit=new_allowed_extra_profit,
        adjustment_step=new_adjustment_step,
        ma_time=new_ma_time
    )





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
def _views_implementation() -> ITwocryptoView:
    return ITwocryptoView(staticcall factory.views_implementation())


@view
@internal
def _admin() -> address:
    return staticcall factory.admin()


@external
@view
def admin() -> address:
    """
    @notice Returns the address of the pool's admin.
    @return address Admin.
    """
    return self._admin()

@view
@internal
def _fee_receiver() -> address:
    return staticcall factory.fee_receiver()


@external
@view
def fee_receiver() -> address:
    """
    @notice Returns the address of the admin fee receiver.
    @return address Fee receiver.
    """
    return self._fee_receiver()


@view
@internal
def _A_gamma() -> uint256[2]:
    t1: uint256 = self.future_A_gamma_time

    gamma_A1: uint256[2] = utils.unpack_2(self.future_A_gamma)
    gamma1: uint256 = gamma_A1[0]
    A1: uint256 = gamma_A1[1]

    if block.timestamp < t1:

        # --------------- Handle ramping up and down of A --------------------

        gamma_A0: uint256[2] = utils.unpack_2(self.initial_A_gamma) # [gamma, A]
        gamma0: uint256 = gamma_A0[0]
        A0: uint256 = gamma_A0[1]

        t0: uint256 = self.initial_A_gamma_time

        t1 -= t0
        t0 = block.timestamp - t0
        t2: uint256 = t1 - t0

        A1 = (A0 * t2 + A1 * t0) // t1
        gamma1 = (gamma0 * t2 + gamma1 * t0) // t1

    return [A1, gamma1]


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
@internal
def _ma_time() -> uint256:
    # TODO document the conversion here
    return utils.unpack_3(self.packed_rebalancing_params)[2] * 694 // 1000


@view
@external
def ma_time() -> uint256:
    """
    @notice Returns the current moving average time in seconds
    @dev To get time in seconds, the parameter is multiplied by ln(2)
         One can expect off-by-one errors here.
    @return uint256 ma_time value.
    """
    return self._ma_time()
