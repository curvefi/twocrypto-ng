#!/usr/bin/env python3
# flake8: noqa
from decimal import Decimal
from math import exp

A_MULTIPLIER = 10000


def get_y_n2_dec(ANN, gamma, x, D, i):
    """
    Analytical solution to obtain the value of y
    Equivalent to get_y in the math smart contract,
    except that it doesn't fallback to newton_y.
    This function is a draft and should not be used
    as expected value for y in testing.
    """

    if i == 0:
        m = 1
    elif i == 1:
        m = 0

    A = Decimal(ANN) / 10**4 / 4
    gamma = Decimal(gamma) / 10**18
    x = [Decimal(_x) / 10**18 for _x in x]
    D = Decimal(D) / 10**18

    a = Decimal(16) * x[m] ** 3 / D**3
    b = 4 * A * gamma**2 * x[m] - (4 * (3 + 2 * gamma) * x[m] ** 2) / D
    c = D * (3 + 4 * gamma + (1 - 4 * A) * gamma**2) * x[m] + 4 * A * gamma**2 * x[m] ** 2
    d = -(Decimal(1) / 4) * D**3 * (1 + gamma) ** 2

    delta0 = b**2 - 3 * a * c
    delta1 = 2 * b**3 - 9 * a * b * c + 27 * a**2 * d
    sqrt_arg = delta1**2 - 4 * delta0**3

    if sqrt_arg < 0:
        return [0, {}]

    sqrt = sqrt_arg ** (Decimal(1) / 2)
    cbrt_arg = (delta1 + sqrt) / 2
    if cbrt_arg > 0:
        C1 = cbrt_arg ** (Decimal(1) / 3)
    else:
        C1 = -((-cbrt_arg) ** (Decimal(1) / 3))
    root = -(b + C1 + delta0 / C1) / (3 * a)

    return [root, (a, b, c, d)]


def geometric_mean(x):
    N = len(x)
    x = sorted(x, reverse=True)  # Presort - good for convergence
    D = x[0]
    for i in range(255):
        D_prev = D
        tmp = 10**18
        for _x in x:
            tmp = tmp * _x // D
        D = D * ((N - 1) * 10**18 + tmp) // (N * 10**18)
        diff = abs(D - D_prev)
        if diff <= 1 or diff * 10**18 < D:
            return D
    raise ValueError("Did not converge")


def reduction_coefficient(x, gamma):
    N = len(x)
    x_prod = 10**18
    K = 10**18
    S = sum(x)
    for x_i in x:
        x_prod = x_prod * x_i // 10**18
        K = K * N * x_i // S
    if gamma > 0:
        K = gamma * 10**18 // (gamma + 10**18 - K)
    return K


def get_fee(x, fee_gamma, mid_fee, out_fee):
    f = reduction_coefficient(x, fee_gamma)
    return (mid_fee * f + out_fee * (10**18 - f)) // 10**18


