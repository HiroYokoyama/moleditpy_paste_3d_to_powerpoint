"""Put a captured 3D scene on the system clipboard, ready for Ctrl+V in PowerPoint.

Three representations go up together, so the paste target picks the richest
one it understands:

* ``Art::GVML ClipFormat`` - the Office drawing format; PowerPoint pastes it as
  a native 3D model with the camera (field of view) set by this plugin;
* ``model/gltf-binary`` - the bare .glb, which Office also accepts as a 3D
  model (default camera);
* a bitmap of the current view, for applications without 3D support.

Native Windows clipboard formats are reached through Qt's
``application/x-qt-windows-mime;value="..."`` MIME names, so no PowerPoint
automation and no pywin32 are involved.
"""

from typing import Any, Optional

GVML_FORMAT = "Art::GVML ClipFormat"
GLTF_FORMAT = "model/gltf-binary"


def windows_mime(native_name: str) -> str:
    return f'application/x-qt-windows-mime;value="{native_name}"'


def build_mime_data(gvml: bytes, glb: bytes, image: Optional[Any] = None) -> Any:
    """QMimeData carrying the GVML payload, the GLB and an optional QImage."""
    from PySide6.QtCore import QByteArray, QMimeData

    mime = QMimeData()
    mime.setData(windows_mime(GVML_FORMAT), QByteArray(gvml))
    mime.setData(windows_mime(GLTF_FORMAT), QByteArray(glb))
    # Other platforms ignore the Windows-only names; keep the model reachable.
    mime.setData(GLTF_FORMAT, QByteArray(glb))
    if image is not None:
        mime.setImageData(image)
    return mime


def screenshot_image(plotter: Any) -> Optional[Any]:
    """The current 3D view as a QImage, or None if it cannot be grabbed."""
    try:
        import numpy as np
        from PySide6.QtGui import QImage

        arr = plotter.screenshot(None, return_img=True)
        arr = np.ascontiguousarray(arr[:, :, :3], dtype=np.uint8)
        h, w, _ = arr.shape
        return QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    except Exception:  # a missing preview must not block the 3D copy
        return None


def copy_to_clipboard(gvml: bytes, glb: bytes, image: Optional[Any] = None) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.clipboard().setMimeData(build_mime_data(gvml, glb, image))
