# Reference contracts

Byte-identical copies of production sources, used only by tests. Do not edit.

| File | Source | Used by |
|---|---|---|
| `CurveCryptoMathOptimized2.vy` | twocrypto-ng commit 7b4fd90, `contracts/main/CurveCryptoMathOptimized2.vy` (cryptoswap math v2.2.0) | `tests/unitary/twocrypto_math/test_parity_v2_2_0.py`: `TwocryptoMath.vy` must reproduce it exactly |
| `CurveTwocryptoFactory.vy` | twocrypto-ng commit 7b4fd90, `contracts/main/CurveTwocryptoFactory.vy` (legacy factory, Vyper 0.3.10, the source of the deployed factories) | `tests/unitary/factory/test_legacy_factory.py`: the pool deploys and works through the legacy factory |

Check a copy with:

```
git -C <twocrypto-ng checkout> show 7b4fd90:contracts/main/CurveCryptoMathOptimized2.vy | cmp - tests/reference/CurveCryptoMathOptimized2.vy
```
