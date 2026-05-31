"""
fatal_flaw_analyzer/fatal_flaw_analyzer.py
Main QGIS plugin class. Manages lifecycle, dock widget, and actions.
Compatible with QGIS 3.28+ LTR.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsMessageLog,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QDockWidget,
    QMessageBox,
)

from .fatal_flaw_dockwidget import FatalFlawDockWidget
from .dialog import SettingsDialog


PLUGIN_NAME = "Fatal Flaw Analyzer"
SETTINGS_PREFIX = "fatal_flaw_analyzer"


class FatalFlawAnalyzer:
    """Main QGIS plugin class."""

    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.dock_widget: FatalFlawDockWidget | None = None
        self.actions: list[QAction] = []
        self.plugin_dir = Path(__file__).parent

        # Load persisted settings
        self.settings = QSettings()

    # ── Plugin lifecycle ─────────────────────────────────────────────────────

    def initGui(self):
        """Create menu entry and dock widget."""
        icon_path = str(self.plugin_dir / "icons" / "icon.svg")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        # Main action: open dock widget
        self.action_open = QAction(icon, "Fatal Flaw Analyzer", self.iface.mainWindow())
        self.action_open.setCheckable(True)
        self.action_open.triggered.connect(self._toggle_dock)
        self.iface.addToolBarIcon(self.action_open)
        self.iface.addPluginToMenu(PLUGIN_NAME, self.action_open)
        self.actions.append(self.action_open)

        # Settings action
        self.action_settings = QAction("Settings…", self.iface.mainWindow())
        self.action_settings.triggered.connect(self._open_settings)
        self.iface.addPluginToMenu(PLUGIN_NAME, self.action_settings)
        self.actions.append(self.action_settings)

        # Create dock widget
        self._create_dock()

    def unload(self):
        """Remove the plugin menu items and dock widget."""
        for action in self.actions:
            self.iface.removePluginMenu(PLUGIN_NAME, action)
            self.iface.removeToolBarIcon(action)
        if self.dock_widget:
            self.iface.removeDockWidget(self.dock_widget)
            self.dock_widget.deleteLater()

    # ── Dock widget ──────────────────────────────────────────────────────────

    def _create_dock(self):
        self.dock_widget = FatalFlawDockWidget(self.iface, self._get_api_config())
        self.dock_widget.setObjectName("FatalFlawDockWidget")
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)
        self.dock_widget.hide()
        self.dock_widget.visibilityChanged.connect(self.action_open.setChecked)

    def _toggle_dock(self, checked: bool):
        if self.dock_widget:
            if checked:
                self.dock_widget.show()
            else:
                self.dock_widget.hide()

    # ── Settings ─────────────────────────────────────────────────────────────

    def _open_settings(self):
        dlg = SettingsDialog(self.iface.mainWindow(), self._get_api_config())
        if dlg.exec_():
            config = dlg.get_config()
            self._save_api_config(config)
            if self.dock_widget:
                self.dock_widget.update_api_config(config)

    def _get_api_config(self) -> dict:
        s = self.settings
        return {
            "api_url": s.value(f"{SETTINGS_PREFIX}/api_url", "http://localhost:8000"),
            "api_timeout": int(s.value(f"{SETTINGS_PREFIX}/api_timeout", 30)),
            "site_type": s.value(f"{SETTINGS_PREFIX}/site_type", "solar"),
            "output_dir": s.value(f"{SETTINGS_PREFIX}/output_dir",
                                   str(Path.home() / "fatal_flaw_reports")),
            "risk_colors": {
                "low":    s.value(f"{SETTINGS_PREFIX}/color_low",    "#4CAF50"),
                "medium": s.value(f"{SETTINGS_PREFIX}/color_medium",  "#FFC107"),
                "high":   s.value(f"{SETTINGS_PREFIX}/color_high",    "#FF9800"),
                "fatal":  s.value(f"{SETTINGS_PREFIX}/color_fatal",   "#F44336"),
            },
        }

    def _save_api_config(self, config: dict):
        s = self.settings
        s.setValue(f"{SETTINGS_PREFIX}/api_url", config["api_url"])
        s.setValue(f"{SETTINGS_PREFIX}/api_timeout", config["api_timeout"])
        s.setValue(f"{SETTINGS_PREFIX}/site_type", config["site_type"])
        s.setValue(f"{SETTINGS_PREFIX}/output_dir", config["output_dir"])
        for level, color in config.get("risk_colors", {}).items():
            s.setValue(f"{SETTINGS_PREFIX}/color_{level}", color)
