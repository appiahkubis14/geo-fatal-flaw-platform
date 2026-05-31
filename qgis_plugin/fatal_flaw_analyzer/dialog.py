"""
fatal_flaw_analyzer/dialog.py
Settings dialog for configuring the Fatal Flaw Analyzer plugin.
"""

from __future__ import annotations

from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QVBoxLayout,
)
from qgis.PyQt.QtGui import QIntValidator


class SettingsDialog(QDialog):
    """Plugin settings dialog."""

    def __init__(self, parent, current_config: dict):
        super().__init__(parent)
        self.setWindowTitle("Fatal Flaw Analyzer — Settings")
        self.setMinimumWidth(420)
        self.config = dict(current_config)

        layout = QVBoxLayout(self)

        # ── API Settings ──────────────────────────────────────────────────
        api_group = QGroupBox("API Connection")
        api_form = QFormLayout(api_group)

        self.api_url_edit = QLineEdit(self.config.get("api_url", "http://localhost:8000"))
        api_form.addRow("API URL:", self.api_url_edit)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self.timeout_spin.setValue(self.config.get("api_timeout", 30))
        self.timeout_spin.setSuffix(" seconds")
        api_form.addRow("Timeout:", self.timeout_spin)

        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._test_connection)
        api_form.addRow("", test_btn)
        self.connection_status = QLabel("")
        api_form.addRow("", self.connection_status)

        layout.addWidget(api_group)

        # ── Analysis Settings ─────────────────────────────────────────────
        analysis_group = QGroupBox("Analysis Defaults")
        analysis_form = QFormLayout(analysis_group)

        self.site_type_combo = QComboBox()
        self.site_type_combo.addItems(["solar", "wind", "bess", "datacenter"])
        self.site_type_combo.setCurrentText(self.config.get("site_type", "solar"))
        analysis_form.addRow("Default Site Type:", self.site_type_combo)

        layout.addWidget(analysis_group)

        # ── Output Settings ───────────────────────────────────────────────
        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)

        dir_row = QHBoxLayout()
        self.output_dir_edit = QLineEdit(self.config.get("output_dir", ""))
        self.output_dir_edit.setPlaceholderText("Default PDF output directory")
        dir_row.addWidget(self.output_dir_edit)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        output_layout.addLayout(dir_row)
        layout.addWidget(output_group)

        # ── Buttons ───────────────────────────────────────────────────────
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _test_connection(self):
        from .api_client import ApiClient
        client = ApiClient({"api_url": self.api_url_edit.text(), "api_timeout": 5})
        if client.health_check():
            self.connection_status.setText("✅ Connected")
            self.connection_status.setStyleSheet("color: green;")
        else:
            self.connection_status.setText("❌ Cannot connect")
            self.connection_status.setStyleSheet("color: red;")

    def _browse_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.output_dir_edit.setText(directory)

    def get_config(self) -> dict:
        return {
            "api_url": self.api_url_edit.text().rstrip("/"),
            "api_timeout": self.timeout_spin.value(),
            "site_type": self.site_type_combo.currentText(),
            "output_dir": self.output_dir_edit.text(),
            "risk_colors": self.config.get("risk_colors", {}),
        }
