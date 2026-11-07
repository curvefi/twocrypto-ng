import boa.interpret
from vvm import get_installed_vyper_versions

pytest_plugins = [
    "tests.fixtures.accounts",
    "tests.fixtures.tokens",
    "tests.fixtures.functions",
    "tests.fixtures.pool",
    "tests.fixtures.factory",
]

# The legacy factory and gauge stay on Vyper 0.3.10, so boa compiles them through vvm.
# vvm always queries the GitHub API for installable versions, which gets rate limited
# under parallel workers; prefer an installed compiler that satisfies the pragma.
_pick_vyper_version_online = boa.interpret._pick_vyper_version


def _pick_installed_vyper_version(specifier_set, *args, **kwargs):
    installed = [v for v in get_installed_vyper_versions() if specifier_set.contains(v)]
    if installed:
        return max(installed)
    return _pick_vyper_version_online(specifier_set, *args, **kwargs)


boa.interpret._pick_vyper_version = _pick_installed_vyper_version
