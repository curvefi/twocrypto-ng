# Math contract tests

```
math
├── conftest.py - "Fixtures for new and old math contracts."
├── test_cbrt.py
├── test_exp.py
├── test_get_p.py
├── test_get_y.py
├── test_log2.py
├── test_newton_D.py
├── test_newton_D_ref.py
├── test_newton_y.py - "Verify that newton_y always convergees to the correct values quickly enough"
└── test_packing.py - "Testing unpacking for (2, 3)-tuples"
```

### Fuzzing parallelization
Due to the nature of the math involved in curve pools (i.e. analytical solutions for equations not always availble), we often require approximation methods to solve these equations numerically. Testing this requires extensive fuzzing which can be very time consuming sometimes. Hypothesis does not support test parallelisation and this is why in the code we use test parametrisation as a hacky way to obtain parallel fuzzing with `xdist`:

```python
@pytest.mark.parametrize(
    "_tmp", range(N_CASES)
)  # Parallelisation hack (more details in folder's README)
```

### Useful info
- We have proven that in (0, x + y) newton_D either converges or reverts. Converging to a wrong value is not possible since there's only one root in (0, x + y).

### Checklist when modifying functions using on Newton's method
- Make sure that the function still converges in all instances where it used to before.
- The number of iterations required to converge should not increase significantly.
