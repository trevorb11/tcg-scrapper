"""
REST API
========

FastAPI-based REST API for accessing leads and managing scans.
"""

from industry_deep_scan.api.main import app, create_app

__all__ = ["app", "create_app"]
