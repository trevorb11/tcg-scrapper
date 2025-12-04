"""
REST API
========

FastAPI-based REST API for accessing leads and managing scans.
"""

from industry_deep_scan.api.main import app, create_app
from industry_deep_scan.api.routes import leads, signals, scans, analytics

__all__ = ["app", "create_app"]
