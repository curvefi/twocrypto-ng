"""
Constants often used for testing.

These cannot be used as fixtures because they are often
used as bounds for fuzzing (outside of the test functions).
"""
# TODO use values from actual contracts once this:
# https://github.com/vyperlang/titanoboa/issues/196
# is implmented.

MIN_GAMMA = 10**10
MAX_GAMMA_SMALL = 2 * 10**16
MAX_GAMMA = 199 * 10**15  # 1.99 * 10**17
