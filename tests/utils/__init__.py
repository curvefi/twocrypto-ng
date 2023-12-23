import math


def approx(x1, x2, precision):
    return abs(math.log(x1 / x2)) <= precision
