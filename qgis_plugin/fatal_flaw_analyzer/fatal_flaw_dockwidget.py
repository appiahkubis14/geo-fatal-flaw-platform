"""
fatal_flaw_analyzer/fatal_flaw_dockwidget.py
Main dock widget UI: layer selector, analyze button, results panel,
color-coded polygon overlay, and report generation trigger.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsMapLayer,
    QgsMessageLog,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QTimer
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDockWidget,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .api_client import ApiClient, AssessmentWorker


RISK_COLORS = {
    "low":    QColor("#4CAF50"),  # Green
    "medium": QColor("#FFC107"),  # Yellow
    "high":   QColor("#FF9800"),  # Orange
    "fatal":  QColor("#F44336"),  # Red
}

RISK_THRESHOLDS = {"low": 25, "medium": 50, "high": 75}


def score_to_risk_level(score: float, fatal: bool) -> str:
    if fatal:
        return "fatal"
    if score <= RISK_THRESHOLDS["low"]:
        return "low"
    if score <= RISK_THRESHOLDS["medium"]:
        return "medium"
    if score <= RISK_THRESHOLDS["high"]:
        return "high"
    return "fatal"


class FatalFlawDockWidget(QDockWidget):
    """
    Main dock widget for the Fatal Flaw Analyzer plugin.
    Provides: layer selection, site analysis trigger, results display,
    polygon color overlay, and PDF report generation.
    """

    def __init__(self, iface, api_config: dict, parent=None):
        super().__init__("Fatal Flaw Analyzer", parent)
        self.iface = iface
        self.api_config = api_config
        self.api_client = ApiClient(api_config)
        self._last_result: Optional[dict] = None
        self._scored_layer: Optional[QgsVectorLayer] = None
        self._worker: Optional[AssessmentWorker] = None

        self._build_ui()
        self._refresh_layer_list()

        # Refresh layer list when project layers change
        QgsProject.instance().layersAdded.connect(self._refresh_layer_list)
        QgsProject.instance().layersRemoved.connect(self._refresh_layer_list)

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ── Header ────────────────────────────────────────────────────────
        header = QLabel("⚡ Fatal Flaw Analyzer")
        header.setStyleSheet("font-size: 14px; font-weight: bold; color: #2c3e50; padding: 4px;")
        main_layout.addWidget(header)

        # ── Site configuration ────────────────────────────────────────────
        cfg_group = QGroupBox("Site Configuration")
        cfg_layout = QVBoxLayout(cfg_group)

        # Layer selector
        lyr_row = QHBoxLayout()
        lyr_row.addWidget(QLabel("Polygon Layer:"))
        self.layer_combo = QComboBox()
        self.layer_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lyr_row.addWidget(self.layer_combo)
        cfg_layout.addLayout(lyr_row)

        # Site type selector
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Site Type:"))
        self.site_type_combo = QComboBox()
        self.site_type_combo.addItems(["solar", "wind", "bess", "datacenter"])
        type_row.addWidget(self.site_type_combo)
        cfg_layout.addLayout(type_row)

        # Feature selector (first selected, or all)
        feat_row = QHBoxLayout()
        feat_row.addWidget(QLabel("Analyze:"))
        self.feature_combo = QComboBox()
        self.feature_combo.addItems(["Selected features", "All features"])
        feat_row.addWidget(self.feature_combo)
        cfg_layout.addLayout(feat_row)

        main_layout.addWidget(cfg_group)

        # ── Analyze button ────────────────────────────────────────────────
        self.analyze_btn = QPushButton("🔍 Analyze Site")
        self.analyze_btn.setStyleSheet(
            "QPushButton { background: #2196F3; color: white; font-weight: bold; "
            "padding: 8px; border-radius: 4px; }"
            "QPushButton:hover { background: #1976D2; }"
            "QPushButton:disabled { background: #B0BEC5; }"
        )
        self.analyze_btn.clicked.connect(self._run_analysis)
        main_layout.addWidget(self.analyze_btn)

        # ── Progress bar ─────────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)   # indeterminate
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("QProgressBar { height: 6px; }")
        main_layout.addWidget(self.progress_bar)

        # ── Status label ──────────────────────────────────────────────────
        self.status_label = QLabel("Ready — select a polygon layer to begin.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #555; font-size: 11px; padding: 2px;")
        main_layout.addWidget(self.status_label)

        # ── Results panel ─────────────────────────────────────────────────
        self.results_group = QGroupBox("Assessment Results")
        self.results_group.setVisible(False)
        results_layout = QVBoxLayout(self.results_group)

        # Score display
        self.score_label = QLabel("—")
        self.score_label.setAlignment(Qt.AlignCenter)
        self.score_label.setStyleSheet(
            "font-size: 36px; font-weight: bold; padding: 8px; border-radius: 6px;"
        )
        results_layout.addWidget(self.score_label)

        # Fatal flag
        self.fatal_label = QLabel()
        self.fatal_label.setAlignment(Qt.AlignCenter)
        self.fatal_label.setStyleSheet("font-size: 13px; font-weight: bold; padding: 4px;")
        results_layout.addWidget(self.fatal_label)

        # Site area
        self.area_label = QLabel()
        self.area_label.setAlignment(Qt.AlignCenter)
        self.area_label.setStyleSheet("color: #555; font-size: 11px;")
        results_layout.addWidget(self.area_label)

        # Processing time
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("color: #888; font-size: 10px;")
        results_layout.addWidget(self.time_label)

        # Top risks table
        top_risks_label = QLabel("Top Constraints:")
        top_risks_label.setStyleSheet("font-weight: bold; margin-top: 6px;")
        results_layout.addWidget(top_risks_label)

        self.risks_table = QTableWidget(0, 4)
        self.risks_table.setHorizontalHeaderLabels(["Layer", "Area (ac)", "% Site", "Score"])
        self.risks_table.horizontalHeader().setStretchLastSection(True)
        self.risks_table.setMaximumHeight(160)
        self.risks_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.risks_table.setSelectionMode(QTableWidget.SingleSelection)
        results_layout.addWidget(self.risks_table)

        # Action buttons
        btn_row = QHBoxLayout()
        self.report_btn = QPushButton("📄 Generate PDF")
        self.report_btn.clicked.connect(self._generate_pdf)
        self.report_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; padding: 6px; border-radius: 4px; }"
            "QPushButton:hover { background: #388E3C; }"
        )
        btn_row.addWidget(self.report_btn)

        self.copy_btn = QPushButton("📋 Copy JSON")
        self.copy_btn.clicked.connect(self._copy_results)
        self.copy_btn.setStyleSheet(
            "QPushButton { background: #607D8B; color: white; padding: 6px; border-radius: 4px; }"
            "QPushButton:hover { background: #455A64; }"
        )
        btn_row.addWidget(self.copy_btn)
        results_layout.addLayout(btn_row)

        main_layout.addWidget(self.results_group)
        main_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(container)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWidget(scroll)
        self.setMinimumWidth(300)

    # ── Layer list ───────────────────────────────────────────────────────────

    def _refresh_layer_list(self):
        self.layer_combo.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if (isinstance(layer, QgsVectorLayer)
                    and layer.geometryType() == QgsWkbTypes.PolygonGeometry):
                self.layer_combo.addItem(layer.name(), layer.id())

    def _get_selected_layer(self) -> Optional[QgsVectorLayer]:
        layer_id = self.layer_combo.currentData()
        if not layer_id:
            return None
        return QgsProject.instance().mapLayer(layer_id)

    # ── Analysis ─────────────────────────────────────────────────────────────

    def _run_analysis(self):
        layer = self._get_selected_layer()
        if not layer:
            self._set_status("❌ No polygon layer selected.", error=True)
            return

        # Get features to analyze
        use_selected = self.feature_combo.currentIndex() == 0
        if use_selected:
            features = list(layer.selectedFeatures())
            if not features:
                self._set_status("❌ No features selected. Select one or more polygons first.", error=True)
                return
        else:
            features = list(layer.getFeatures())

        if not features:
            self._set_status("❌ Layer has no features.", error=True)
            return

        # For now analyze first feature; multi-feature loop can be added
        feature = features[0]
        geom = feature.geometry()
        if geom.isEmpty():
            self._set_status("❌ Selected feature has empty geometry.", error=True)
            return

        # Convert to GeoJSON
        geojson_str = geom.asJson()
        try:
            geojson_dict = json.loads(geojson_str)
        except Exception as e:
            self._set_status(f"❌ Could not parse geometry: {e}", error=True)
            return

        site_name = str(feature.id())
        for field in layer.fields():
            if field.name().lower() in ("name", "site_name", "label", "id"):
                val = feature[field.name()]
                if val:
                    site_name = str(val)
                    break

        site_type = self.site_type_combo.currentText()

        # Start async worker
        self.analyze_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self._set_status("⏳ Analyzing site against 15 constraint layers…")
        self.results_group.setVisible(False)

        self._worker = AssessmentWorker(
            api_client=self.api_client,
            geometry=geojson_dict,
            site_name=site_name,
            site_type=site_type,
        )
        self._worker.finished.connect(self._on_analysis_complete)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.start()

        # Store reference to analyzed layer for overlay
        self._scored_layer = layer
        self._scored_feature_id = feature.id()

    def _on_analysis_complete(self, result: dict):
        self._last_result = result
        self._show_results(result)
        self._apply_color_overlay(result)
        self.analyze_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

    def _on_analysis_error(self, error_msg: str):
        self._set_status(f"❌ API error: {error_msg}", error=True)
        self.analyze_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

    # ── Results display ──────────────────────────────────────────────────────

    def _show_results(self, result: dict):
        score = result.get("overall_risk_score", 0)
        fatal = result.get("fatal_flag", False)
        risk_level = score_to_risk_level(score, fatal)
        color = RISK_COLORS[risk_level]

        # Score label
        self.score_label.setText(f"{score:.1f}")
        self.score_label.setStyleSheet(
            f"font-size: 36px; font-weight: bold; padding: 8px; border-radius: 6px; "
            f"background-color: {color.name()}; color: white;"
        )

        # Fatal label
        if fatal:
            fatal_layers = ", ".join(result.get("fatal_layers", []))
            self.fatal_label.setText(f"⛔ FATAL — {fatal_layers}")
            self.fatal_label.setStyleSheet("color: #F44336; font-size: 12px; font-weight: bold;")
        else:
            self.fatal_label.setText(f"✅ Risk Level: {risk_level.upper()}")
            self.fatal_label.setStyleSheet(f"color: {color.name()}; font-size: 12px; font-weight: bold;")

        # Area and timing
        self.area_label.setText(f"Site area: {result.get('site_area_acres', 0):.1f} acres")
        self.time_label.setText(f"Analyzed in {result.get('processing_time_ms', 0)}ms")

        # Top risks table
        top_risks = result.get("top_risks", [])
        self.risks_table.setRowCount(len(top_risks))
        for i, risk in enumerate(top_risks):
            self.risks_table.setItem(i, 0, QTableWidgetItem(risk["layer_name"]))
            self.risks_table.setItem(i, 1, QTableWidgetItem(f"{risk.get('impact_area_acres', 0):.2f}"))
            self.risks_table.setItem(i, 2, QTableWidgetItem(f"{risk.get('percentage_of_site', 0):.1f}%"))
            score_item = QTableWidgetItem(f"{risk.get('contribution_score', 0):.1f}")
            if risk.get("is_fatal"):
                score_item.setForeground(QColor("#F44336"))
            self.risks_table.setItem(i, 3, score_item)

        self.risks_table.resizeColumnsToContents()
        self._set_status(f"✓ Assessment complete — {result.get('site_name', 'Site')}")
        self.results_group.setVisible(True)

    # ── Color overlay ────────────────────────────────────────────────────────

    def _apply_color_overlay(self, result: dict):
        """Color-code the analyzed polygon in QGIS based on risk score."""
        if not self._scored_layer:
            return

        score = result.get("overall_risk_score", 0)
        fatal = result.get("fatal_flag", False)
        risk_level = score_to_risk_level(score, fatal)
        color = RISK_COLORS[risk_level]

        try:
            from qgis.core import (
                QgsCategorizedSymbolRenderer,
                QgsRendererCategory,
                QgsSimpleFillSymbolLayer,
                QgsSymbol,
            )
            symbol = QgsSymbol.defaultSymbol(self._scored_layer.geometryType())
            symbol.setColor(color)
            symbol.setOpacity(0.6)

            # Apply to just the scored feature via rule-based renderer
            # For simplicity: change whole layer renderer color
            self._scored_layer.renderer().symbol().setColor(color)
            self._scored_layer.renderer().symbol().setOpacity(0.6)
            self._scored_layer.triggerRepaint()
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Could not apply overlay: {e}", "Fatal Flaw", level=1
            )

    # ── PDF generation ───────────────────────────────────────────────────────

    def _generate_pdf(self):
        if not self._last_result:
            self._set_status("❌ Run an assessment first.", error=True)
            return

        from qgis.PyQt.QtWidgets import QFileDialog
        output_dir = self.api_config.get("output_dir", str(Path.home()))
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        site_name = self._last_result.get("site_name", "site").replace(" ", "_")
        default_path = str(Path(output_dir) / f"FatalFlaw_{site_name}.pdf")

        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF Report", default_path, "PDF Files (*.pdf)"
        )
        if not path:
            return

        try:
            from .report_generator import ReportGenerator
            gen = ReportGenerator(self.iface, self._last_result, self._scored_layer)
            gen.generate_pdf(path)
            self._set_status(f"✓ PDF saved: {path}")
        except Exception as e:
            self._set_status(f"❌ PDF generation failed: {e}", error=True)
            QgsMessageLog.logMessage(f"PDF error: {e}", "Fatal Flaw", level=2)

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _copy_results(self):
        if self._last_result:
            from qgis.PyQt.QtWidgets import QApplication
            QApplication.clipboard().setText(
                json.dumps(self._last_result, indent=2, default=str)
            )
            self._set_status("✓ JSON copied to clipboard.")

    def _set_status(self, msg: str, error: bool = False):
        self.status_label.setText(msg)
        color = "#c0392b" if error else "#555"
        self.status_label.setStyleSheet(f"color: {color}; font-size: 11px; padding: 2px;")

    def update_api_config(self, config: dict):
        self.api_config = config
        self.api_client = ApiClient(config)
