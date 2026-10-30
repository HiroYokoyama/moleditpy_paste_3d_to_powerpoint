"""Paste 3D to PowerPoint - copy the MoleditPy 3D view as a native PowerPoint 3D model.

Export > "Copy 3D to PowerPoint" puts whatever the 3D view shows - molecules,
CIF Viewer crystals, cube-file orbitals, other plugin overlays - on the
clipboard in its current orientation, colors, gloss and transparency.  Paste
it into PowerPoint with Ctrl+V and it arrives as a rotatable 3D model (add the
Turntable animation for a spinning structure).  Export > "Export 3D Scene as
glTF (.glb)..." writes the same model to a file.

Source code, README, and full license (GNU GPL):
    https://github.com/HiroYokoyama/moleditpy_paste_3d_to_powerpoint
Copyright (c) HiroYokoyama. Licensed under the GNU Lesser General Public License;
see the LICENSE file in the repository above for the full terms.
"""

import logging
import os

logger = logging.getLogger(__name__)

PLUGIN_NAME = "Paste 3D to PowerPoint"
PLUGIN_VERSION = "0.1.0"
PLUGIN_AUTHOR = "HiroYokoyama"
PLUGIN_DESCRIPTION = (
    "Copy the 3D view (molecules, crystals, orbitals) to the clipboard as a native "
    "PowerPoint 3D model, or export it as glTF (.glb), keeping the on-screen style."
)
PLUGIN_CATEGORY = "Export"
PLUGIN_TAGS = ["File", "Visualization"]
PLUGIN_DEPENDENCIES = ["numpy", "PySide6-Essentials", "pyvista"]
PLUGIN_OPTIONAL_DEPENDENCIES = []
PLUGIN_SUPPORTED_MOLEDITPY_VERSION = ">=5.0.0, <6.0.0"
PLUGIN_SUPPORTED_PYTHON_VERSION = ">=3.9, <3.15"

COPY_LABEL = "Copy 3D to PowerPoint"
EXPORT_LABEL = "Export 3D Scene as glTF (.glb)..."
SETTINGS_MENU_PATH = "Settings/Paste 3D to PowerPoint..."
WINDOW_ID = "paste_3d_to_powerpoint_settings"

_context = None
current_settings = {}


def _settings() -> dict:
    if not current_settings:
        from .settings import load_settings

        current_settings.update(load_settings())
    return current_settings


def _status(message: str) -> None:
    if _context is not None:
        try:
            _context.show_status_message(message, 6000)
            return
        except Exception:  # pragma: no cover - host API guard
            logger.exception("%s: status bar unavailable", PLUGIN_NAME)
    logger.info("%s: %s", PLUGIN_NAME, message)


def _warn(title: str, message: str) -> None:
    from PySide6.QtWidgets import QMessageBox

    parent = _context.get_main_window() if _context is not None else None
    QMessageBox.warning(parent, title, message)


def _capture():
    """Capture the 3D view, or warn and return None."""
    from .scene_capture import capture_scene

    plotter = _context.plotter if _context is not None else None
    if plotter is None:
        _warn(PLUGIN_NAME, "The 3D view is not available.")
        return None, None
    try:
        from .settings import apply_line_color

        settings = _settings()
        scene = capture_scene(plotter, parallel_fov_deg=settings["parallel_fov_deg"])
        apply_line_color(scene.primitives, settings)
        return scene, plotter
    except ValueError as exc:
        _warn(PLUGIN_NAME, f"{exc}\nShow a structure in the 3D view first.")
    except Exception as exc:
        logger.exception("%s: capture failed", PLUGIN_NAME)
        _warn(PLUGIN_NAME, f"Could not capture the 3D view:\n{exc}")
    return None, None


def _skipped_note(scene) -> str:
    n = len(scene.skipped)
    return f" ({n} object(s) without a mesh were left out)" if n else ""


def copy_to_powerpoint(*_args) -> bool:
    """Export-menu action: put the 3D view on the clipboard."""
    from .clipboard import copy_to_clipboard, screenshot_image
    from .gltf_writer import bounds, build_glb
    from .gvml import build_gvml

    scene, plotter = _capture()
    if scene is None:
        return False
    try:
        glb = build_glb(
            scene.primitives, generator=f"MoleditPy {PLUGIN_NAME} {PLUGIN_VERSION}"
        )
        lo, hi = bounds(scene.primitives)
        settings = _settings()
        gvml = build_gvml(
            glb,
            hi - lo,
            (lo + hi) / 2,
            fov_deg=scene.fov_deg,
            size_pt=settings["paste_size_pt"],
            light_preset=settings["light_preset"],
            brightness=settings["brightness"],
        )
        copy_to_clipboard(gvml, glb, screenshot_image(plotter))
    except Exception as exc:
        logger.exception("%s: copy failed", PLUGIN_NAME)
        _warn(PLUGIN_NAME, f"Could not copy the 3D model:\n{exc}")
        return False
    _status(
        "3D model copied - paste it into PowerPoint with Ctrl+V" + _skipped_note(scene)
    )
    return True


def _default_glb_path() -> str:
    mw = _context.get_main_window() if _context is not None else None
    init_manager = getattr(mw, "init_manager", None)
    current = getattr(init_manager, "current_file_path", None)
    if current:
        return os.path.splitext(current)[0] + ".glb"
    return os.path.join(os.path.expanduser("~"), "molecule.glb")


def export_glb(*_args) -> bool:
    """Export-menu action: write the 3D view to a .glb file."""
    from PySide6.QtWidgets import QFileDialog

    from .gltf_writer import build_glb

    parent = _context.get_main_window() if _context is not None else None
    path, _ = QFileDialog.getSaveFileName(
        parent,
        EXPORT_LABEL.rstrip("."),
        _default_glb_path(),
        "glTF Binary (*.glb);;All Files (*)",
    )
    if not path:
        return False
    if not path.lower().endswith(".glb"):
        path += ".glb"
    scene, _plotter = _capture()
    if scene is None:
        return False
    try:
        data = build_glb(
            scene.primitives, generator=f"MoleditPy {PLUGIN_NAME} {PLUGIN_VERSION}"
        )
        with open(path, "wb") as fh:
            fh.write(data)
    except Exception as exc:
        logger.exception("%s: export failed", PLUGIN_NAME)
        _warn(PLUGIN_NAME, f"Could not write {path}:\n{exc}")
        return False
    _status(f"3D scene exported to {path}" + _skipped_note(scene))
    return True


def open_settings(*_args) -> None:
    """Settings-menu action: show the settings window (one at a time)."""
    from .settings import save_settings
    from .settings_dialog import SettingsDialog

    if _context is not None:
        existing = _context.get_window(WINDOW_ID)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
    parent = _context.get_main_window() if _context is not None else None
    dlg = SettingsDialog(
        parent, _settings(), on_change=save_settings, on_copy=copy_to_powerpoint
    )
    if _context is not None:
        _context.register_window(WINDOW_ID, dlg)
    dlg.show()


def initialize(context):
    """Copy and glTF export go to the Export menu, the settings to the Settings menu."""
    global _context
    _context = context
    current_settings.clear()
    context.add_export_action(COPY_LABEL, copy_to_powerpoint)
    context.add_export_action(EXPORT_LABEL, export_glb)
    context.add_menu_action(SETTINGS_MENU_PATH, open_settings)
