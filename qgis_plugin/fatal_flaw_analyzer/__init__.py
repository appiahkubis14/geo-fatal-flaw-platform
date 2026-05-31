"""
fatal_flaw_analyzer/__init__.py
QGIS plugin entry point — required by QGIS plugin loader.
"""


def classFactory(iface):
    """Load FatalFlawAnalyzer plugin."""
    from .fatal_flaw_analyzer import FatalFlawAnalyzer
    return FatalFlawAnalyzer(iface)
