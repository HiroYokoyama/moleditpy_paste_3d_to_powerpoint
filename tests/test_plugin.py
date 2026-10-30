import io
import zipfile
from types import SimpleNamespace

import pytest

import paste_3d_to_powerpoint as plugin


class FakeContext:
    def __init__(self, plotter=None):
        self.plotter = plotter
        self.export_actions = []
        self.menu_actions = []
        self.messages = []

    def add_export_action(self, label, callback):
        self.export_actions.append((label, callback))

    def add_menu_action(self, path, callback):
        self.menu_actions.append((path, callback))

    def show_status_message(self, message, timeout=3000):
        self.messages.append(message)

    def get_main_window(self):
        return None


def test_metadata():
    assert plugin.PLUGIN_NAME == "Paste 3D to PowerPoint"
    assert plugin.PLUGIN_VERSION == "0.1.1"
    assert plugin.PLUGIN_SUPPORTED_MOLEDITPY_VERSION == ">=5.0.0, <6.0.0"
    assert isinstance(plugin.PLUGIN_TAGS, list) and plugin.PLUGIN_TAGS
    assert not hasattr(plugin, "run"), "run() would add a duplicate Plugins-menu entry"


def test_initialize_registers_the_export_actions():
    ctx = FakeContext()
    plugin.initialize(ctx)
    assert [label for label, _ in ctx.export_actions] == [
        plugin.COPY_LABEL,
        plugin.EXPORT_LABEL,
    ]
    assert ctx.export_actions[0][1] is plugin.copy_to_powerpoint
    assert ctx.export_actions[1][1] is plugin.export_glb
    # Settings live in the menu bar's Settings menu, not in the Export button.
    assert ctx.menu_actions == [
        ("Settings/Paste 3D to PowerPoint...", plugin.open_settings)
    ]


def test_copy_without_3d_view_warns(monkeypatch):
    warnings = []
    monkeypatch.setattr(plugin, "_warn", lambda title, msg: warnings.append(msg))
    plugin.initialize(FakeContext(plotter=None))
    assert plugin.copy_to_powerpoint() is False
    assert warnings and "not available" in warnings[0]


def _fake_scene():
    np = pytest.importorskip("numpy")
    from paste_3d_to_powerpoint.gltf_writer import Primitive
    from paste_3d_to_powerpoint.scene_capture import CapturedScene

    prim = Primitive(
        "tri",
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float),
        np.array([[0, 0, 1]] * 3, float),
        np.array([[0, 1, 2]]),
    )
    return CapturedScene(primitives=[prim], fov_deg=10.0, skipped=["label"])


def test_copy_puts_gvml_and_glb_on_the_clipboard(monkeypatch):
    from paste_3d_to_powerpoint import clipboard, scene_capture

    ctx = FakeContext(plotter=object())
    plugin.initialize(ctx)
    scene = _fake_scene()
    monkeypatch.setattr(
        scene_capture, "capture_scene", lambda plotter, parallel_fov_deg: scene
    )
    copied = {}
    monkeypatch.setattr(
        clipboard,
        "copy_to_clipboard",
        lambda gvml, glb, image: copied.update(gvml=gvml, glb=glb),
    )
    monkeypatch.setattr(clipboard, "screenshot_image", lambda plotter: None)
    monkeypatch.setattr(plugin.sys, "platform", "win32")

    assert plugin.copy_to_powerpoint() is True
    assert copied["glb"][:4] == b"glTF"
    z = zipfile.ZipFile(io.BytesIO(copied["gvml"]))
    assert z.read("clipboard/media/model3d1.glb") == copied["glb"]
    assert 'fov="600000"' in z.read("clipboard/drawings/drawing1.xml").decode()
    assert "Ctrl+V" in ctx.messages[-1] and "1 object(s)" in ctx.messages[-1]


