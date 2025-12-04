"""
Industry Deep Scan Engine
=========================

AI-powered industry signal scanner for MCA lead generation.
Detects funding triggers from multiple sources in real-time.

Key Features:
- Multi-source scraping (news, reviews, LinkedIn, BBB, liens, permits, business listings)
- LLM-powered signal classification (cash squeeze, rapid growth, distress indicators)
- Real-time alerts and notifications
- CRM-ready lead export
- REST API for integration

Usage:
    from industry_deep_scan import DeepScanEngine

    engine = DeepScanEngine()
    await engine.run_full_scan()
"""

__version__ = "1.0.0"
__author__ = "TCG Brokerage"

from industry_deep_scan.engine import DeepScanEngine
from industry_deep_scan.models import Business, Signal, SignalType, SignalPriority

__all__ = [
    "DeepScanEngine",
    "Business",
    "Signal",
    "SignalType",
    "SignalPriority",
]
