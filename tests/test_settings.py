import json
import re

import pytest

from paste_3d_to_powerpoint import gvml, settings
from paste_3d_to_powerpoint.gltf_writer import Primitive


def test_missing_or_broken_file_gives_defaults(isolated_settings):
    assert settings.load_settings() == settings.default_settings()
    isolated_settings.write_text("{not json", encoding="utf-8")
    assert settings.load_settings() == settings.default_settings()


def test_round_trip_and_clamping(isolated_settings):
    settings.save_settings(
        {
            "light_preset": "powerpoint",
            "brightness": 99,
            "parallel_fov_deg": 0,
            "override_line_color": True,
            "line_color": "#ABCDEF",
            "paste_size_pt": "200",
        }
    )
    loaded = settings.load_settings()
    assert loaded["light_preset"] == "powerpoint"
    assert loaded["brightness"] == settings.LIMITS["brightness"][1]
    assert loaded["parallel_fov_deg"] == settings.LIMITS["parallel_fov_deg"][0]
    assert loaded["line_color"] == "#abcdef" and loaded["override_line_color"] is True
    assert loaded["paste_size_pt"] == 200.0
    assert json.loads(isolated_settings.read_text(encoding="utf-8")) == loaded


def test_invalid_values_fall_back_to_defaults():
    got = settings.sanitize(
        {
            "light_preset": "disco",
            "line_color": "red",
            "override_line_color": "yes",
            "brightness": "x",
        }
    )
    assert got == settings.default_settings()


def test_line_color_override_only_touches_line_tubes():
    np = pytest.importorskip("numpy")
    tri = (np.zeros((3, 3)), np.zeros((3, 3)), np.array([[0, 1, 2]]))
    line = Primitive("cell", *tri, color=(1, 1, 1, 0.5), extras={"line": True})
    line.vertex_colors = np.full((3, 4), 255, np.uint8)
    atom = Primitive("atom", *tri, color=(0, 1, 0, 1))
    settings.apply_line_color([line, atom], {"override_line_color": False})
    assert line.color == (1, 1, 1, 0.5)
    settings.apply_line_color(
        [line, atom], {"override_line_color": True, "line_color": "#000080"}
    )
    assert line.color == pytest.approx((0, 0, 128 / 255, 0.5))
    assert line.vertex_colors is None
    assert atom.color == (0, 1, 0, 1)


@pytest.mark.parametrize("preset", list(gvml.LIGHT_PRESETS))
def test_light_rig_scales_every_light(preset):
    rig = gvml.LIGHT_PRESETS[preset]
    full = gvml.light_rig_xml(preset, 1.0)
    half = gvml.light_rig_xml(preset, 0.5)
    assert full.count("<am3d:ptLight") == len(rig["points"])
    nums = lambda xml: [
        int(n) for n in re.findall(r'(?:intensity|illuminance) n="(\d+)"', xml)
    ]  # noqa: E731
    assert [round(h * 2) for h in nums(half)] == pytest.approx(nums(full), abs=2)


def test_powerpoint_preset_reproduces_powerpoints_own_rig():
    xml = gvml.light_rig_xml("powerpoint", 1.0)
    for fragment in (
        '<am3d:illuminance n="500000" d="1000000"/>',
        '<am3d:intensity n="9765625" d="1000000"/>',
        'x="21960000" y="70920000" z="16344000"',
    ):
        assert fragment in xml


def test_unknown_preset_uses_default():
    assert gvml.light_rig_xml("nope") == gvml.light_rig_xml(gvml.DEFAULT_LIGHT_PRESET)


def test_dialog_edits_and_saves(qapp, isolated_settings):
    pytest.importorskip("PySide6")
    from paste_3d_to_powerpoint.settings_dialog import SettingsDialog

    current = settings.default_settings()
    saved, copies = [], []
    dlg = SettingsDialog(
        None,
        current,
        on_change=lambda s: saved.append(dict(s)),
        on_copy=lambda: copies.append(1),
    )
    dlg.preset_combo.setCurrentIndex(dlg.preset_combo.findData("key"))
    dlg.brightness_slider.setValue(60)
    dlg.fov_spin.setValue(20)
    dlg.line_check.setChecked(True)
    assert current["light_preset"] == "key" and current["brightness"] == 0.6
    assert current["parallel_fov_deg"] == 20 and current["override_line_color"] is True
    assert saved[-1] == current
    assert dlg.brightness_label.text() == "60 %"
    dlg.copy_button.click()
    assert copies == [1]
    dlg.reset_to_defaults()
    assert current == settings.default_settings()
    dlg.close()


def test_dialog_shows_loaded_settings_without_saving(qapp):
    pytest.importorskip("PySide6")
    from paste_3d_to_powerpoint.settings_dialog import SettingsDialog

    values = settings.sanitize(
        {"light_preset": "powerpoint", "brightness": 1.5, "line_color": "#123456"}
    )
    saved = []
    dlg = SettingsDialog(
        None, dict(values), on_change=saved.append, on_copy=lambda: None
    )
    assert saved == []
    assert dlg.collect() == values
    dlg.close()
