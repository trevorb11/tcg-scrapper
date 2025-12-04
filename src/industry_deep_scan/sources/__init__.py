"""
Data Source Connectors
======================

Pluggable connectors for various data sources.
Each source implements the BaseSource interface.
"""

from industry_deep_scan.sources.base import BaseSource, RawSignal
from industry_deep_scan.sources.news import GoogleNewsSource, LocalNewsSource
from industry_deep_scan.sources.reviews import YelpSource, GoogleReviewsSource
from industry_deep_scan.sources.linkedin import LinkedInSource
from industry_deep_scan.sources.bbb import BBBSource
from industry_deep_scan.sources.listings import BizBuySellSource, BusinessBrokerSource
from industry_deep_scan.sources.court_records import CourtRecordsSource, UCCFilingsSource
from industry_deep_scan.sources.permits import EquipmentPermitSource, SOSFilingsSource

__all__ = [
    "BaseSource",
    "RawSignal",
    "GoogleNewsSource",
    "LocalNewsSource",
    "YelpSource",
    "GoogleReviewsSource",
    "LinkedInSource",
    "BBBSource",
    "BizBuySellSource",
    "BusinessBrokerSource",
    "CourtRecordsSource",
    "UCCFilingsSource",
    "EquipmentPermitSource",
    "SOSFilingsSource",
]
