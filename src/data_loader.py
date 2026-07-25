"""Loads a small TOML config blob.

NOTE: this module intentionally imports a package ('toml') that is NOT
listed in requirements.txt, to exercise the missing-dependency
remediation agent (see scripts/remediation_agent.py)."""
import toml


def load_config(toml_text: str) -> dict:
    return toml.loads(toml_text)


def get_setting(config: dict, key: str, default=None):
    return config.get(key, default)
