# Math contract tests

### Fuzzing parallelization
Due to the nature of the math involved in curve pools (i.e. analytical solutions for equations not always availble), we often require approximation methods to solve these equations numerically. Testing this requires extensive fuzzing which can be very time consuming sometimes. Hypothesis does not support test parallelisation and this is why in the code we use test parametrisation as a hacky way to obtain parallel fuzzing with `xdist`:

```python
@pytest.mark.parametrize(
    "_tmp", range(N_CASES)
)  # Parallelisation hack (more details in folder's README)
```

### Useful info
- We have proven (mathemtaically) that in `(0, x + y)` newton_D either converges or reverts. Converging to a wrong value is not possible since there's only one root in `(0, x + y)`. (should add link to proof once available, ask george if this still isn't available).

### Checklist when modifying functions using on Newton's method
- Make sure that the function still converges in all instances where it used to before.
- The number of iterations required to converge should not increase significantly.
