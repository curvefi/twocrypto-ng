from pathlib import Path

import boa

from tests.utils.constants import VENOM_FLAG


ROOT = Path(__file__).resolve().parents[2]
TWOCRYPTO_SOURCE = ROOT / "contracts" / "main" / "Twocrypto.vy"


def load_twocrypto_with_embedded_periphery(views_address, math_address):
    twocrypto_code = TWOCRYPTO_SOURCE.read_text()
    twocrypto_code = twocrypto_code.replace(
        "MATH = Math(empty(address))",
        f"MATH = Math({math_address})",
        1,
    )
    twocrypto_code = twocrypto_code.replace(
        "VIEW = Views(empty(address))",
        f"VIEW = Views({views_address})",
        1,
    )

    assert f"MATH = Math({math_address})" in twocrypto_code
    assert f"VIEW = Views({views_address})" in twocrypto_code

    return boa.loads_partial(
        twocrypto_code,
        compiler_args={"experimental_codegen": VENOM_FLAG},
    )
