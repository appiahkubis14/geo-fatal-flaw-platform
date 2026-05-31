"""
fatal_flaw_analyzer/report_generator.py
Programmatic PDF report generation using QGIS Print Layout API.
Generates a 4-page professional report without requiring user interaction
with the print layout editor.

Pages:
  1 — Executive Summary (score gauge, fatal flag, site metadata)
  2 — Top 5 Risks (table + bar chart description)
  3 — Map Section (locator map + constraint overlay)
  4 — Complete Results Table (all 15 layers)
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

from qgis.core import (
    QgsLayout,
    QgsLayoutExporter,
    QgsLayoutItemLabel,
    QgsLayoutItemMap,
    QgsLayoutItemPage,
    QgsLayoutItemPicture,
    QgsLayoutItemShape,
    QgsLayoutItemTable,
    QgsLayoutMeasurement,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsPrintLayout,
    QgsProject,
    QgsRectangle,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPageSize


class ReportGenerator:
    """
    Generates a multi-page PDF report from a Fatal Flaw assessment result.
    All layout items are created programmatically — no .qpt template file needed.
    """

    # Page dimensions (A4 landscape, mm)
    PAGE_W = 297.0
    PAGE_H = 210.0
    MARGIN = 15.0

    # Risk colors
    COLORS = {
        "low":    QColor("#4CAF50"),
        "medium": QColor("#FFC107"),
        "high":   QColor("#FF9800"),
        "fatal":  QColor("#F44336"),
    }

    def __init__(self, iface, result: dict, site_layer: Optional[QgsVectorLayer] = None):
        self.iface = iface
        self.result = result
        self.site_layer = site_layer
        self.layout: Optional[QgsPrintLayout] = None

    def generate_pdf(self, output_path: str) -> None:
        """
        Create a QgsPrintLayout, populate all pages, export to PDF.
        Removes the layout from the project after export.
        """
        project = QgsProject.instance()
        layout_name = f"FatalFlawReport_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        self.layout = QgsPrintLayout(project)
        self.layout.initializeDefaults()
        self.layout.setName(layout_name)

        # Page size: A4 landscape
        pc = self.layout.pageCollection()

        # Build 4 pages
        for page_num in range(4):
            if page_num == 0:
                page = pc.pages()[0]
            else:
                page = QgsLayoutItemPage(self.layout)
                pc.addPage(page)
            page.setPageSize(
                QgsLayoutSize(self.PAGE_W, self.PAGE_H, QgsUnitTypes.LayoutMillimeters)
            )

        self._build_page_1()
        self._build_page_2()
        self._build_page_3()
        self._build_page_4()

        # Export
        exporter = QgsLayoutExporter(self.layout)
        pdf_settings = QgsLayoutExporter.PdfExportSettings()
        result_code = exporter.exportToPdf(output_path, pdf_settings)

        # Cleanup
        project.layoutManager().removeLayout(self.layout)

        if result_code != QgsLayoutExporter.Success:
            raise RuntimeError(f"PDF export failed with code {result_code}")

    # ── Page 1: Executive Summary ────────────────────────────────────────────

    def _build_page_1(self):
        page_idx = 0
        r = self.result
        score = r.get("overall_risk_score", 0)
        fatal = r.get("fatal_flag", False)
        risk_level = self._score_to_level(score, fatal)

        # ── Header bar ────────────────────────────────────────────────────
        self._add_rect(0, 0, self.PAGE_W, 18, QColor("#2c3e50"), page_idx)
        self._add_label(
            "FATAL FLAW GEOSPATIAL RISK ASSESSMENT", 5, 3, self.PAGE_W - 10, 12,
            page_idx, font_size=14, bold=True, color=QColor("white"),
            alignment=Qt.AlignCenter,
        )

        # ── Score circle (rectangle as proxy) ─────────────────────────────
        score_color = self.COLORS[risk_level]
        self._add_rect(self.MARGIN, 25, 60, 60, score_color, page_idx)
        self._add_label(
            f"{score:.0f}", self.MARGIN, 38, 60, 20,
            page_idx, font_size=28, bold=True, color=QColor("white"),
            alignment=Qt.AlignCenter,
        )
        self._add_label(
            "/ 100", self.MARGIN, 58, 60, 10,
            page_idx, font_size=10, color=QColor("white"),
            alignment=Qt.AlignCenter,
        )
        self._add_label(
            "RISK SCORE", self.MARGIN, 70, 60, 8,
            page_idx, font_size=8, bold=True, color=QColor("white"),
            alignment=Qt.AlignCenter,
        )

        # ── Fatal flag indicator ──────────────────────────────────────────
        flag_color = QColor("#F44336") if fatal else QColor("#4CAF50")
        flag_text = "⛔  FATAL FLAW DETECTED" if fatal else "✅  No Fatal Constraints"
        self._add_rect(self.MARGIN, 88, 60, 14, flag_color, page_idx)
        self._add_label(
            flag_text, self.MARGIN, 90, 60, 10,
            page_idx, font_size=8, bold=True, color=QColor("white"),
            alignment=Qt.AlignCenter,
        )

        # ── Site metadata ─────────────────────────────────────────────────
        meta_x = self.MARGIN + 70
        meta_items = [
            ("Site Name", r.get("site_name", "Unnamed")),
            ("Site Type", r.get("site_type", "solar").upper()),
            ("Site Area", f"{r.get('site_area_acres', 0):,.1f} acres"),
            ("Assessment ID", str(r.get("assessment_id", ""))[:18] + "…"),
            ("Date", r.get("assessment_timestamp", "")[:10]),
            ("Processing Time", f"{r.get('processing_time_ms', 0)} ms"),
        ]
        for i, (label, value) in enumerate(meta_items):
            y = 28 + i * 12
            self._add_label(label + ":", meta_x, y, 50, 10, page_idx,
                            font_size=9, bold=True, color=QColor("#2c3e50"))
            self._add_label(value, meta_x + 52, y, 80, 10, page_idx,
                            font_size=9, color=QColor("#333"))

        # ── Fatal layers list (if any) ─────────────────────────────────────
        if fatal and r.get("fatal_layers"):
            self._add_label(
                "Fatal Constraints: " + ", ".join(r["fatal_layers"]),
                self.MARGIN, 105, self.PAGE_W - 2 * self.MARGIN, 10,
                page_idx, font_size=9, bold=True, color=QColor("#c0392b"),
            )

        # ── Risk level legend ──────────────────────────────────────────────
        legend_y = 120
        self._add_label("RISK SCALE", self.MARGIN, legend_y, 80, 8, page_idx,
                        font_size=8, bold=True, color=QColor("#555"))
        levels = [("LOW (0-25)", "low"), ("MODERATE (26-50)", "medium"),
                  ("HIGH (51-75)", "high"), ("FATAL (76-100)", "fatal")]
        for i, (lbl, lvl) in enumerate(levels):
            x = self.MARGIN + i * 65
            self._add_rect(x, legend_y + 6, 60, 8, self.COLORS[lvl], page_idx)
            self._add_label(lbl, x, legend_y + 7, 60, 6, page_idx,
                            font_size=6, color=QColor("white"), alignment=Qt.AlignCenter)

        # ── Footer ────────────────────────────────────────────────────────
        self._add_label(
            "Page 1 of 4 — Fatal Flaw Geospatial Risk Assessment Platform v1.0",
            self.MARGIN, self.PAGE_H - 10, self.PAGE_W - 2 * self.MARGIN, 6,
            page_idx, font_size=7, color=QColor("#999"), alignment=Qt.AlignCenter,
        )

    # ── Page 2: Top 5 Risks ──────────────────────────────────────────────────

    def _build_page_2(self):
        page_idx = 1
        top_risks = self.result.get("top_risks", [])

        self._add_rect(0, 0, self.PAGE_W, 14, QColor("#2c3e50"), page_idx)
        self._add_label(
            "TOP CONSTRAINT ANALYSIS", 5, 2, self.PAGE_W - 10, 10,
            page_idx, font_size=12, bold=True, color=QColor("white"), alignment=Qt.AlignCenter,
        )

        if not top_risks:
            self._add_label(
                "No constraint intersections detected for this site.",
                self.MARGIN, 40, self.PAGE_W - 2 * self.MARGIN, 12,
                page_idx, font_size=12, color=QColor("#555"), alignment=Qt.AlignCenter,
            )
            return

        # Table headers
        cols = ["Constraint Layer", "Category", "Area (acres)", "% of Site",
                "Score", "Weight", "Fatal?"]
        col_widths = [60, 28, 28, 22, 22, 22, 18]
        table_x = self.MARGIN
        table_y = 20

        # Header row
        x = table_x
        for col, w in zip(cols, col_widths):
            self._add_rect(x, table_y, w, 8, QColor("#2c3e50"), page_idx)
            self._add_label(col, x + 1, table_y + 1, w - 2, 6, page_idx,
                            font_size=6, bold=True, color=QColor("white"))
            x += w

        # Data rows
        for i, risk in enumerate(top_risks[:10]):
            row_y = table_y + 8 + i * 9
            bg = QColor("#f8f9fa") if i % 2 == 0 else QColor("white")
            row_color = QColor("#ffebee") if risk.get("is_fatal") else bg

            x = table_x
            row_vals = [
                risk.get("layer_name", ""),
                risk.get("category", ""),
                f"{risk.get('impact_area_acres', 0):.2f}",
                f"{risk.get('percentage_of_site', 0):.1f}%",
                f"{risk.get('contribution_score', 0):.1f}",
                f"{risk.get('weight', 0):.2f}",
                "YES ⛔" if risk.get("is_fatal") else "No",
            ]
            for val, w in zip(row_vals, col_widths):
                self._add_rect(x, row_y, w, 8, row_color, page_idx)
                self._add_label(str(val), x + 1, row_y + 1, w - 2, 6, page_idx, font_size=6)
                x += w

        # Bar chart (visual representation using rectangles)
        chart_y = table_y + 8 + len(top_risks[:10]) * 9 + 10
        max_bar_w = 150
        max_score = max((r.get("contribution_score", 0) for r in top_risks), default=1)

        self._add_label("CONTRIBUTION SCORES", self.MARGIN, chart_y, 100, 8,
                        page_idx, font_size=8, bold=True, color=QColor("#2c3e50"))
        chart_y += 8

        for i, risk in enumerate(top_risks[:5]):
            bar_y = chart_y + i * 11
            score_val = risk.get("contribution_score", 0)
            bar_w = max(2, (score_val / max(max_score, 1)) * max_bar_w)
            level = self._score_to_level(score_val * 3, risk.get("is_fatal", False))

            self._add_label(
                risk.get("layer_name", ""), self.MARGIN, bar_y, 60, 8,
                page_idx, font_size=7, color=QColor("#333"),
            )
            self._add_rect(self.MARGIN + 62, bar_y + 1, bar_w, 6,
                           self.COLORS[level], page_idx)
            self._add_label(
                f"{score_val:.1f}", self.MARGIN + 62 + bar_w + 2, bar_y, 20, 8,
                page_idx, font_size=7, color=QColor("#555"),
            )

        self._add_label(
            "Page 2 of 4 — Fatal Flaw Geospatial Risk Assessment Platform v1.0",
            self.MARGIN, self.PAGE_H - 10, self.PAGE_W - 2 * self.MARGIN, 6,
            page_idx, font_size=7, color=QColor("#999"), alignment=Qt.AlignCenter,
        )

    # ── Page 3: Map Section ───────────────────────────────────────────────────

    def _build_page_3(self):
        page_idx = 2
        self._add_rect(0, 0, self.PAGE_W, 14, QColor("#2c3e50"), page_idx)
        self._add_label(
            "SITE MAP & CONSTRAINT OVERLAY", 5, 2, self.PAGE_W - 10, 10,
            page_idx, font_size=12, bold=True, color=QColor("white"), alignment=Qt.AlignCenter,
        )

        # Main map item
        try:
            map_item = QgsLayoutItemMap(self.layout)
            map_item.attemptResize(QgsLayoutSize(
                self.PAGE_W - 2 * self.MARGIN, self.PAGE_H - 40,
                QgsUnitTypes.LayoutMillimeters
            ))
            map_item.attemptMove(QgsLayoutPoint(
                self.MARGIN, 18, QgsUnitTypes.LayoutMillimeters
            ), page=page_idx
            )
            map_item.setFrameEnabled(True)
            map_item.setFrameStrokeColor(QColor("#2c3e50"))
            map_item.setMapRotation(0)

            # Set map extent from canvas
            map_item.setExtent(self.iface.mapCanvas().extent())
            map_item.setScale(self.iface.mapCanvas().scale())

            self.layout.addLayoutItem(map_item)
        except Exception:
            # Fallback: label if map can't be added
            self._add_label(
                "[Map view — open the site in QGIS and re-generate to capture map]",
                self.MARGIN, 50, self.PAGE_W - 2 * self.MARGIN, 20,
                page_idx, font_size=10, color=QColor("#888"), alignment=Qt.AlignCenter,
            )

        # Map legend text
        self._add_label(
            "Map shows current QGIS canvas extent. Constraint layers visible in QGIS "
            "project are rendered in the map above.",
            self.MARGIN, self.PAGE_H - 18, self.PAGE_W - 2 * self.MARGIN, 6,
            page_idx, font_size=7, color=QColor("#555"),
        )
        self._add_label(
            "Page 3 of 4 — Fatal Flaw Geospatial Risk Assessment Platform v1.0",
            self.MARGIN, self.PAGE_H - 10, self.PAGE_W - 2 * self.MARGIN, 6,
            page_idx, font_size=7, color=QColor("#999"), alignment=Qt.AlignCenter,
        )

    # ── Page 4: Complete Results Table ───────────────────────────────────────

    def _build_page_4(self):
        page_idx = 3
        all_results = self.result.get("all_layer_results", [])

        self._add_rect(0, 0, self.PAGE_W, 14, QColor("#2c3e50"), page_idx)
        self._add_label(
            "COMPLETE LAYER RESULTS — ALL 15 CONSTRAINT LAYERS", 5, 2, self.PAGE_W - 10, 10,
            page_idx, font_size=11, bold=True, color=QColor("white"), alignment=Qt.AlignCenter,
        )

        cols = ["Layer", "Category", "Type", "Intersects", "Area (ac)", "% Site",
                "Distance (m)", "Score", "Wt", "Fatal?"]
        col_widths = [48, 24, 22, 20, 22, 16, 26, 20, 14, 18]
        table_x = self.MARGIN
        table_y = 18

        # Header
        x = table_x
        for col, w in zip(cols, col_widths):
            self._add_rect(x, table_y, w, 7, QColor("#34495e"), page_idx)
            self._add_label(col, x + 0.5, table_y + 0.5, w - 1, 5.5, page_idx,
                            font_size=5.5, bold=True, color=QColor("white"))
            x += w

        for i, lr in enumerate(all_results):
            row_y = table_y + 7 + i * 7.5
            bg = QColor("#f8f9fa") if i % 2 == 0 else QColor("white")
            if lr.get("fatal_triggered"):
                bg = QColor("#ffebee")

            dist = lr.get("min_distance_meters")
            row_vals = [
                lr.get("layer_name", ""),
                lr.get("category", ""),
                lr.get("analysis_type", ""),
                "YES" if lr.get("intersects") else "no",
                f"{lr.get('intersection_area_acres', 0):.2f}",
                f"{lr.get('percentage_of_site', 0):.1f}%",
                f"{dist:.0f}" if dist is not None else "—",
                f"{lr.get('contribution_score', 0):.1f}",
                f"{lr.get('weight', 0):.2f}",
                "⛔" if lr.get("fatal_triggered") else ("!" if lr.get("is_fatal") else ""),
            ]
            x = table_x
            for val, w in zip(row_vals, col_widths):
                self._add_rect(x, row_y, w, 7, bg, page_idx)
                text_color = QColor("#c0392b") if lr.get("fatal_triggered") else QColor("#333")
                self._add_label(str(val), x + 0.5, row_y + 0.5, w - 1, 6, page_idx,
                                font_size=5.5, color=text_color)
                x += w

        self._add_label(
            "⛔ = fatal constraint triggered  |  ! = layer is fatal if intersected  "
            "|  Score = contribution to overall risk (0–100 scale)",
            self.MARGIN, self.PAGE_H - 18, self.PAGE_W - 2 * self.MARGIN, 6,
            page_idx, font_size=6.5, color=QColor("#555"),
        )
        self._add_label(
            "Page 4 of 4 — Fatal Flaw Geospatial Risk Assessment Platform v1.0",
            self.MARGIN, self.PAGE_H - 10, self.PAGE_W - 2 * self.MARGIN, 6,
            page_idx, font_size=7, color=QColor("#999"), alignment=Qt.AlignCenter,
        )

    # ── Layout helpers ────────────────────────────────────────────────────────

    def _add_label(
        self, text: str, x: float, y: float, w: float, h: float,
        page: int, font_size: float = 9, bold: bool = False,
        color: QColor = None, alignment: Qt.AlignmentFlag = Qt.AlignLeft,
    ) -> QgsLayoutItemLabel:
        label = QgsLayoutItemLabel(self.layout)
        label.setText(text)
        font = QFont()
        font.setPointSizeF(font_size)
        font.setBold(bold)
        label.setFont(font)
        if color:
            label.setFontColor(color)
        label.setHAlign(alignment)
        label.setVAlign(Qt.AlignVCenter)
        label.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
        label.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters), page=page)
        self.layout.addLayoutItem(label)
        return label

    def _add_rect(
        self, x: float, y: float, w: float, h: float,
        fill_color: QColor, page: int,
        stroke_color: QColor = None,
    ) -> QgsLayoutItemShape:
        shape = QgsLayoutItemShape(self.layout)
        shape.setShapeType(QgsLayoutItemShape.Rectangle)
        shape.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
        shape.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters), page=page)
        shape.setBackgroundColor(fill_color)
        shape.setFrameEnabled(stroke_color is not None)
        if stroke_color:
            shape.setFrameStrokeColor(stroke_color)
        else:
            shape.setFrameEnabled(False)
        self.layout.addLayoutItem(shape)
        return shape

    @staticmethod
    def _score_to_level(score: float, fatal: bool) -> str:
        if fatal:
            return "fatal"
        if score <= 25:
            return "low"
        if score <= 50:
            return "medium"
        if score <= 75:
            return "high"
        return "fatal"
