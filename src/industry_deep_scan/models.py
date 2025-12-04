"""
Data Models
===========

SQLAlchemy models for businesses, signals, and leads.
Designed for comprehensive lead tracking and signal management.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all models."""

    pass


class SignalType(str, Enum):
    """Types of funding signals detected."""

    # Cash Flow Stress Indicators
    CASH_SQUEEZE = "cash_squeeze"
    PAYMENT_DELAY = "payment_delay"
    VENDOR_DISPUTE = "vendor_dispute"
    TAX_LIEN = "tax_lien"
    JUDGMENT = "judgment"

    # Growth Indicators
    RAPID_GROWTH = "rapid_growth"
    NEW_CONTRACT = "new_contract"
    EXPANSION = "expansion"
    HIRING_SURGE = "hiring_surge"
    NEW_LOCATION = "new_location"

    # Distress Indicators
    LAYOFFS = "layoffs"
    REVIEW_DECLINE = "review_decline"
    BBB_COMPLAINT = "bbb_complaint"
    OWNER_CHANGE = "owner_change"

    # Opportunity Indicators
    EQUIPMENT_PURCHASE = "equipment_purchase"
    SEASONAL_RAMP = "seasonal_ramp"
    INVENTORY_NEED = "inventory_need"
    BUSINESS_FOR_SALE = "business_for_sale"

    # General
    NEWS_MENTION = "news_mention"
    PERMIT_FILED = "permit_filed"
    UCC_FILING = "ucc_filing"


class SignalPriority(str, Enum):
    """Priority classification for signals."""

    CRITICAL = "critical"  # Score 9-10: Call immediately
    HIGH = "high"  # Score 7-8: Call within 24 hours
    MEDIUM = "medium"  # Score 5-6: Add to queue
    LOW = "low"  # Score 3-4: Nurture list
    INFORMATIONAL = "informational"  # Score 1-2: Data enrichment


class SignalCategory(str, Enum):
    """High-level signal categories."""

    CASH_FLOW_STRESS = "cash_flow_stress"
    RAPID_GROWTH = "rapid_growth"
    DISTRESS_HIGH_REVENUE = "distress_high_revenue"
    EXPANSION_OPPORTUNITY = "expansion_opportunity"
    ACQUISITION_TARGET = "acquisition_target"


class SourceType(str, Enum):
    """Data source types."""

    NEWS = "news"
    YELP = "yelp"
    GOOGLE_REVIEWS = "google_reviews"
    LINKEDIN = "linkedin"
    BBB = "bbb"
    COURT_RECORDS = "court_records"
    EQUIPMENT_PERMITS = "equipment_permits"
    BUSINESS_LISTINGS = "business_listings"
    UCC_FILINGS = "ucc_filings"
    SOS_FILINGS = "sos_filings"
    MANUAL = "manual"


class LeadStatus(str, Enum):
    """Lead workflow status."""

    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    PROPOSAL_SENT = "proposal_sent"
    FUNDED = "funded"
    DECLINED = "declined"
    NOT_INTERESTED = "not_interested"
    DEAD = "dead"


class Business(Base):
    """
    Core business entity.
    Represents a potential MCA lead with all enrichment data.
    """

    __tablename__ = "businesses"

    # Primary identification
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Business identification
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    dba_name: Mapped[Optional[str]] = mapped_column(String(255))
    legal_name: Mapped[Optional[str]] = mapped_column(String(255))

    # Contact information
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    website: Mapped[Optional[str]] = mapped_column(String(500))

    # Location
    address: Mapped[Optional[str]] = mapped_column(String(500))
    city: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    state: Mapped[Optional[str]] = mapped_column(String(2), index=True)
    zip_code: Mapped[Optional[str]] = mapped_column(String(10))
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)

    # Business classification
    industry: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    naics_code: Mapped[Optional[str]] = mapped_column(String(10))
    sic_code: Mapped[Optional[str]] = mapped_column(String(10))
    business_type: Mapped[Optional[str]] = mapped_column(String(50))  # LLC, Corp, Sole Prop, etc.

    # Business details
    year_established: Mapped[Optional[int]] = mapped_column(Integer)
    employee_count: Mapped[Optional[int]] = mapped_column(Integer)
    annual_revenue_estimate: Mapped[Optional[float]] = mapped_column(Float)
    revenue_source: Mapped[Optional[str]] = mapped_column(String(100))  # Where estimate came from

    # Owner information
    owner_name: Mapped[Optional[str]] = mapped_column(String(255))
    owner_email: Mapped[Optional[str]] = mapped_column(String(255))
    owner_phone: Mapped[Optional[str]] = mapped_column(String(20))
    owner_linkedin: Mapped[Optional[str]] = mapped_column(String(500))

    # External IDs
    yelp_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    google_place_id: Mapped[Optional[str]] = mapped_column(String(100))
    linkedin_company_id: Mapped[Optional[str]] = mapped_column(String(100))
    bbb_id: Mapped[Optional[str]] = mapped_column(String(100))
    sos_entity_id: Mapped[Optional[str]] = mapped_column(String(100))

    # Review metrics
    yelp_rating: Mapped[Optional[float]] = mapped_column(Float)
    yelp_review_count: Mapped[Optional[int]] = mapped_column(Integer)
    google_rating: Mapped[Optional[float]] = mapped_column(Float)
    google_review_count: Mapped[Optional[int]] = mapped_column(Integer)
    bbb_rating: Mapped[Optional[str]] = mapped_column(String(5))
    bbb_complaint_count: Mapped[Optional[int]] = mapped_column(Integer)

    # Scoring
    lead_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    priority: Mapped[SignalPriority] = mapped_column(
        SQLEnum(SignalPriority), default=SignalPriority.LOW
    )
    category: Mapped[Optional[SignalCategory]] = mapped_column(SQLEnum(SignalCategory))

    # Lead management
    status: Mapped[LeadStatus] = mapped_column(SQLEnum(LeadStatus), default=LeadStatus.NEW)
    assigned_to: Mapped[Optional[str]] = mapped_column(String(100))
    last_contacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    next_follow_up: Mapped[Optional[datetime]] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Flags
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    blacklist_reason: Mapped[Optional[str]] = mapped_column(String(255))
    has_existing_mca: Mapped[Optional[bool]] = mapped_column(Boolean)
    last_contacted: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Relationships
    signals: Mapped[list["Signal"]] = relationship(
        "Signal", back_populates="business", cascade="all, delete-orphan"
    )
    contact_attempts: Mapped[list["ContactAttempt"]] = relationship(
        "ContactAttempt", back_populates="business", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("ix_business_location", "state", "city"),
        Index("ix_business_scoring", "lead_score", "priority"),
        Index("ix_business_status", "status", "next_follow_up"),
        Index("ix_business_hot_leads", "is_blacklisted", "priority", "lead_score"),
        Index("ix_business_industry_state", "industry", "state"),
        Index("ix_business_created", "created_at"),
        Index("ix_business_assigned", "assigned_to", "status"),
    )

    def __repr__(self) -> str:
        return f"<Business(id={self.id}, name={self.name}, score={self.lead_score})>"


class Signal(Base):
    """
    Detected funding signal.
    Each signal represents a specific trigger event that indicates funding potential.
    """

    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # Business relationship
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), index=True)
    business: Mapped["Business"] = relationship("Business", back_populates="signals")

    # Signal classification
    signal_type: Mapped[SignalType] = mapped_column(SQLEnum(SignalType), index=True)
    category: Mapped[SignalCategory] = mapped_column(SQLEnum(SignalCategory), index=True)
    priority: Mapped[SignalPriority] = mapped_column(SQLEnum(SignalPriority), index=True)

    # Signal details
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    raw_content: Mapped[Optional[str]] = mapped_column(Text)  # Original scraped content

    # Source tracking
    source_type: Mapped[SourceType] = mapped_column(SQLEnum(SourceType), index=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000))
    source_date: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Scoring
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1 from LLM
    signal_strength: Mapped[float] = mapped_column(Float, default=0.0)  # 1-10 scale
    urgency_score: Mapped[float] = mapped_column(Float, default=0.0)  # 1-10 scale

    # LLM analysis
    llm_analysis: Mapped[Optional[str]] = mapped_column(Text)  # Full LLM response
    funding_indicators: Mapped[Optional[str]] = mapped_column(Text)  # JSON list of indicators
    recommended_approach: Mapped[Optional[str]] = mapped_column(Text)  # LLM suggested pitch

    # Status
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    is_notified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Deduplication
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    __table_args__ = (
        Index("ix_signal_business_type", "business_id", "signal_type"),
        Index("ix_signal_priority_date", "priority", "created_at"),
        Index("ix_signal_source_date", "source_type", "created_at"),
        Index("ix_signal_category", "category", "priority"),
        Index("ix_signal_notified", "is_notified", "priority"),
        UniqueConstraint("business_id", "content_hash", name="uq_signal_content"),
    )

    def __repr__(self) -> str:
        return f"<Signal(id={self.id}, type={self.signal_type}, priority={self.priority})>"


class ContactAttempt(Base):
    """
    Record of outreach attempts for a business.
    Tracks call/email history for follow-up management.
    """

    __tablename__ = "contact_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Business relationship
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), index=True)
    business: Mapped["Business"] = relationship("Business", back_populates="contact_attempts")

    # Contact details
    contact_method: Mapped[str] = mapped_column(String(20))  # phone, email, linkedin, etc.
    contact_person: Mapped[Optional[str]] = mapped_column(String(255))
    contacted_by: Mapped[str] = mapped_column(String(100))  # Agent name

    # Outcome
    outcome: Mapped[str] = mapped_column(String(50))  # connected, voicemail, no_answer, etc.
    notes: Mapped[Optional[str]] = mapped_column(Text)
    follow_up_scheduled: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Related signal
    signal_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("signals.id"))


class ScanJob(Base):
    """
    Record of scanning jobs for monitoring and debugging.
    """

    __tablename__ = "scan_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Job details
    source_type: Mapped[SourceType] = mapped_column(SQLEnum(SourceType))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running, completed, failed

    # Results
    items_scanned: Mapped[int] = mapped_column(Integer, default=0)
    signals_found: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)

    # Metadata
    error_messages: Mapped[Optional[str]] = mapped_column(Text)
    parameters: Mapped[Optional[str]] = mapped_column(Text)  # JSON of scan parameters


class Industry(Base):
    """
    Industry classification reference data.
    """

    __tablename__ = "industries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    naics_code: Mapped[Optional[str]] = mapped_column(String(10))
    keywords: Mapped[Optional[str]] = mapped_column(Text)  # Comma-separated search keywords
    avg_mca_amount: Mapped[Optional[float]] = mapped_column(Float)
    mca_approval_rate: Mapped[Optional[float]] = mapped_column(Float)
    priority_multiplier: Mapped[float] = mapped_column(Float, default=1.0)


class Geography(Base):
    """
    Geographic targeting configuration.
    """

    __tablename__ = "geographies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    city: Mapped[Optional[str]] = mapped_column(String(100))
    zip_code: Mapped[Optional[str]] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority_multiplier: Mapped[float] = mapped_column(Float, default=1.0)

    __table_args__ = (UniqueConstraint("state", "city", "zip_code", name="uq_geography"),)


class Blacklist(Base):
    """
    Blacklisted businesses or domains to skip.
    """

    __tablename__ = "blacklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Match criteria
    business_name: Mapped[Optional[str]] = mapped_column(String(255))
    domain: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(255))

    # Reason
    reason: Mapped[str] = mapped_column(String(255))
    added_by: Mapped[Optional[str]] = mapped_column(String(100))


class DealStage(str, Enum):
    """Deal pipeline stages."""

    LEAD = "lead"
    QUALIFIED = "qualified"
    PROPOSAL_SENT = "proposal_sent"
    NEGOTIATING = "negotiating"
    UNDERWRITING = "underwriting"
    APPROVED = "approved"
    FUNDED = "funded"
    DECLINED = "declined"
    LOST = "lost"


class DealPipeline(Base):
    """
    Deal pipeline tracking.
    Tracks deals through funding stages with timing and amounts.
    """

    __tablename__ = "deal_pipeline"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Business relationship
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), index=True)

    # Deal details
    stage: Mapped[DealStage] = mapped_column(SQLEnum(DealStage), default=DealStage.LEAD, index=True)
    estimated_deal_size: Mapped[float] = mapped_column(Float, default=0)
    actual_deal_amount: Mapped[Optional[float]] = mapped_column(Float)
    probability_percentage: Mapped[int] = mapped_column(Integer, default=10)

    # Timing
    stage_entered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    days_in_current_stage: Mapped[int] = mapped_column(Integer, default=0)
    expected_close_date: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Agent tracking
    assigned_agent_id: Mapped[Optional[str]] = mapped_column(String(100))
    assigned_agent_name: Mapped[Optional[str]] = mapped_column(String(255))

    # Outcome tracking
    deal_won: Mapped[Optional[bool]] = mapped_column(Boolean)
    lost_reason: Mapped[Optional[str]] = mapped_column(String(500))
    lost_to_competitor: Mapped[Optional[str]] = mapped_column(String(255))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Source attribution
    primary_signal_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("signals.id"))
    source_campaign: Mapped[Optional[str]] = mapped_column(String(255))

    # Notes
    notes: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_deal_pipeline_stage", "stage", "created_at"),
        Index("ix_deal_pipeline_agent", "assigned_agent_id", "stage"),
    )


class FundingRecord(Base):
    """
    Record of completed fundings.
    Tracks revenue attribution and deal details.
    """

    __tablename__ = "funding_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), index=True)
    deal_pipeline_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("deal_pipeline.id"))

    # Funding details
    funding_amount: Mapped[float] = mapped_column(Float, nullable=False)
    factor_rate: Mapped[float] = mapped_column(Float, default=1.0)  # e.g., 1.25 = 25% fee
    total_repayment: Mapped[float] = mapped_column(Float, default=0)
    term_months: Mapped[Optional[int]] = mapped_column(Integer)
    payment_frequency: Mapped[Optional[str]] = mapped_column(String(50))  # daily, weekly, monthly

    # Dates
    funded_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    first_payment_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    maturity_date: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Agent/broker
    broker_who_closed: Mapped[str] = mapped_column(String(255))
    broker_commission: Mapped[Optional[float]] = mapped_column(Float)
    broker_commission_percent: Mapped[Optional[float]] = mapped_column(Float)

    # Funder info
    funder_name: Mapped[Optional[str]] = mapped_column(String(255))
    funder_deal_id: Mapped[Optional[str]] = mapped_column(String(100))

    # Attribution
    source_signal_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("signals.id"))
    source_signal_type: Mapped[Optional[str]] = mapped_column(String(50))
    source_type: Mapped[Optional[str]] = mapped_column(String(50))

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(50), default="active")  # active, paid_off, defaulted

    # Notes
    notes: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_funding_record_date", "funded_date"),
        Index("ix_funding_record_broker", "broker_who_closed", "funded_date"),
    )


class SequenceEnrollment(Base):
    """
    Tracks lead enrollment in follow-up sequences.
    """

    __tablename__ = "sequence_enrollments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Business
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), index=True)

    # Sequence tracking
    sequence_id: Mapped[str] = mapped_column(String(36), index=True)
    sequence_name: Mapped[str] = mapped_column(String(255))
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    total_steps: Mapped[int] = mapped_column(Integer, default=1)

    # Status
    status: Mapped[str] = mapped_column(String(50), default="active")  # active, completed, paused, stopped

    # Timing
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    next_action_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # Outcomes
    step_outcomes: Mapped[Optional[str]] = mapped_column(Text)  # JSON of step -> outcome
    final_outcome: Mapped[Optional[str]] = mapped_column(String(100))


class EscalationLog(Base):
    """
    Log of lead escalations.
    """

    __tablename__ = "escalation_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # Business
    business_id: Mapped[str] = mapped_column(String(36), ForeignKey("businesses.id"), index=True)

    # Escalation details
    rule_id: Mapped[str] = mapped_column(String(36))
    rule_name: Mapped[str] = mapped_column(String(255))
    trigger: Mapped[str] = mapped_column(String(100))
    action_taken: Mapped[str] = mapped_column(String(100))

    # Target
    escalated_to: Mapped[str] = mapped_column(String(255))
    escalated_from: Mapped[Optional[str]] = mapped_column(String(255))

    # Reason
    reason: Mapped[str] = mapped_column(Text)

    # Resolution
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(255))


class AgentPerformance(Base):
    """
    Agent performance metrics tracking.
    """

    __tablename__ = "agent_performance"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    agent_id: Mapped[str] = mapped_column(String(100), index=True)
    agent_name: Mapped[str] = mapped_column(String(255))

    # Period
    period_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime)
    period_type: Mapped[str] = mapped_column(String(20))  # daily, weekly, monthly

    # Activity metrics
    leads_assigned: Mapped[int] = mapped_column(Integer, default=0)
    leads_contacted: Mapped[int] = mapped_column(Integer, default=0)
    leads_qualified: Mapped[int] = mapped_column(Integer, default=0)
    proposals_sent: Mapped[int] = mapped_column(Integer, default=0)

    # Outcome metrics
    deals_closed: Mapped[int] = mapped_column(Integer, default=0)
    deals_lost: Mapped[int] = mapped_column(Integer, default=0)
    total_funded_amount: Mapped[float] = mapped_column(Float, default=0)
    total_commission: Mapped[float] = mapped_column(Float, default=0)

    # Efficiency metrics
    avg_cycle_days: Mapped[Optional[float]] = mapped_column(Float)
    close_rate: Mapped[Optional[float]] = mapped_column(Float)
    avg_deal_size: Mapped[Optional[float]] = mapped_column(Float)

    # Contact metrics
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_emails: Mapped[int] = mapped_column(Integer, default=0)
    connect_rate: Mapped[Optional[float]] = mapped_column(Float)

    __table_args__ = (
        Index("ix_agent_performance_period", "agent_id", "period_start"),
    )

