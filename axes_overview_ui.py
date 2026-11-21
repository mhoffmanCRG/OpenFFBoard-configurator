"""All axes tab: range and independent axis effects of every FFB axis side by side.

Shown when the board runs more than one axis (for example the FFB wheel + command axes main class).
Each column is one axis (axis command instance). Values are applied per axis. Use Save to keep them.
"""
from PyQt6.QtWidgets import QGridLayout, QLabel, QSpinBox, QPushButton, QHBoxLayout, QVBoxLayout, QGroupBox
from PyQt6.QtCore import Qt
from base_ui import WidgetUI, CommunicationHandler


class AxesOverviewUI(WidgetUI, CommunicationHandler):
    # (command, label, min, max, tooltip)
    SETTINGS = [
        ("degrees", "Range (deg)", 1, 0x7FFF, "Rotation range. Soft endstops at both ends"),
        ("axisdamper", "Damper", 0, 255, "Always active damper of this axis"),
        ("axisinertia", "Inertia", 0, 255, "Always active inertia of this axis"),
        ("axisfriction", "Friction", 0, 255, "Always active friction of this axis"),
    ]

    def __init__(self, main=None):
        WidgetUI.__init__(self, main, "")
        CommunicationHandler.__init__(self)
        self.main = main
        self.axes = []  # Axis instances shown as columns
        self.boxes = {}  # (command, axis) -> QSpinBox

        layout = QVBoxLayout(self)
        self.group = QGroupBox("Range and axis effects of all axes")
        self.grid = QGridLayout(self.group)
        layout.addWidget(self.group)

        buttons = QHBoxLayout()
        self.button_read = QPushButton("Read")
        self.button_read.setToolTip("Read the values from the board")
        self.button_read.clicked.connect(self.read_values)
        self.button_copy = QPushButton("Copy axis 1 to all")
        self.button_copy.setToolTip("Fill all columns with the values of the first axis. Press Apply to send them")
        self.button_copy.clicked.connect(self.copy_first)
        self.button_apply = QPushButton("Apply")
        self.button_apply.setToolTip("Send all values to the board. Use Save to keep them after a restart")
        self.button_apply.clicked.connect(self.apply)
        buttons.addWidget(self.button_read)
        buttons.addWidget(self.button_copy)
        buttons.addStretch(1)
        buttons.addWidget(self.button_apply)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def set_axes(self, axes):
        """Rebuilds the grid for the given axis instances"""
        axes = sorted(set(axes))
        if axes == self.axes:
            return
        self.remove_callbacks()
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.boxes.clear()
        self.axes = axes

        for col, axis in enumerate(axes):
            header = QLabel(f"Axis {axis + 1}" + (" (wheel)" if axis == 0 else ""))
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(header, 0, col + 1)
        for row, (cmd, label, lo, hi, tip) in enumerate(self.SETTINGS):
            name = QLabel(label)
            name.setToolTip(tip)
            self.grid.addWidget(name, row + 1, 0)
            for col, axis in enumerate(axes):
                box = QSpinBox()
                box.setRange(lo, hi)
                box.setToolTip(tip)
                self.grid.addWidget(box, row + 1, col + 1)
                self.boxes[(cmd, axis)] = box
                # Also receives the replies to commands sent by the axis tabs, so both stay in sync
                self.register_callback("axis", cmd, box.setValue, axis, int)
        self.read_values()

    def read_values(self):
        for axis in self.axes:
            self.send_commands("axis", [s[0] for s in self.SETTINGS], axis)

    def copy_first(self):
        if not self.axes:
            return
        first = self.axes[0]
        for cmd, *_ in self.SETTINGS:
            val = self.boxes[(cmd, first)].value()
            for axis in self.axes[1:]:
                self.boxes[(cmd, axis)].setValue(val)

    def apply(self):
        for axis in self.axes:
            for cmd, *_ in self.SETTINGS:
                self.send_value("axis", cmd, self.boxes[(cmd, axis)].value(), instance=axis)
        self.read_values()  # Replies also update the axis tabs