def test_copy_uses_saved_lighting_size_and_line_color(monkeypatch, isolated_settings):
    from paste_3d_to_powerpoint import clipboard, scene_capture, settings

    settings.save_settings(
        {
            "light_preset": "key",
            "brightness": 0.5,
            "paste_size_pt": 144,
            "override_line_color": True,
            "line_color": "#ff0000",
            "parallel_fov_deg": 7,
        }
    )
    plugin.initialize(FakeContext(plotter=object()))
    scene = _fake_scene()
    scene.primitives[0].extras["line"] = True
    seen = {}

    def fake_capture(plotter, parallel_fov_deg):
        seen["fov"] = parallel_fov_deg
        return scene

    monkeypatch.setattr(scene_capture, "capture_scene", fake_capture)
    copied = {}
    monkeypatch.setattr(
        clipboard,
        "copy_to_clipboard",
        lambda gvml, glb, image: copied.update(gvml=gvml),
    )
    monkeypatch.setattr(clipboard, "screenshot_image", lambda plotter: None)

    assert plugin.copy_to_powerpoint() is True
    assert seen["fov"] == 7.0
    assert tuple(scene.primitives[0].color[:3]) == (1.0, 0.0, 0.0)
    drawing = zipfile.ZipFile(io.BytesIO(copied["gvml"])).read(
        "clipboard/drawings/drawing1.xml"
    )
    assert drawing.count(b"<am3d:ptLight") == 1  # single key light
    assert b'<am3d:intensity n="4000000"' in drawing  # 8.0 x 0.5
    assert b'cx="1828800"' in drawing  # 144 pt


def test_settings_window_is_a_singleton(monkeypatch, qapp):
    ctx = FakeContext()
    windows = {}
    ctx.get_window = windows.get
    ctx.register_window = windows.__setitem__
    plugin.initialize(ctx)
    plugin.open_settings()
    first = windows[plugin.WINDOW_ID]
    plugin.open_settings()
    assert windows[plugin.WINDOW_ID] is first
    first.close()


def test_export_writes_glb(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets

    from paste_3d_to_powerpoint import scene_capture

    ctx = FakeContext(plotter=object())
    plugin.initialize(ctx)
    monkeypatch.setattr(
        scene_capture, "capture_scene", lambda plotter, parallel_fov_deg: _fake_scene()
    )
    target = tmp_path / "out"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "")),
    )
    assert plugin.export_glb() is True
    assert (tmp_path / "out.glb").read_bytes()[:4] == b"glTF"


def test_export_cancelled_does_nothing(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets

    plugin.initialize(FakeContext(plotter=object()))
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", ""))
    )
    assert plugin.export_glb() is False


def test_default_path_follows_the_open_file(monkeypatch):
    ctx = FakeContext()
    mw = SimpleNamespace(
        init_manager=SimpleNamespace(current_file_path="C:/work/benzene.pmeprj")
    )
    ctx.get_main_window = lambda: mw
    plugin.initialize(ctx)
    assert plugin._default_glb_path().replace("\\", "/") == "C:/work/benzene.glb"


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_copy_off_windows_does_not_promise_a_powerpoint_paste(monkeypatch, platform):
    """Only the Windows clipboard carries the Office format; elsewhere point to .glb."""
    from paste_3d_to_powerpoint import clipboard, scene_capture

    ctx = FakeContext(plotter=object())
    plugin.initialize(ctx)
    monkeypatch.setattr(
        scene_capture, "capture_scene", lambda plotter, parallel_fov_deg: _fake_scene()
    )
    monkeypatch.setattr(clipboard, "copy_to_clipboard", lambda gvml, glb, image: None)
    monkeypatch.setattr(clipboard, "screenshot_image", lambda plotter: None)
    monkeypatch.setattr(plugin.sys, "platform", platform)

    assert plugin.copy_to_powerpoint() is True
    assert "Ctrl+V" not in ctx.messages[-1]
    assert "needs Windows" in ctx.messages[-1] and "glTF (.glb)" in ctx.messages[-1]
