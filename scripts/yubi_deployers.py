"""Load an Ethereum account with a YubiKey touch and the keystore password.

The key lives in ~/.config/eth/<checksum address>.json.age: a standard eth keystore (scrypt, password)
encrypted with age to one or more YubiKeys through age-plugin-yubikey (touch Always, PIN Never).
Nothing is written to disk; the decrypted keystore and the key stay in this process's memory.
scripts/setup_key.py in github.com/heswithme/yubi-deployers creates the file.

    from yubi_deployers import load_account
    acct = load_account("0x...")   # touch the YubiKey, then type the keystore password
    boa.env.add_account(acct); boa.env.eoa = acct.address
"""
import getpass
import json
import subprocess
import sys
import warnings
from pathlib import Path

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils import to_checksum_address

KEY_DIR = Path("~/.config/eth").expanduser()
STUB_PREFIX = "AGE-PLUGIN-YUBIKEY-"


class LoadError(Exception):
    pass


def key_path(address: str) -> Path:
    return KEY_DIR / f"{to_checksum_address(address)}.json.age"


def yubikey_stubs(serial: int | None = None) -> list[str]:
    """age identity stubs on the plugged-in YubiKeys (not secret: each names a serial and a slot)."""
    cmd = ["age-plugin-yubikey", "--identity"] + (["--serial", str(serial)] if serial else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise LoadError(f"age-plugin-yubikey --identity failed: {r.stderr.strip()}")
    return [line.strip() for line in r.stdout.splitlines() if line.strip().startswith(STUB_PREFIX)]


def age_decrypt(path: Path, stubs: list[str]) -> bytes:
    """age -d with only these identities. The YubiKey asks for a touch on the terminal (stderr and /dev/tty);
    stdout is kept in memory and used only if age exits with 0."""
    r = subprocess.run(["age", "-d", "-i", "-", str(path)],
                       input=("\n".join(stubs) + "\n").encode(), stdout=subprocess.PIPE)
    if r.returncode != 0:
        raise LoadError(f"age could not decrypt {path} (exit code {r.returncode})")
    return r.stdout


def read_password(prompt: str = "Keystore password: ") -> str:
    """No-echo prompt; refuses to fall back to a prompt that would show the password."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def decrypt_keystore(keystore: bytes, password: str) -> LocalAccount:
    try:
        keyfile = json.loads(keystore)
    except ValueError:
        keyfile = None
    if not isinstance(keyfile, dict):
        raise LoadError("the decrypted file is not a keystore")
    print("decrypting the keystore (scrypt, a few seconds)...", file=sys.stderr)
    try:
        key = Account.decrypt(keyfile, password)
    except ValueError:
        raise LoadError("wrong keystore password") from None
    return Account.from_key(key)


def load_account(expected_address: str) -> LocalAccount:
    expected = to_checksum_address(expected_address)  # rejects a malformed address before any prompt
    path = key_path(expected)
    if not path.is_file():
        raise LoadError(f"no key file {path}; create it with scripts/setup_key.py"
                        " from github.com/heswithme/yubi-deployers")
    stubs = yubikey_stubs()
    if not stubs:
        raise LoadError("no YubiKey with an age identity is plugged in")
    print(f"touch the YubiKey to unlock {path.name}", file=sys.stderr)
    account = decrypt_keystore(age_decrypt(path, stubs), read_password())
    if account.address != expected:
        raise LoadError(f"{path.name} holds {account.address}, not {expected}")
    return account
