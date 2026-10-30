"""Settings window: lighting, camera, line color and paste size."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from .gvml import LIGHT_PRESETS
from .settings import default_settings, sanitize


class SettingsDialog(QDialog):
    """Edits ``settings`` in place and calls ``on_change`` after every edit."""

    def __init__(self, parent, settings: dict, on_change, on_copy):
        super().__init__(parent)
        self.setWindowTitle("Paste 3D to PowerPoint Settings")
        self.settings = settings
        self._on_change = on_change
        self._on_copy = on_copy
        self._loading = False

        layout = QVBoxLayout(self)

        light_box = QGroupBox("Lighting in PowerPoint")
        light_form = QFormLayout(light_box)
        self.preset_combo = QComboBox()
        for key, rig in LIGHT_PRESETS.items():
            self.preset_combo.addItem(rig["label"], key)
        light_form.addRow("Light rig:", self.preset_combo)
        bright_row = QHBoxLayout()
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(10, 300)
        self.brightness_label = QLabel()
        self.brightness_label.setMinimumWidth(48)
        bright_row.addWidget(self.brightness_slider)
        bright_row.addWidget(self.brightness_label)
        light_form.addRow("Brightness:", bright_row)
        layout.addWidget(light_box)

        view_box = QGroupBox("View")
        view_form = QFormLayout(view_box)
        self.fov_spin = QDoubleSpinBox()
        self.fov_spin.setRange(1.0, 60.0)
        self.fov_spin.setSingleStep(1.0)
        self.fov_spin.setSuffix(" °")
        self.fov_spin.setToolTip(
            "PowerPoint has no parallel projection. A parallel-projection view is "
            "pasted with this field of view (smaller = flatter)."
        )
        view_form.addRow("Field of view for parallel projection:", self.fov_spin)
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(72.0, 720.0)
        self.size_spin.setSingleStep(12.0)
        self.size_spin.setDecimals(0)
        self.size_spin.setSuffix(" pt")
        view_form.addRow("Pasted size:", self.size_spin)
        layout.addWidget(view_box)

        line_box = QGroupBox("Lines (unit cell, axes, wireframes)")
        line_row = QHBoxLayout(line_box)
        self.line_check = QCheckBox("Replace line color with")
        self.line_check.setToolTip(
            "White unit-cell lines are invisible on a white slide."
        )
        self.line_color_button = QPushButton()
        self.line_color_button.setFixedWidth(64)
        line_row.addWidget(self.line_check)
        line_row.addWidget(self.line_color_button)
        line_row.addStretch(1)
        layout.addWidget(line_box)

        note = QLabel(
            "To make the model spin, select it in PowerPoint and choose "
            "Animations > Turntable."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        self.copy_button = buttons.addButton(
            "Copy 3D to PowerPoint", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.reset_button = buttons.addButton(
            "Reset to Defaults", QDialogButtonBox.ButtonRole.ResetRole
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        layout.addWidget(buttons)

        self.preset_combo.currentIndexChanged.connect(self._changed)
        self.brightness_slider.valueChanged.connect(self._changed)
        self.fov_spin.valueChanged.connect(self._changed)
        self.size_spin.valueChanged.connect(self._changed)
        self.line_check.toggled.connect(self._changed)
        self.line_color_button.clicked.connect(self._pick_line_color)
        self.copy_button.clicked.connect(self._copy)
        self.reset_button.clicked.connect(self.reset_to_defaults)
        buttons.rejected.connect(self.close)

        self.apply_settings(settings)

    def apply_settings(self, settings: dict) -> None:
        """Show ``settings`` in the widgets without re-saving them."""
        self._loading = True
        try:
            idx = self.preset_combo.findData(settings["light_preset"])
            self.preset_combo.setCurrentIndex(max(idx, 0))
            self.brightness_slider.setValue(int(round(settings["brightness"] * 100)))
            self.fov_spin.setValue(settings["parallel_fov_deg"])
            self.size_spin.setValue(settings["paste_size_pt"])
            self.line_check.setChecked(settings["override_line_color"])
            self._show_line_color(settings["line_color"])
        finally:
            self._loading = False
        self._update_labels()

    def collect(self) -> dict:
        return sanitize(
            {
                "light_preset": self.preset_combo.currentData(),
                "brightness": self.brightness_slider.value() / 100.0,
                "parallel_fov_deg": self.fov_spin.value(),
                "paste_size_pt": self.size_spin.value(),
                "override_line_color": self.line_check.isChecked(),
                "line_color": self.line_color_button.property("hex_color"),
            }
        )

    def _changed(self, *_args) -> None:
        self._update_labels()
        if self._loading:
            return
        self.settings.update(self.collect())
        self._on_change(self.settings)

    def _update_labels(self) -> None:
        self.brightness_label.setText(f"{self.brightness_slider.value()} %")
        self.line_color_button.setEnabled(self.line_check.isChecked())

    def _show_line_color(self, hex_color: str) -> None:
        self.line_color_button.setProperty("hex_color", hex_color)
        self.line_color_button.setStyleSheet(f"background-color: {hex_color};")

    def _pick_line_color(self) -> None:
        current = QColor(self.line_color_button.property("hex_color"))
        color = QColorDialog.getColor(current, self, "Line Color")
        if color.isValid():
            self._show_line_color(color.name())
            self._changed()

    def reset_to_defaults(self) -> None:
        self.apply_settings(default_settings())
        self._changed()

    def _copy(self) -> None:
        self._on_copy()
