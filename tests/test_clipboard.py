import pytest

pytest.importorskip("PySide6")

from paste_3d_to_powerpoint import clipboard  # noqa: E402


def test_mime_data_uses_native_windows_format_names(qapp):
    from PySide6.QtGui import QImage

    image = QImage(4, 4, QImage.Format.Format_RGB888)
    mime = clipboard.build_mime_data(b"GVML", b"glTF-bytes", image)
    formats = mime.formats()
    assert 'application/x-qt-windows-mime;value="Art::GVML ClipFormat"' in formats
    assert 'application/x-qt-windows-mime;value="model/gltf-binary"' in formats
    assert bytes(mime.data(clipboard.windows_mime(clipboard.GVML_FORMAT))) == b"GVML"
    assert bytes(mime.data(clipboard.GLTF_FORMAT)) == b"glTF-bytes"
    assert mime.hasImage()


def test_mime_data_without_preview_image(qapp):
    assert not clipboard.build_mime_data(b"g", b"b").hasImage()


def test_screenshot_failure_returns_none():
    class Broken:
        def screenshot(self, *args, **kwargs):
            raise RuntimeError("no render window")

    assert clipboard.screenshot_image(Broken()) is None
