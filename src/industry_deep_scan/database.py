"""
Database Management
===================

Async database connection management, session handling, and utilities.
"""

import hashlib
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator, Optional, Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from industry_deep_scan.config import get_settings
from industry_deep_scan.models import (
    Base,
    Blacklist,
    Business,
    ContactAttempt,
    Industry,
    LeadStatus,
    ScanJob,
    Signal,
    SignalCategory,
    SignalPriority,
    SignalType,
    SourceType,
)

settings = get_settings()

# Create async engine
engine = create_async_engine(
    settings.database.url,
    echo=settings.environment == "development",
    pool_pre_ping=True,
)

# Session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Initialize database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    """Drop all database tables (use with caution!)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class BusinessRepository:
    """Repository for business operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, business: Business) -> Business:
        """Create a new business."""
        self.session.add(business)
        await self.session.flush()
        return business

    async def get_by_id(self, business_id: str) -> Optional[Business]:
        """Get business by ID with signals loaded."""
        result = await self.session.execute(
            select(Business)
            .where(Business.id == business_id)
            .options(selectinload(Business.signals))
        )
        return result.scalar_one_or_none()

    async def get_by_name_and_location(
        self, name: str, city: Optional[str], state: Optional[str]
    ) -> Optional[Business]:
        """Find existing business by name and location."""
        query = select(Business).where(
            func.lower(Business.name) == func.lower(name)
        )
        if city:
            query = query.where(func.lower(Business.city) == func.lower(city))
        if state:
            query = query.where(Business.state == state)

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_external_id(
        self,
        yelp_id: Optional[str] = None,
        google_place_id: Optional[str] = None,
        linkedin_company_id: Optional[str] = None,
        bbb_id: Optional[str] = None,
    ) -> Optional[Business]:
        """Find business by external ID."""
        query = select(Business)

        if yelp_id:
            query = query.where(Business.yelp_id == yelp_id)
        elif google_place_id:
            query = query.where(Business.google_place_id == google_place_id)
        elif linkedin_company_id:
            query = query.where(Business.linkedin_company_id == linkedin_company_id)
        elif bbb_id:
            query = query.where(Business.bbb_id == bbb_id)
        else:
            return None

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def find_or_create(self, business_data: dict) -> tuple[Business, bool]:
        """Find existing business or create new one."""
        # Try to find by external IDs first
        existing = await self.get_by_external_id(
            yelp_id=business_data.get("yelp_id"),
            google_place_id=business_data.get("google_place_id"),
            linkedin_company_id=business_data.get("linkedin_company_id"),
            bbb_id=business_data.get("bbb_id"),
        )

        if existing:
            # Update with new data
            for key, value in business_data.items():
                if value is not None:
                    setattr(existing, key, value)
            return existing, False

        # Try by name + location
        existing = await self.get_by_name_and_location(
            business_data.get("name", ""),
            business_data.get("city"),
            business_data.get("state"),
        )

        if existing:
            for key, value in business_data.items():
                if value is not None and getattr(existing, key) is None:
                    setattr(existing, key, value)
            return existing, False

        # Create new
        business = Business(**business_data)
        await self.create(business)
        return business, True

    async def update_score(self, business_id: str, score: float, priority: SignalPriority) -> None:
        """Update business lead score and priority."""
        await self.session.execute(
            update(Business)
            .where(Business.id == business_id)
            .values(lead_score=score, priority=priority, updated_at=datetime.utcnow())
        )

    async def get_leads(
        self,
        status: Optional[LeadStatus] = None,
        min_score: float = 0,
        priority: Optional[SignalPriority] = None,
        state: Optional[str] = None,
        industry: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Business]:
        """Get leads with filters."""
        query = select(Business).where(
            Business.lead_score >= min_score,
            Business.is_blacklisted == False,
        )

        if status:
            query = query.where(Business.status == status)
        if priority:
            query = query.where(Business.priority == priority)
        if state:
            query = query.where(Business.state == state)
        if industry:
            query = query.where(Business.industry.ilike(f"%{industry}%"))

        query = query.order_by(Business.lead_score.desc()).offset(offset).limit(limit)

        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_hot_leads(self, limit: int = 50) -> Sequence[Business]:
        """Get highest priority leads that need immediate attention."""
        result = await self.session.execute(
            select(Business)
            .where(
                Business.status == LeadStatus.NEW,
                Business.priority.in_([SignalPriority.CRITICAL, SignalPriority.HIGH]),
                Business.is_blacklisted == False,
            )
            .order_by(Business.lead_score.desc())
            .limit(limit)
            .options(selectinload(Business.signals))
        )
        return result.scalars().all()

    async def get_follow_ups_due(self) -> Sequence[Business]:
        """Get businesses with follow-ups due today or overdue."""
        result = await self.session.execute(
            select(Business)
            .where(
                Business.next_follow_up <= datetime.utcnow(),
                Business.status.not_in([LeadStatus.FUNDED, LeadStatus.DEAD, LeadStatus.NOT_INTERESTED]),
            )
            .order_by(Business.next_follow_up)
        )
        return result.scalars().all()


class SignalRepository:
    """Repository for signal operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def generate_content_hash(content: str) -> str:
        """Generate hash for content deduplication."""
        return hashlib.sha256(content.encode()).hexdigest()

    async def create(self, signal: Signal) -> Signal:
        """Create a new signal."""
        # Generate content hash if not set
        if not signal.content_hash and signal.raw_content:
            signal.content_hash = self.generate_content_hash(signal.raw_content)

        self.session.add(signal)
        await self.session.flush()
        return signal

    async def exists_by_hash(self, business_id: str, content_hash: str) -> bool:
        """Check if signal already exists (deduplication)."""
        result = await self.session.execute(
            select(Signal.id)
            .where(
                Signal.business_id == business_id,
                Signal.content_hash == content_hash,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_by_id(self, signal_id: str) -> Optional[Signal]:
        """Get signal by ID."""
        result = await self.session.execute(
            select(Signal)
            .where(Signal.id == signal_id)
            .options(selectinload(Signal.business))
        )
        return result.scalar_one_or_none()

    async def get_recent(
        self,
        hours: int = 24,
        source_type: Optional[SourceType] = None,
        priority: Optional[SignalPriority] = None,
        limit: int = 100,
    ) -> Sequence[Signal]:
        """Get recent signals."""
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(hours=hours)

        query = select(Signal).where(Signal.created_at >= cutoff)

        if source_type:
            query = query.where(Signal.source_type == source_type)
        if priority:
            query = query.where(Signal.priority == priority)

        query = query.order_by(Signal.created_at.desc()).limit(limit)

        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_unprocessed(self, limit: int = 100) -> Sequence[Signal]:
        """Get signals pending LLM processing."""
        result = await self.session.execute(
            select(Signal)
            .where(Signal.is_processed == False)
            .order_by(Signal.created_at)
            .limit(limit)
        )
        return result.scalars().all()

    async def get_unnotified_high_priority(self, limit: int = 50) -> Sequence[Signal]:
        """Get high-priority signals that haven't been notified."""
        result = await self.session.execute(
            select(Signal)
            .where(
                Signal.is_notified == False,
                Signal.priority.in_([SignalPriority.CRITICAL, SignalPriority.HIGH]),
            )
            .order_by(Signal.created_at)
            .limit(limit)
            .options(selectinload(Signal.business))
        )
        return result.scalars().all()

    async def mark_notified(self, signal_ids: list[str]) -> None:
        """Mark signals as notified."""
        await self.session.execute(
            update(Signal)
            .where(Signal.id.in_(signal_ids))
            .values(is_notified=True)
        )

    async def get_signals_by_business(self, business_id: str) -> Sequence[Signal]:
        """Get all signals for a business."""
        result = await self.session.execute(
            select(Signal)
            .where(Signal.business_id == business_id)
            .order_by(Signal.created_at.desc())
        )
        return result.scalars().all()

    async def get_signal_stats(self, days: int = 7) -> dict:
        """Get signal statistics."""
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(days=days)

        # Total signals
        total_result = await self.session.execute(
            select(func.count()).select_from(Signal).where(Signal.created_at >= cutoff)
        )
        total = total_result.scalar()

        # By priority
        priority_result = await self.session.execute(
            select(Signal.priority, func.count())
            .where(Signal.created_at >= cutoff)
            .group_by(Signal.priority)
        )
        by_priority = dict(priority_result.all())

        # By source
        source_result = await self.session.execute(
            select(Signal.source_type, func.count())
            .where(Signal.created_at >= cutoff)
            .group_by(Signal.source_type)
        )
        by_source = dict(source_result.all())

        # By type
        type_result = await self.session.execute(
            select(Signal.signal_type, func.count())
            .where(Signal.created_at >= cutoff)
            .group_by(Signal.signal_type)
        )
        by_type = dict(type_result.all())

        return {
            "total": total,
            "by_priority": by_priority,
            "by_source": by_source,
            "by_type": by_type,
            "period_days": days,
        }


class ScanJobRepository:
    """Repository for scan job tracking."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, source_type: SourceType, parameters: Optional[dict] = None) -> ScanJob:
        """Create a new scan job."""
        import json

        job = ScanJob(
            source_type=source_type,
            parameters=json.dumps(parameters) if parameters else None,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def complete(
        self,
        job_id: str,
        items_scanned: int,
        signals_found: int,
        errors: int = 0,
        error_messages: Optional[str] = None,
    ) -> None:
        """Mark job as completed."""
        await self.session.execute(
            update(ScanJob)
            .where(ScanJob.id == job_id)
            .values(
                completed_at=datetime.utcnow(),
                status="completed" if errors == 0 else "completed_with_errors",
                items_scanned=items_scanned,
                signals_found=signals_found,
                errors=errors,
                error_messages=error_messages,
            )
        )

    async def fail(self, job_id: str, error_message: str) -> None:
        """Mark job as failed."""
        await self.session.execute(
            update(ScanJob)
            .where(ScanJob.id == job_id)
            .values(
                completed_at=datetime.utcnow(),
                status="failed",
                error_messages=error_message,
            )
        )


class BlacklistRepository:
    """Repository for blacklist operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def is_blacklisted(
        self,
        name: Optional[str] = None,
        domain: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
    ) -> bool:
        """Check if business is blacklisted."""
        query = select(Blacklist.id)

        conditions = []
        if name:
            conditions.append(func.lower(Blacklist.business_name) == func.lower(name))
        if domain:
            conditions.append(func.lower(Blacklist.domain) == func.lower(domain))
        if phone:
            conditions.append(Blacklist.phone == phone)
        if email:
            conditions.append(func.lower(Blacklist.email) == func.lower(email))

        if not conditions:
            return False

        from sqlalchemy import or_

        query = query.where(or_(*conditions)).limit(1)
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None

    async def add(
        self,
        reason: str,
        business_name: Optional[str] = None,
        domain: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        added_by: Optional[str] = None,
    ) -> Blacklist:
        """Add to blacklist."""
        entry = Blacklist(
            business_name=business_name,
            domain=domain,
            phone=phone,
            email=email,
            reason=reason,
            added_by=added_by,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry
