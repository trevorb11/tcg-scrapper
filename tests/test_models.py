"""
Model Tests
===========

Tests for data models and database operations.
"""

import pytest
from datetime import datetime

from industry_deep_scan.models import (
    Business,
    Signal,
    SignalType,
    SignalCategory,
    SignalPriority,
    SourceType,
    LeadStatus,
)


class TestBusinessModel:
    """Tests for Business model."""

    def test_create_business(self):
        """Test creating a business entity."""
        business = Business(
            name="Test Company LLC",
            city="Los Angeles",
            state="CA",
            industry="Construction",
        )

        assert business.name == "Test Company LLC"
        assert business.city == "Los Angeles"
        assert business.state == "CA"
        assert business.industry == "Construction"
        assert business.status == LeadStatus.NEW
        assert business.lead_score == 0.0

    def test_business_defaults(self):
        """Test default values."""
        business = Business(name="Test")

        assert business.priority == SignalPriority.LOW
        assert business.is_verified is False
        assert business.is_blacklisted is False


class TestSignalModel:
    """Tests for Signal model."""

    def test_create_signal(self):
        """Test creating a signal."""
        signal = Signal(
            business_id="test-123",
            signal_type=SignalType.CASH_SQUEEZE,
            category=SignalCategory.CASH_FLOW_STRESS,
            priority=SignalPriority.HIGH,
            title="Test Signal",
            source_type=SourceType.NEWS,
        )

        assert signal.signal_type == SignalType.CASH_SQUEEZE
        assert signal.category == SignalCategory.CASH_FLOW_STRESS
        assert signal.priority == SignalPriority.HIGH

    def test_signal_types(self):
        """Test all signal types are accessible."""
        assert len(SignalType) > 10
        assert SignalType.CASH_SQUEEZE in SignalType
        assert SignalType.RAPID_GROWTH in SignalType
        assert SignalType.TAX_LIEN in SignalType


class TestEnums:
    """Tests for enum values."""

    def test_signal_priority_ordering(self):
        """Test priority enum values."""
        priorities = [
            SignalPriority.CRITICAL,
            SignalPriority.HIGH,
            SignalPriority.MEDIUM,
            SignalPriority.LOW,
            SignalPriority.INFORMATIONAL,
        ]

        assert len(priorities) == 5

    def test_source_types(self):
        """Test source type coverage."""
        sources = [
            SourceType.NEWS,
            SourceType.YELP,
            SourceType.LINKEDIN,
            SourceType.BBB,
            SourceType.COURT_RECORDS,
            SourceType.EQUIPMENT_PERMITS,
            SourceType.BUSINESS_LISTINGS,
        ]

        for source in sources:
            assert source in SourceType

    def test_lead_status_workflow(self):
        """Test lead status values for workflow."""
        workflow = [
            LeadStatus.NEW,
            LeadStatus.CONTACTED,
            LeadStatus.QUALIFIED,
            LeadStatus.PROPOSAL_SENT,
            LeadStatus.FUNDED,
        ]

        for status in workflow:
            assert status in LeadStatus
