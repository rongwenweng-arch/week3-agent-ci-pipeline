from src.data_loader import load_config, get_setting

SAMPLE = """
[app]
name = "NorthStar"
debug = true
"""


def test_load_config():
    cfg = load_config(SAMPLE)
    assert cfg["app"]["name"] == "NorthStar"


def test_get_setting_default():
    cfg = load_config(SAMPLE)
    assert get_setting(cfg, "missing_key", "fallback") == "fallback"