def newton_D(A, gamma, x, D0):
    D = D0

    S = sum(x)
    x = sorted(x, reverse=True)
    N = len(x)

    assert N == 2

    for i in range(255):
        D_prev = D

        K0 = 10**18
        for _x in x:
            K0 = K0 * _x * N // D

        _g1k0 = abs(gamma + 10**18 - K0)

        # D / (A * N**N) * _g1k0**2 / gamma**2
        mul1 = 10**18 * D // gamma * _g1k0 // gamma * _g1k0 * A_MULTIPLIER // A

        # 2*N*K0 / _g1k0
        mul2 = (2 * 10**18) * N * K0 // _g1k0

        neg_fprime = (S + S * mul2 // 10**18) + mul1 * N // K0 - mul2 * D // 10**18
        assert neg_fprime > 0  # Python only: -f' > 0

        # D -= f / fprime
        D = (D * neg_fprime + D * S - D**2) // neg_fprime - D * (mul1 // neg_fprime) // 10**18 * (
            10**18 - K0
        ) // K0

        if D < 0:
            D = -D // 2
        if abs(D - D_prev) <= max(100, D // 10**14):
            return D

    raise ValueError("Did not converge")


def newton_y(A, gamma, x, D, i):
    N = len(x)

    assert N == 2

    y = D // N
    K0_i = 10**18
    S_i = 0
    x_sorted = sorted(_x for j, _x in enumerate(x) if j != i)
    convergence_limit = max(max(x_sorted) // 10**14, D // 10**14, 100)
    for _x in x_sorted:
        y = y * D // (_x * N)  # Small _x first
        S_i += _x
    for _x in x_sorted[::-1]:
        K0_i = K0_i * _x * N // D  # Large _x first

    for j in range(255):
        y_prev = y

        K0 = K0_i * y * N // D
        S = S_i + y

        _g1k0 = abs(gamma + 10**18 - K0)

        # D / (A * N**N) * _g1k0**2 / gamma**2
        mul1 = 10**18 * D // gamma * _g1k0 // gamma * _g1k0 * A_MULTIPLIER // A

        # 2*K0 / _g1k0
        mul2 = 10**18 + (2 * 10**18) * K0 // _g1k0

        yfprime = 10**18 * y + S * mul2 + mul1 - D * mul2
        fprime = yfprime // y
        assert fprime > 0  # Python only: f' > 0

        # y -= f / f_prime;  y = (y * fprime - f) / fprime
        y = (yfprime + 10**18 * D - 10**18 * S) // fprime + mul1 // fprime * (10**18 - K0) // K0

        if j > 100:  # Just logging when doesn't converge
            print(j, y, D, x)
        if y < 0 or fprime < 0:
            y = y_prev // 2
        if abs(y - y_prev) <= max(convergence_limit, y // 10**14):
            return y

    raise Exception("Did not converge")


def solve_x(A, gamma, x, D, i):
    """
    Solving for x or y in the AMM equation.

    Even though we have an analytical solution we consider
    the newton method to be a ground truth. The analytical
    solution does not always work.
    """
    return newton_y(A, gamma, x, D, i)


def solve_D(A, gamma, x):
    D0 = len(x) * geometric_mean(x)  # <- fuzz to make sure it's ok XXX
    return newton_D(A, gamma, x, D0)


N_COINS = 2


class Curve:
    def __init__(self, A, gamma, D, p):
        self.A = A
        self.gamma = gamma
        self.p = p
        self.x = [D // N_COINS * 10**18 // self.p[i] for i in range(N_COINS)]

    def xp(self):
        return [x * p // 10**18 for x, p in zip(self.x, self.p)]

    def D(self):
        xp = self.xp()
        if any(x <= 0 for x in xp):
            raise ValueError
        return solve_D(self.A, self.gamma, xp)

    def y(self, x, i, j):
        xp = self.xp()
        xp[i] = x * self.p[i] // 10**18
        yp = solve_x(self.A, self.gamma, xp, self.D(), j)
        return yp * 10**18 // self.p[j]

    def get_p(self):
        A = self.A
        gamma = self.gamma
        xp = self.xp()
        D = self.D()

        K0 = xp[0] * xp[1] * 4 // D * 10**36 // D
        gK0 = (
            2 * K0 * K0 // 10**36 * K0 // 10**36
            + (gamma + 10**18) ** 2
            - (K0 * K0 // 10**36 * (2 * gamma + 3 * 10**18) // 10**18)
        )
        NNAG2 = A * gamma**2 // A_MULTIPLIER
        numerator = xp[0] * (gK0 + NNAG2 * xp[1] // D * K0 // 10**36) // xp[1]
        denominator = gK0 + NNAG2 * xp[0] // D * K0 // 10**36

        return numerator * 10**18 // denominator


class Trader:
    def __init__(
        self,
        A,
        gamma,
        D,
        p0,
        mid_fee=1e-3,
        out_fee=3e-3,
        fee_gamma=None,
        adjustment_step=0.003,
        ma_time=866,
    ):
        self.t = 0
        self.price_oracle = p0[:]
        self.last_price = p0[:]
        self.curve = Curve(A, gamma, D, p=p0[:])
        self.mid_fee = int(mid_fee * 1e10)
        self.out_fee = int(out_fee * 1e10)
        self.xcp_profit = 10**18
        self.xcp_profit_real = 10**18
        self.xcp = self.get_xcp()
        self.adjustment_step = int(10**18 * adjustment_step)
        self.fee_gamma = fee_gamma or gamma  # why can gamma be used as fee_gamma?
        self.ma_time = ma_time

    def fee(self):
        f = reduction_coefficient(self.curve.xp(), self.fee_gamma)
        return (self.mid_fee * f + self.out_fee * (10**18 - f)) // 10**18

    def get_xcp(self):
        # First calculate the ideal balance
        # Then calculate, what the constant-product would be
        D = self.curve.D()
        N = len(self.curve.x)
        X = [D * 10**18 // (N * p) for p in self.curve.p]

        return geometric_mean(X)

    def update_xcp(self, only_real=False):
        xcp = self.get_xcp()
        self.xcp_profit_real = self.xcp_profit_real * xcp // self.xcp
        if not only_real:
            self.xcp_profit = self.xcp_profit * xcp // self.xcp
        self.xcp = xcp

    def buy(self, dx, i, j, max_price=1e100):
        """
        Buy y for x
        """
        try:
            x_old = self.curve.x[:]
            x = self.curve.x[i] + dx
            y = self.curve.y(x, i, j)
            dy = self.curve.x[j] - y
            self.curve.x[i] = x
            self.curve.x[j] = y
            fee = self.fee()
            self.curve.x[j] += dy * fee // 10**10
            dy = dy * (10**10 - fee) // 10**10
            if dx * 10**18 // dy > max_price or dy < 0:
                self.curve.x = x_old
                return False
            self.update_xcp()
            return dy
        except ValueError:
            return False

    def sell(self, dy, i, j, min_price=0):
        """
        Sell y for x
        """
        try:
            x_old = self.curve.x[:]
            y = self.curve.x[j] + dy
            x = self.curve.y(y, j, i)
            dx = self.curve.x[i] - x
            self.curve.x[i] = x
            self.curve.x[j] = y
            fee = self.fee()
            self.curve.x[i] += dx * fee // 10**10
            dx = dx * (10**10 - fee) // 10**10
            if dx * 10**18 // dy < min_price or dx < 0:
                self.curve.x = x_old
                return False
            self.update_xcp()
            return dx
        except ValueError:
            return False

    def _ma_multiplier(self, t):
        return int(10**18 * exp(-1 * (t - self.t) / self.ma_time))

    def ma_recorder(self, t, price_vector):
        # need to convert this to exp!
        # XXX what if every block only has p_b being last
        N = len(price_vector)
        if t > self.t:
            alpha = self._ma_multiplier(t)
            last_price = min(price_vector[1], 2 * self.curve.p[1])
            self.price_oracle[1] = (
                int(last_price * (10**18 - alpha) + self.price_oracle[1] * alpha) // 10**18
            )
            self.t = t

    def tweak_price(self, t):
        self.ma_recorder(t, self.last_price)
        self.last_price[1] = self.curve.get_p() * self.curve.p[1] // 10**18

        # update price_scale:
        norm = int(
            sum(
                (p_real * 10**18 // p_target - 10**18) ** 2
                for p_real, p_target in zip(self.price_oracle, self.curve.p)
            )
            ** 0.5
        )
        adjustment_step = max(self.adjustment_step, norm // 5)
        if norm <= adjustment_step:
            # Already close to the target price
            return norm

        price_scale_adjustment = adjustment_step * (self.price_oracle[1] - self.curve.p[1]) // norm
        p_new = [10**18, self.curve.p[1] + price_scale_adjustment]

        old_p = self.curve.p[:]
        old_profit = self.xcp_profit_real
        old_xcp = self.xcp

        self.curve.p = p_new
        self.update_xcp(only_real=True)

        if 2 * (self.xcp_profit_real - 10**18) <= self.xcp_profit - 10**18:
            # If real profit is less than half of maximum - revert params back
            self.curve.p = old_p
            self.xcp_profit_real = old_profit
            self.xcp = old_xcp

        return norm
