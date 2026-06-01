"""
fatal_flaw_analyzer/report_generator.py
Professional PDF report generator using Qt painting directly.
Bypasses QgsLayout entirely to avoid QGIS version compatibility issues.
Generates a clean 4-page A4 landscape report.
"""

from __future__ import annotations

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from qgis.PyQt.QtCore import Qt, QRectF, QPointF, QSizeF
from qgis.PyQt.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPen, QBrush,
    QLinearGradient, QPageSize, QPdfWriter, QPageLayout
)
from qgis.PyQt.QtWidgets import QApplication
from qgis.PyQt.QtCore import QMarginsF, QSizeF as QtSizeF


# ── Colour palette ────────────────────────────────────────────────────────────
C_DARK       = QColor("#1a2332")
C_HEADER     = QColor("#2c3e50")
C_ACCENT     = QColor("#2980b9")
C_LOW        = QColor("#27ae60")
C_MEDIUM     = QColor("#f39c12")
C_HIGH       = QColor("#e67e22")
C_FATAL      = QColor("#c0392b")
C_FATAL_LIGHT= QColor("#fadbd8")
C_ROW_ALT    = QColor("#f4f6f8")
C_ROW_NORM   = QColor("#ffffff")
C_BORDER     = QColor("#dce1e7")
C_TEXT_DARK  = QColor("#2c3e50")
C_TEXT_MID   = QColor("#555555")
C_TEXT_LIGHT = QColor("#888888")
C_WHITE      = QColor("#ffffff")
C_BG         = QColor("#f8f9fa")


def _risk_color(score: float, fatal: bool) -> QColor:
    if fatal:            return C_FATAL
    if score <= 25:      return C_LOW
    if score <= 50:      return C_MEDIUM
    if score <= 75:      return C_HIGH
    return C_FATAL


def _risk_label(score: float, fatal: bool) -> str:
    if fatal:            return "FATAL FLAW"
    if score <= 25:      return "LOW RISK"
    if score <= 50:      return "MODERATE RISK"
    if score <= 75:      return "HIGH RISK"
    return "VERY HIGH RISK"


