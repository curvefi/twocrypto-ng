from decimal import Decimal


def get_y_n2_dec(ANN, gamma, x, D, i):

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
    c = (
        D * (3 + 4 * gamma + (1 - 4 * A) * gamma**2) * x[m]
        + 4 * A * gamma**2 * x[m] ** 2
    )
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
