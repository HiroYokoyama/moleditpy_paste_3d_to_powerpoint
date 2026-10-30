import io
import zipfile
from types import SimpleNamespace

import pytest

import paste_3d_to_powerpoint as plugin


class FakeContext:
    def __init__(self, plotter=None):
        self.plotter = plotter
        self.export_actions = []
        self.messages = []

    def add_export_action(self, label, callback):
        self.export_actions.append((label, callback))

    def show_status_message(self, message, timeout=3000):
        self.messages.append(message)

    def get_main_window(self):
        return None


def test_metadata():
    assert plugin.PLUGIN_NAME == "Paste 3D to PowerPoint"
    assert plugin.PLUGIN_VERSION == "0.1.0"
    assert plugin.PLUGIN_SUPPORTED_MOLEDITPY_VERSION == ">=5.0.0, <6.0.0"
    assert isinstance(plugin.PLUGIN_TAGS, list) and plugin.PLUGIN_TAGS
    assert not hasattr(plugin, "run"), "run() would add a duplicate Plugins-menu entry"


def test_initialize_registers_both_export_actions():
    ctx = FakeContext()
    plugin.initialize(ctx)
    assert [label for label, _ in ctx.export_actions] == [
        plugin.COPY_LABEL,
        plugin.EXPORT_LABEL,
    ]
    assert ctx.export_actions[0][1] is plugin.copy_to_powerpoint
    assert ctx.export_actions[1][1] is plugin.export_glb


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

    assert plugin.copy_to_powerpoint() is True
    assert copied["glb"][:4] == b"glTF"
    z = zipfile.ZipFile(io.BytesIO(copied["gvml"]))
    assert z.read("clipboard/media/model3d1.glb") == copied["glb"]
    assert 'fov="600000"' in z.read("clipboard/drawings/drawing1.xml").decode()
    assert "Ctrl+V" in ctx.messages[-1] and "1 object(s)" in ctx.messages[-1]


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