class ReportGenerator:
    """
    Generates a 4-page professional PDF report using QPdfWriter + QPainter.
    No dependency on QgsLayout — works on all QGIS 3.x versions.
    """

    # A4 landscape in points (1 pt = 1/72 inch)
    PW = 841.89   # ~297mm
    PH = 595.28   # ~210mm
    M  = 36       # margin
    CW = 841.89 - 72   # content width

    def __init__(self, iface, result: dict, site_layer=None):
        self.iface  = iface
        self.R      = result
        self.layer  = site_layer
        self.score  = result.get("overall_risk_score", 0)
        self.fatal  = result.get("fatal_flag", False)
        self.color  = _risk_color(self.score, self.fatal)
        self.label  = _risk_label(self.score, self.fatal)

    # ── Public entry point ────────────────────────────────────────────────────

    def generate_pdf(self, output_path: str) -> None:
        writer = QPdfWriter(output_path)
        writer.setPageSize(QPageSize(QPageSize.A4))
        writer.setPageOrientation(QPageLayout.Landscape)
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        writer.setResolution(150)

        p = QPainter(writer)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        # Scale: map pt coordinates to device pixels
        # A4 landscape = 297x210mm; at 150dpi device size varies
        # We work in our own "point" space and let Qt scale
        dw = writer.width()
        dh = writer.height()
        sx = dw / self.PW
        sy = dh / self.PH
        p.scale(sx, sy)

        self._page1(p)
        writer.newPage()
        self._page2(p)
        writer.newPage()
        self._page3(p)
        writer.newPage()
        self._page4(p)

        p.end()

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE 1 — Executive Summary
    # ══════════════════════════════════════════════════════════════════════════

    def _page1(self, p: QPainter):
        R = self.R
        # Background
        self._fill_rect(p, 0, 0, self.PW, self.PH, C_BG)

        # ── Top gradient header bar ───────────────────────────────────────────
        grad = QLinearGradient(0, 0, self.PW, 0)
        grad.setColorAt(0, C_DARK)
        grad.setColorAt(1, C_ACCENT)
        p.fillRect(QRectF(0, 0, self.PW, 58), grad)

        # Platform name
        self._text(p, "FATAL FLAW GEOSPATIAL RISK ASSESSMENT",
                   self.M, 10, self.CW, 20,
                   C_WHITE, 14, bold=True, align=Qt.AlignLeft | Qt.AlignVCenter)
        self._text(p, "Renewable Energy Site Suitability Report",
                   self.M, 30, self.CW, 16,
                   QColor("#aed6f1"), 9, align=Qt.AlignLeft | Qt.AlignVCenter)

        # Date top right
        date_str = datetime.now().strftime("%B %d, %Y  %H:%M UTC")
        self._text(p, date_str, 0, 10, self.PW - self.M, 16,
                   QColor("#aed6f1"), 8, align=Qt.AlignRight | Qt.AlignVCenter)

        # ── Score card (left column) ──────────────────────────────────────────
        card_x, card_y, card_w, card_h = self.M, 72, 200, 180
        self._rounded_rect(p, card_x, card_y, card_w, card_h, C_WHITE, 8, C_BORDER)

        # Colour strip at top of card
        self._fill_rounded_top(p, card_x, card_y, card_w, 6, self.color)

        # Score number
        self._text(p, f"{self.score:.1f}", card_x, card_y + 14,
                   card_w, 60, self.color, 48, bold=True, align=Qt.AlignCenter)

        # /100
        self._text(p, "out of 100", card_x, card_y + 68,
                   card_w, 14, C_TEXT_LIGHT, 8, align=Qt.AlignCenter)

        # Risk badge
        badge_y = card_y + 88
        self._fill_rect(p, card_x + 20, badge_y, card_w - 40, 22, self.color)
        self._text(p, self.label, card_x + 20, badge_y,
                   card_w - 40, 22, C_WHITE, 9, bold=True, align=Qt.AlignCenter)

        # Fatal indicator
        fatal_y = badge_y + 30
        if self.fatal:
            self._fill_rect(p, card_x + 10, fatal_y, card_w - 20, 20, C_FATAL_LIGHT)
            self._text(p, "⚠  FATAL CONSTRAINT DETECTED",
                       card_x + 10, fatal_y, card_w - 20, 20,
                       C_FATAL, 7, bold=True, align=Qt.AlignCenter)
            # Fatal layers
            fl = ", ".join(R.get("fatal_layers", []))
            self._text(p, fl, card_x + 10, fatal_y + 18, card_w - 20, 14,
                       C_FATAL, 6, align=Qt.AlignCenter)
        else:
            self._fill_rect(p, card_x + 10, fatal_y, card_w - 20, 20,
                            QColor("#d5f5e3"))
            self._text(p, "✓  No Fatal Constraints Found",
                       card_x + 10, fatal_y, card_w - 20, 20,
                       C_LOW, 7, bold=True, align=Qt.AlignCenter)

        # Processing time
        self._text(p, f"Analyzed in {R.get('processing_time_ms', 0)}ms",
                   card_x, card_y + card_h - 16, card_w, 12,
                   C_TEXT_LIGHT, 7, align=Qt.AlignCenter)

        # ── Site metadata (right of score card) ──────────────────────────────
        meta_x = card_x + card_w + 24
        meta_y = card_y
        meta_w = self.PW - meta_x - self.M

        self._rounded_rect(p, meta_x, meta_y, meta_w, card_h, C_WHITE, 8, C_BORDER)
        self._fill_rounded_top(p, meta_x, meta_y, meta_w, 6, C_ACCENT)

        self._text(p, "SITE INFORMATION", meta_x + 12, meta_y + 10,
                   meta_w - 24, 16, C_ACCENT, 8, bold=True)

        fields = [
            ("Site Name",        R.get("site_name", "—")),
            ("Site Type",        R.get("site_type", "—").upper()),
            ("Site Area",        f"{R.get('site_area_acres', 0):,.1f} acres"),
            ("Assessment ID",    str(R.get("assessment_id", "—"))[:24]),
            ("Assessment Date",  R.get("assessment_timestamp", "—")[:10]),
            ("Overall Score",    f"{self.score:.1f} / 100  ({self.label})"),
            ("Fatal Flag",       "YES — See fatal layers below" if self.fatal else "NO"),
        ]
        row_h = 18
        for i, (label, value) in enumerate(fields):
            ry = meta_y + 30 + i * row_h
            bg = C_ROW_ALT if i % 2 == 0 else C_ROW_NORM
            self._fill_rect(p, meta_x + 8, ry, meta_w - 16, row_h - 2, bg)
            self._text(p, label, meta_x + 12, ry, 110, row_h - 2,
                       C_TEXT_MID, 7, bold=True)
            color = C_FATAL if (label == "Fatal Flag" and self.fatal) else C_TEXT_DARK
            self._text(p, value, meta_x + 126, ry, meta_w - 140, row_h - 2,
                       color, 7)

        # ── Risk scale legend ─────────────────────────────────────────────────
        leg_y = card_y + card_h + 16
        self._text(p, "RISK SCALE REFERENCE", self.M, leg_y,
                   200, 12, C_TEXT_MID, 7, bold=True)
        leg_y += 14
        levels = [
            ("LOW  0–25",      C_LOW),
            ("MODERATE  26–50", C_MEDIUM),
            ("HIGH  51–75",    C_HIGH),
            ("FATAL  76–100",  C_FATAL),
        ]
        seg_w = (self.CW) / len(levels)
        for i, (lbl, col) in enumerate(levels):
            lx = self.M + i * seg_w
            self._fill_rect(p, lx, leg_y, seg_w - 4, 18, col)
            self._text(p, lbl, lx, leg_y, seg_w - 4, 18,
                       C_WHITE, 7, bold=True, align=Qt.AlignCenter)

        # ── Footer ────────────────────────────────────────────────────────────
        self._footer(p, 1)

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE 2 — Top Constraints Analysis
    # ══════════════════════════════════════════════════════════════════════════

    def _page2(self, p: QPainter):
        self._fill_rect(p, 0, 0, self.PW, self.PH, C_BG)
        self._page_header(p, "TOP CONSTRAINT ANALYSIS",
                          "Layers contributing most to the overall risk score")

        top = self.R.get("top_risks", [])
        if not top:
            self._text(p, "No constraint intersections detected for this site.",
                       self.M, 120, self.CW, 20, C_TEXT_MID, 11,
                       align=Qt.AlignCenter)
            self._footer(p, 2)
            return

        # ── Bar chart ─────────────────────────────────────────────────────────
        chart_x = self.M
        chart_y = 80
        chart_h = 160
        bar_area_w = 420
        max_score = max((r.get("contribution_score", 0) for r in top), default=1)

        self._rounded_rect(p, chart_x, chart_y,
                           bar_area_w + 160, chart_h + 20, C_WHITE, 6, C_BORDER)
        self._text(p, "CONTRIBUTION SCORES",
                   chart_x + 10, chart_y + 6, 200, 12,
                   C_ACCENT, 7, bold=True)

        bar_h = 22
        gap = 8
        for i, risk in enumerate(top[:5]):
            s = risk.get("contribution_score", 0)
            by = chart_y + 22 + i * (bar_h + gap)
            bw = max(4, (s / max(max_score, 1)) * bar_area_w)
            col = _risk_color(s * 2, risk.get("is_fatal", False))

            # Layer name
            self._text(p, risk.get("layer_name", ""), chart_x + 8, by,
                       130, bar_h, C_TEXT_DARK, 7, bold=True)

            # Bar
            bx = chart_x + 142
            self._fill_rect(p, bx, by + 4, bw, bar_h - 8, col)

            # Score label
            self._text(p, f"{s:.1f}",
                       bx + bw + 6, by, 40, bar_h,
                       col, 8, bold=True)

            # Fatal badge
            if risk.get("is_fatal"):
                self._fill_rect(p, bx + bw + 46, by + 4, 40, bar_h - 8,
                                C_FATAL_LIGHT)
                self._text(p, "FATAL", bx + bw + 46, by + 4, 40, bar_h - 8,
                           C_FATAL, 6, bold=True, align=Qt.AlignCenter)

        # ── Detail table ──────────────────────────────────────────────────────
        tbl_y = chart_y + chart_h + 30
        cols = ["Constraint Layer", "Category", "Analysis Type",
                "Overlap Area (ac)", "% of Site", "Score", "Weight", "Fatal?"]
        widths = [140, 80, 80, 90, 70, 60, 55, 50]

        # Header
        tx = self.M
        self._fill_rect(p, tx, tbl_y, sum(widths), 20, C_HEADER)
        for col, w in zip(cols, widths):
            self._text(p, col, tx + 4, tbl_y, w - 6, 20,
                       C_WHITE, 6, bold=True)
            tx += w

        for i, risk in enumerate(top):
            ry = tbl_y + 20 + i * 20
            bg = C_FATAL_LIGHT if risk.get("is_fatal") else \
                 (C_ROW_ALT if i % 2 == 0 else C_ROW_NORM)
            self._fill_rect(p, self.M, ry, sum(widths), 19, bg)
            # border
            p.setPen(QPen(C_BORDER, 0.5))
            p.drawLine(QPointF(self.M, ry + 19),
                       QPointF(self.M + sum(widths), ry + 19))
            p.setPen(Qt.NoPen)

            vals = [
                risk.get("layer_name", ""),
                risk.get("category", ""),
                risk.get("analysis_type", ""),
                f"{risk.get('impact_area_acres', 0):.2f}",
                f"{risk.get('percentage_of_site', 0):.1f}%",
                f"{risk.get('contribution_score', 0):.1f}",
                f"{risk.get('weight', 0):.2f}",
                "⛔ YES" if risk.get("is_fatal") else "No",
            ]
            tx = self.M
            for val, w in zip(vals, widths):
                col = C_FATAL if (val.startswith("⛔")) else C_TEXT_DARK
                self._text(p, val, tx + 4, ry, w - 6, 19, col, 6)
                tx += w

        self._footer(p, 2)

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE 3 — Map placeholder + site summary
    # ══════════════════════════════════════════════════════════════════════════

    def _page3(self, p: QPainter):
        self._fill_rect(p, 0, 0, self.PW, self.PH, C_BG)
        self._page_header(p, "SITE LOCATION & CONTEXT",
                          "Geographic context and constraint summary")

        # Map frame
        map_x, map_y = self.M, 80
        map_w, map_h  = 460, 360

        self._rounded_rect(p, map_x, map_y, map_w, map_h, C_WHITE, 6, C_BORDER)

        # Try to render QGIS canvas into the map frame
        canvas_rendered = False
        try:
            if self.iface and self.iface.mapCanvas():
                from qgis.PyQt.QtGui import QPixmap
                canvas = self.iface.mapCanvas()
                pixmap = QPixmap(int(map_w - 4), int(map_h - 4))
                canvas.render(pixmap)
                p.drawPixmap(
                    QRectF(map_x + 2, map_y + 2, map_w - 4, map_h - 4),
                    pixmap,
                    QRectF(0, 0, pixmap.width(), pixmap.height())
                )
                canvas_rendered = True
        except Exception:
            pass

        if not canvas_rendered:
            # Placeholder grid
            self._fill_rect(p, map_x + 2, map_y + 2, map_w - 4, map_h - 4,
                            QColor("#eaf2fb"))
            p.setPen(QPen(QColor("#d5e8f3"), 1, Qt.DotLine))
            for gx in range(int(map_x), int(map_x + map_w), 40):
                p.drawLine(QPointF(gx, map_y), QPointF(gx, map_y + map_h))
            for gy in range(int(map_y), int(map_y + map_h), 40):
                p.drawLine(QPointF(map_x, gy), QPointF(map_x + map_w, gy))
            p.setPen(Qt.NoPen)
            self._text(p, "🗺  Map View",
                       map_x, map_y + map_h / 2 - 20, map_w, 20,
                       C_ACCENT, 14, bold=True, align=Qt.AlignCenter)
            self._text(p,
                       "Open site in QGIS and re-generate\nreport to capture map view",
                       map_x, map_y + map_h / 2 + 10, map_w, 30,
                       C_TEXT_LIGHT, 8, align=Qt.AlignCenter)

        # Map caption
        self._text(p, "Figure 1 — Site location. Constraint layers visible in QGIS "
                   "are rendered above.",
                   map_x, map_y + map_h + 4, map_w, 12,
                   C_TEXT_LIGHT, 6, align=Qt.AlignCenter)

        # ── Info panel right of map ───────────────────────────────────────────
        info_x = map_x + map_w + 20
        info_w = self.PW - info_x - self.M
        info_y = map_y

        # Score summary box
        self._rounded_rect(p, info_x, info_y, info_w, 90, C_WHITE, 6, C_BORDER)
        self._fill_rounded_top(p, info_x, info_y, info_w, 5, self.color)
        self._text(p, f"{self.score:.1f}", info_x, info_y + 8,
                   info_w, 42, self.color, 36, bold=True, align=Qt.AlignCenter)
        self._text(p, self.label, info_x, info_y + 52,
                   info_w, 14, self.color, 7, bold=True, align=Qt.AlignCenter)
        self._text(p, f"{self.R.get('site_area_acres', 0):,.0f} acres",
                   info_x, info_y + 68, info_w, 14,
                   C_TEXT_MID, 7, align=Qt.AlignCenter)

        # Layer count summary
        results = self.R.get("all_layer_results", [])
        n_hit    = sum(1 for r in results if r.get("intersects"))
        n_fatal  = sum(1 for r in results if r.get("fatal_triggered"))
        n_clean  = len(results) - n_hit

        summary_items = [
            ("Total Layers Checked", str(len(results)), C_ACCENT),
            ("Layers Intersecting",  str(n_hit),        C_HIGH),
            ("Fatal Triggers",       str(n_fatal),      C_FATAL if n_fatal else C_LOW),
            ("Clear Layers",         str(n_clean),      C_LOW),
        ]
        sy = info_y + 100
        for label, val, col in summary_items:
            self._rounded_rect(p, info_x, sy, info_w, 32, C_WHITE, 4, C_BORDER)
            self._fill_rect(p, info_x, sy, 5, 32, col)
            self._text(p, label, info_x + 12, sy, info_w - 60, 32,
                       C_TEXT_MID, 7)
            self._text(p, val, info_x, sy, info_w - 8, 32,
                       col, 14, bold=True, align=Qt.AlignRight | Qt.AlignVCenter)
            sy += 40

        self._footer(p, 3)

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE 4 — Complete Results Table
    # ══════════════════════════════════════════════════════════════════════════

    def _page4(self, p: QPainter):
        self._fill_rect(p, 0, 0, self.PW, self.PH, C_BG)
        self._page_header(p, "COMPLETE LAYER RESULTS",
                          "All 15 constraint layers — detailed breakdown")

        results = self.R.get("all_layer_results", [])
        cols   = ["Layer", "Category", "Type", "Intersects",
                  "Area (ac)", "% Site", "Dist (m)", "Score", "Wt", "Fatal"]
        widths = [120, 78, 62, 56, 62, 50, 58, 50, 36, 46]

        tbl_y = 80
        row_h = 17

        # Header
        tx = self.M
        self._fill_rect(p, tx, tbl_y, sum(widths), 22, C_DARK)
        for col, w in zip(cols, widths):
            self._text(p, col, tx + 4, tbl_y, w - 6, 22,
                       C_WHITE, 6, bold=True)
            tx += w

        for i, lr in enumerate(results):
            ry = tbl_y + 22 + i * row_h
            is_fatal_hit = lr.get("fatal_triggered", False)
            intersects   = lr.get("intersects", False)

            if is_fatal_hit:
                bg = C_FATAL_LIGHT
            elif intersects:
                bg = QColor("#fef9e7")
            else:
                bg = C_ROW_ALT if i % 2 == 0 else C_ROW_NORM

            self._fill_rect(p, self.M, ry, sum(widths), row_h - 1, bg)

            # Left accent stripe for fatal rows
            if is_fatal_hit:
                self._fill_rect(p, self.M, ry, 3, row_h - 1, C_FATAL)

            # Row border
            p.setPen(QPen(C_BORDER, 0.4))
            p.drawLine(QPointF(self.M, ry + row_h - 1),
                       QPointF(self.M + sum(widths), ry + row_h - 1))
            p.setPen(Qt.NoPen)

            dist = lr.get("min_distance_meters")
            score_val = lr.get("contribution_score", 0)
            vals = [
                lr.get("layer_name", ""),
                lr.get("category", ""),
                lr.get("analysis_type", ""),
                "YES" if intersects else "—",
                f"{lr.get('intersection_area_acres', 0):.2f}" if intersects else "—",
                f"{lr.get('percentage_of_site', 0):.1f}%" if intersects else "—",
                f"{dist:.0f}" if dist is not None else "—",
                f"{score_val:.1f}",
                f"{lr.get('weight', 0):.2f}",
                "⛔ FATAL" if is_fatal_hit else
                ("!" if lr.get("is_fatal") else "✓"),
            ]
            tx = self.M
            for j, (val, w) in enumerate(zip(vals, widths)):
                if j == 9:   # Fatal column
                    col = C_FATAL if is_fatal_hit else \
                          (C_HIGH if val == "!" else C_LOW)
                elif j == 7 and score_val > 0:  # Score column
                    col = _risk_color(score_val * 2, False)
                elif j == 3 and intersects:
                    col = C_HIGH
                else:
                    col = C_TEXT_DARK
                self._text(p, val, tx + 4, ry, w - 6, row_h - 1, col, 6)
                tx += w

        # Legend
        leg_y = tbl_y + 22 + len(results) * row_h + 10
        legend_text = (
            "⛔ FATAL = fatal constraint triggered  |  "
            "! = layer is fatal if intersected  |  "
            "✓ = no issue  |  "
            "Score = contribution to overall risk (0–100 scale)"
        )
        self._text(p, legend_text, self.M, leg_y, self.CW, 12,
                   C_TEXT_LIGHT, 6)

        self._footer(p, 4)

    # ══════════════════════════════════════════════════════════════════════════
    # Drawing helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _fill_rect(self, p, x, y, w, h, color):
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawRect(QRectF(x, y, w, h))

    def _rounded_rect(self, p, x, y, w, h, fill, radius=6, border_color=None):
        p.setPen(QPen(border_color, 0.8) if border_color else Qt.NoPen)
        p.setBrush(QBrush(fill))
        p.drawRoundedRect(QRectF(x, y, w, h), radius, radius)

    def _fill_rounded_top(self, p, x, y, w, h, color):
        """Fill just the top portion with rounded top corners."""
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawRoundedRect(QRectF(x, y, w, h * 2), h, h)
        p.drawRect(QRectF(x, y + h, w, h))

    def _text(self, p, text, x, y, w, h, color, size,
              bold=False, align=Qt.AlignLeft | Qt.AlignVCenter):
        font = QFont("Arial", size)
        font.setBold(bold)
        p.setFont(font)
        p.setPen(QPen(color))
        p.drawText(QRectF(x, y, w, h), align, str(text))

    def _page_header(self, p, title, subtitle=""):
        grad = QLinearGradient(0, 0, self.PW, 0)
        grad.setColorAt(0, C_DARK)
        grad.setColorAt(1, C_ACCENT)
        p.fillRect(QRectF(0, 0, self.PW, 52), grad)
        self._text(p, title, self.M, 8, self.CW, 22,
                   C_WHITE, 13, bold=True)
        if subtitle:
            self._text(p, subtitle, self.M, 30, self.CW, 14,
                       QColor("#aed6f1"), 8)

    def _footer(self, p, page_num):
        fy = self.PH - 22
        self._fill_rect(p, 0, fy, self.PW, 22, C_DARK)
        self._text(p,
                   "Fatal Flaw Geospatial Risk Assessment Platform  |  "
                   "Confidential — For Internal Use Only  |  "
                   f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                   self.M, fy, self.CW - 60, 22,
                   QColor("#aed6f1"), 6,
                   align=Qt.AlignLeft | Qt.AlignVCenter)
        self._text(p, f"Page {page_num} of 4",
                   0, fy, self.PW - self.M, 22,
                   QColor("#aed6f1"), 7, bold=True,
                   align=Qt.AlignRight | Qt.AlignVCenter)