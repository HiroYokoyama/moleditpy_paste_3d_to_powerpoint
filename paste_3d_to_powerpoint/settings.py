"""User preferences, kept in settings.json beside the package."""

import json
import logging
import os

from .gvml import DEFAULT_LIGHT_PRESET, LIGHT_PRESETS

logger = logging.getLogger(__name__)

SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "settings.json"
)

DEFAULTS = {
    "light_preset": DEFAULT_LIGHT_PRESET,
    "brightness": 1.0,
    # PowerPoint only has perspective cameras; a narrow field of view stands in
    # for MoleditPy's parallel projection.
    "parallel_fov_deg": 10.0,
    # White unit-cell lines vanish on a white slide.
    "override_line_color": False,
    "line_color": "#404040",
    "paste_size_pt": 360.0,
}

LIMITS = {
    "brightness": (0.1, 3.0),
    "parallel_fov_deg": (1.0, 60.0),
    "paste_size_pt": (72.0, 720.0),
}


def default_settings() -> dict:
    return dict(DEFAULTS)


def sanitize(data: dict) -> dict:
    """Defaults merged with the valid, clamped entries of ``data``."""
    out = default_settings()
    if not isinstance(data, dict):
        return out
    if data.get("light_preset") in LIGHT_PRESETS:
        out["light_preset"] = data["light_preset"]
    for key, (lo, hi) in LIMITS.items():
        try:
            out[key] = min(max(float(data[key]), lo), hi)
        except (KeyError, TypeError, ValueError):
            pass
    if isinstance(data.get("override_line_color"), bool):
        out["override_line_color"] = data["override_line_color"]
    color = data.get("line_color")
    if isinstance(color, str) and len(color) == 7 and color.startswith("#"):
        try:
            int(color[1:], 16)
            out["line_color"] = color.lower()
        except ValueError:
            pass
    return out


def load_settings(path=None) -> dict:
    path = path or SETTINGS_FILE
    try:
        with open(path, encoding="utf-8") as fh:
            return sanitize(json.load(fh))
    except FileNotFoundError:
        return default_settings()
    except (OSError, ValueError):
        logger.warning("Paste 3D: ignoring unreadable %s", path, exc_info=True)
        return default_settings()


def save_settings(settings: dict, path=None) -> None:
    path = path or SETTINGS_FILE
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(sanitize(settings), fh, indent=2)
    except OSError:
        logger.warning("Paste 3D: could not save %s", path, exc_info=True)


def hex_to_rgb(color: str):
    return tuple(int(color[i : i + 2], 16) / 255.0 for i in (1, 3, 5))


def apply_line_color(primitives, settings: dict) -> None:
    """Recolor tubes made from lines when the override is on."""
    if not settings.get("override_line_color"):
        return
    rgb = hex_to_rgb(settings["line_color"])
    for prim in primitives:
        if prim.extras.get("line"):
            prim.color = (*rgb, prim.color[3])
            prim.vertex_colors = None
