import tomlkit

from slide_capture.config import ConfigManager, Region, Settings, parse_settings


def test_creates_default_file_with_comments(tmp_path):
    path = tmp_path / "config.toml"
    cm = ConfigManager(path)
    text = path.read_text(encoding="utf-8")
    assert "# 監視間隔(秒)" in text
    assert cm.settings.region is None
    assert cm.settings.max_duration_min == 120
    assert cm.settings.sensitivity == "standard"
    assert cm.settings.output_dir  # 既定の保存先が書き込まれている


def test_update_preserves_user_comments(tmp_path):
    path = tmp_path / "config.toml"
    ConfigManager(path)
    text = path.read_text(encoding="utf-8").replace(
        "interval_sec = 1.0", "# ユーザのメモ\ninterval_sec = 0.5"
    )
    path.write_text(text, encoding="utf-8")

    cm = ConfigManager(path)
    cm.set_region(Region(10, 20, 300, 200))
    cm.update("detection", "sensitivity", "high")

    text = path.read_text(encoding="utf-8")
    assert "# ユーザのメモ" in text
    reloaded = ConfigManager(path).settings
    assert reloaded.region == Region(10, 20, 300, 200)
    assert reloaded.sensitivity == "high"
    assert reloaded.interval_sec == 0.5
    assert reloaded.change_threshold == reloaded.threshold_high


def test_invalid_values_fall_back_to_defaults():
    doc = tomlkit.parse(
        """
[capture]
interval_sec = -1
region = { left = 0, top = 0, width = 0, height = 10 }
[detection]
sensitivity = "ultra"
skip_duplicates = "yes"
[session]
max_duration_min = 90
"""
    )
    s, warnings = parse_settings(doc)
    d = Settings()
    assert s.interval_sec == d.interval_sec
    assert s.sensitivity == d.sensitivity
    assert s.skip_duplicates is True
    assert s.region is None
    assert s.max_duration_min == 90
    assert len(warnings) == 4


def test_reload_detects_external_edit_and_notifies(tmp_path):
    path = tmp_path / "config.toml"
    cm = ConfigManager(path)
    seen = []
    cm.add_listener(lambda old, new: seen.append((old.max_duration_min, new.max_duration_min)))

    assert cm.reload() is False  # 変更なし
    text = path.read_text(encoding="utf-8").replace(
        "max_duration_min = 120", "max_duration_min = 45"
    )
    path.write_text(text, encoding="utf-8")
    assert cm.reload() is True
    assert cm.settings.max_duration_min == 45
    assert seen == [(120, 45)]


def test_reload_with_syntax_error_keeps_previous_settings(tmp_path):
    import pytest

    from slide_capture.config import ConfigError

    path = tmp_path / "config.toml"
    cm = ConfigManager(path)
    path.write_text("[capture\ninterval_sec = ", encoding="utf-8")
    with pytest.raises(ConfigError):
        cm.reload()
    assert cm.settings.interval_sec == 1.0
