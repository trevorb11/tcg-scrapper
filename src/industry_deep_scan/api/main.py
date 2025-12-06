"""
FastAPI Application
===================

Main API application with routes for leads, signals, scans, and analytics.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path

from industry_deep_scan.config import get_settings
from industry_deep_scan.dashboard import router as dashboard_router
from industry_deep_scan.api.automation_routes import router as automation_router
from industry_deep_scan.api.ucc_routes import router as ucc_router
from industry_deep_scan.database import (
    BusinessRepository,
    SignalRepository,
    get_session,
    init_db,
)
from industry_deep_scan.engine import DeepScanEngine
from industry_deep_scan.models import LeadStatus, SignalPriority, SourceType

settings = get_settings()

# Global engine instance
_engine: Optional[DeepScanEngine] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    global _engine

    # Startup
    await init_db()
    _engine = DeepScanEngine()
    await _engine.setup()

    yield

    # Shutdown
    if _engine:
        await _engine.teardown()


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Industry Deep Scan API",
        description="AI-powered industry signal scanner for MCA lead generation",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(dashboard_router)
    app.include_router(automation_router, prefix="/api/v1")
    app.include_router(ucc_router, prefix="/api/v1")

    return app


app = create_app()

# API Key authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Verify API key for protected routes."""
    if not settings.api.api_key_enabled:
        return "anonymous"

    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")

    if api_key not in settings.api.api_keys:
        raise HTTPException(status_code=403, detail="Invalid API key")

    return api_key


def get_engine() -> DeepScanEngine:
    """Get engine instance."""
    if _engine is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")
    return _engine


# === Pydantic Models ===


class LeadResponse(BaseModel):
    """Lead response model."""

    id: str
    business_name: str
    industry: Optional[str] = None
    location: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    score: float
    priority: str
    status: str
    signals: list[dict] = Field(default_factory=list)
    created_at: str


class LeadListResponse(BaseModel):
    """List of leads response."""

    leads: list[LeadResponse]
    total: int
    page: int
    page_size: int


class SignalResponse(BaseModel):
    """Signal response model."""

    id: str
    business_id: str
    business_name: str
    signal_type: str
    category: str
    priority: str
    title: str
    description: Optional[str] = None
    source_type: str
    source_url: Optional[str] = None
    source_date: Optional[str] = None
    confidence_score: float
    recommended_approach: Optional[str] = None
    created_at: str


class ScanRequest(BaseModel):
    """Request to trigger a scan."""

    source: Optional[str] = None  # Specific source or "all"
    states: Optional[list[str]] = None
    industries: Optional[list[str]] = None


class ScanResponse(BaseModel):
    """Scan result response."""

    job_id: Optional[str] = None
    status: str
    signals_found: int = 0
    errors: int = 0
    start_time: str
    end_time: Optional[str] = None
    details: dict = Field(default_factory=dict)


class StatsResponse(BaseModel):
    """Statistics response model."""

    total_signals: int
    by_priority: dict
    by_source: dict
    by_type: dict
    period_days: int
    classifier_stats: dict


class LeadUpdateRequest(BaseModel):
    """Request to update a lead."""

    status: Optional[str] = None
    assigned_to: Optional[str] = None
    notes: Optional[str] = None
    next_follow_up: Optional[str] = None


# === Routes ===


@app.get("/")
async def root():
    """API root - health check."""
    return {
        "name": "Industry Deep Scan API",
        "version": "1.0.0",
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/health")
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "database": "connected",
        "engine": "ready" if _engine else "not initialized",
        "timestamp": datetime.utcnow().isoformat(),
    }


# === Leads Routes ===


@app.get("/leads", response_model=LeadListResponse)
async def get_leads(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    state: Optional[str] = None,
    industry: Optional[str] = None,
    min_score: float = Query(default=0, ge=0, le=10),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    api_key: str = Depends(verify_api_key),
):
    """
    Get leads with filtering and pagination.

    Query Parameters:
    - status: Filter by lead status (new, contacted, qualified, etc.)
    - priority: Filter by priority (critical, high, medium, low)
    - state: Filter by state code (CA, TX, etc.)
    - industry: Filter by industry keyword
    - min_score: Minimum lead score (0-10)
    - page: Page number (default 1)
    - page_size: Items per page (default 50, max 100)
    """
    async with get_session() as session:
        business_repo = BusinessRepository(session)

        # Parse enums
        lead_status = LeadStatus(status) if status else None
        signal_priority = SignalPriority(priority) if priority else None

        offset = (page - 1) * page_size

        businesses = await business_repo.get_leads(
            status=lead_status,
            min_score=min_score,
            priority=signal_priority,
            state=state,
            industry=industry,
            limit=page_size,
            offset=offset,
        )

        leads = []
        signal_repo = SignalRepository(session)

        for business in businesses:
            signals = await signal_repo.get_signals_by_business(business.id)

            leads.append(LeadResponse(
                id=business.id,
                business_name=business.name,
                industry=business.industry,
                location=f"{business.city}, {business.state}" if business.city else business.state,
                phone=business.phone,
                website=business.website,
                score=business.lead_score,
                priority=business.priority.value,
                status=business.status.value,
                signals=[
                    {
                        "type": s.signal_type.value,
                        "title": s.title,
                        "source": s.source_type.value,
                    }
                    for s in signals[:3]
                ],
                created_at=business.created_at.isoformat(),
            ))

        return LeadListResponse(
            leads=leads,
            total=len(leads),  # TODO: Add actual count query
            page=page,
            page_size=page_size,
        )


@app.get("/leads/hot")
async def get_hot_leads(
    limit: int = Query(default=20, ge=1, le=100),
    api_key: str = Depends(verify_api_key),
    engine: DeepScanEngine = Depends(get_engine),
):
    """
    Get highest priority leads for immediate outreach.

    These are the leads your sales team should call RIGHT NOW.
    """
    leads = await engine.get_hot_leads(limit)
    return {"leads": leads, "count": len(leads)}


@app.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Get detailed lead information."""
    async with get_session() as session:
        business_repo = BusinessRepository(session)
        signal_repo = SignalRepository(session)

        business = await business_repo.get_by_id(lead_id)

        if not business:
            raise HTTPException(status_code=404, detail="Lead not found")

        signals = await signal_repo.get_signals_by_business(lead_id)

        return LeadResponse(
            id=business.id,
            business_name=business.name,
            industry=business.industry,
            location=f"{business.city}, {business.state}" if business.city else business.state,
            phone=business.phone,
            website=business.website,
            score=business.lead_score,
            priority=business.priority.value,
            status=business.status.value,
            signals=[
                {
                    "type": s.signal_type.value,
                    "category": s.category.value,
                    "title": s.title,
                    "description": s.description,
                    "source": s.source_type.value,
                    "source_url": s.source_url,
                    "date": s.source_date.isoformat() if s.source_date else None,
                    "confidence": s.confidence_score,
                    "recommended_approach": s.recommended_approach,
                    "analysis": s.llm_analysis,
                }
                for s in signals
            ],
            created_at=business.created_at.isoformat(),
        )


@app.patch("/leads/{lead_id}")
async def update_lead(
    lead_id: str,
    update: LeadUpdateRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Update lead status and metadata.

    Use this to track lead progression through your pipeline.
    """
    async with get_session() as session:
        business_repo = BusinessRepository(session)

        business = await business_repo.get_by_id(lead_id)
        if not business:
            raise HTTPException(status_code=404, detail="Lead not found")

        # Update fields
        if update.status:
            business.status = LeadStatus(update.status)

        if update.assigned_to:
            business.assigned_to = update.assigned_to

        if update.notes:
            business.notes = update.notes

        if update.next_follow_up:
            business.next_follow_up = datetime.fromisoformat(update.next_follow_up)

        return {"message": "Lead updated", "id": lead_id}


# === Signals Routes ===


@app.get("/signals")
async def get_signals(
    hours: int = Query(default=24, ge=1, le=168),
    source: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    api_key: str = Depends(verify_api_key),
):
    """
    Get recent signals.

    Query Parameters:
    - hours: Look back period (default 24, max 168)
    - source: Filter by source type
    - priority: Filter by priority level
    - limit: Maximum results (default 100)
    """
    async with get_session() as session:
        signal_repo = SignalRepository(session)

        source_type = SourceType(source) if source else None
        signal_priority = SignalPriority(priority) if priority else None

        signals = await signal_repo.get_recent(
            hours=hours,
            source_type=source_type,
            priority=signal_priority,
            limit=limit,
        )

        return {
            "signals": [
                {
                    "id": s.id,
                    "business_id": s.business_id,
                    "type": s.signal_type.value,
                    "category": s.category.value,
                    "priority": s.priority.value,
                    "title": s.title,
                    "source": s.source_type.value,
                    "source_url": s.source_url,
                    "date": s.source_date.isoformat() if s.source_date else None,
                    "created_at": s.created_at.isoformat(),
                }
                for s in signals
            ],
            "count": len(signals),
            "hours": hours,
        }


# === Scans Routes ===


@app.post("/scans", response_model=ScanResponse)
async def trigger_scan(
    request: ScanRequest,
    api_key: str = Depends(verify_api_key),
    engine: DeepScanEngine = Depends(get_engine),
):
    """
    Trigger a scan manually.

    Request Body:
    - source: Specific source to scan (news, yelp, bbb, etc.) or "all"
    - states: List of state codes to target
    - industries: List of industries to target
    """
    start_time = datetime.utcnow()

    try:
        if request.source and request.source != "all":
            # Single source scan
            source_type = SourceType(request.source)
            result = await engine.run_source_scan(
                source_type,
                states=request.states,
                industries=request.industries,
            )

            return ScanResponse(
                status="completed",
                signals_found=result.get("signals_found", 0),
                errors=result.get("errors", 0),
                start_time=start_time.isoformat(),
                end_time=datetime.utcnow().isoformat(),
                details=result,
            )
        else:
            # Full scan
            result = await engine.run_full_scan(
                states=request.states,
                industries=request.industries,
            )

            return ScanResponse(
                status="completed",
                signals_found=result["totals"]["signals_found"],
                errors=result["totals"]["errors"],
                start_time=start_time.isoformat(),
                end_time=datetime.utcnow().isoformat(),
                details=result,
            )

    except Exception as e:
        return ScanResponse(
            status="failed",
            start_time=start_time.isoformat(),
            end_time=datetime.utcnow().isoformat(),
            details={"error": str(e)},
        )


# === Analytics Routes ===


@app.get("/analytics/stats", response_model=StatsResponse)
async def get_stats(
    days: int = Query(default=7, ge=1, le=90),
    api_key: str = Depends(verify_api_key),
    engine: DeepScanEngine = Depends(get_engine),
):
    """
    Get signal and lead statistics.

    Query Parameters:
    - days: Analysis period (default 7 days)
    """
    signal_stats = await engine.get_signal_stats(days)
    classifier_stats = await engine.get_classifier_stats()

    return StatsResponse(
        total_signals=signal_stats.get("total", 0),
        by_priority={str(k): v for k, v in signal_stats.get("by_priority", {}).items()},
        by_source={str(k): v for k, v in signal_stats.get("by_source", {}).items()},
        by_type={str(k): v for k, v in signal_stats.get("by_type", {}).items()},
        period_days=days,
        classifier_stats=classifier_stats,
    )


@app.get("/analytics/sources")
async def get_source_stats(
    api_key: str = Depends(verify_api_key),
    engine: DeepScanEngine = Depends(get_engine),
):
    """Get statistics by source."""
    stats = await engine.get_signal_stats(7)

    return {
        "sources": [
            {
                "source": str(source),
                "signal_count": count,
            }
            for source, count in stats.get("by_source", {}).items()
        ],
    }


# === Export Routes ===


@app.get("/export/leads")
async def export_leads(
    format: str = Query(default="json", regex="^(json|csv)$"),
    status: Optional[str] = None,
    min_score: float = Query(default=5, ge=0, le=10),
    limit: int = Query(default=500, ge=1, le=5000),
    api_key: str = Depends(verify_api_key),
):
    """
    Export leads for CRM import.

    Query Parameters:
    - format: Export format (json or csv)
    - status: Filter by status
    - min_score: Minimum lead score
    - limit: Maximum records
    """
    async with get_session() as session:
        business_repo = BusinessRepository(session)

        lead_status = LeadStatus(status) if status else None

        businesses = await business_repo.get_leads(
            status=lead_status,
            min_score=min_score,
            limit=limit,
        )

        if format == "csv":
            import io
            import csv

            output = io.StringIO()
            writer = csv.writer(output)

            # Header
            writer.writerow([
                "ID", "Business Name", "Industry", "City", "State",
                "Phone", "Website", "Score", "Priority", "Status", "Created"
            ])

            # Data
            for b in businesses:
                writer.writerow([
                    b.id, b.name, b.industry, b.city, b.state,
                    b.phone, b.website, b.lead_score, b.priority.value,
                    b.status.value, b.created_at.isoformat()
                ])

            from fastapi.responses import StreamingResponse

            output.seek(0)
            return StreamingResponse(
                iter([output.getvalue()]),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
            )

        else:
            return {
                "leads": [
                    {
                        "id": b.id,
                        "business_name": b.name,
                        "industry": b.industry,
                        "city": b.city,
                        "state": b.state,
                        "phone": b.phone,
                        "email": b.email,
                        "website": b.website,
                        "score": b.lead_score,
                        "priority": b.priority.value,
                        "status": b.status.value,
                        "created_at": b.created_at.isoformat(),
                    }
                    for b in businesses
                ],
                "count": len(businesses),
                "exported_at": datetime.utcnow().isoformat(),
            }


# === Contact Tracking Routes ===


class ContactAttemptRequest(BaseModel):
    """Request to log a contact attempt."""

    contact_method: str  # "phone", "email", "visit", etc.
    outcome: str  # "connected", "voicemail", "no_answer", "bounced", etc.
    notes: Optional[str] = None
    contacted_by: Optional[str] = None


class ContactAttemptResponse(BaseModel):
    """Contact attempt response."""

    id: str
    lead_id: str
    contact_method: str
    outcome: str
    notes: Optional[str] = None
    contacted_by: Optional[str] = None
    created_at: str


@app.post("/leads/{lead_id}/contacts", response_model=ContactAttemptResponse)
async def log_contact_attempt(
    lead_id: str,
    request: ContactAttemptRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Log a contact attempt for a lead.

    Use this to track outreach attempts and outcomes.
    """
    async with get_session() as session:
        business_repo = BusinessRepository(session)

        business = await business_repo.get_by_id(lead_id)
        if not business:
            raise HTTPException(status_code=404, detail="Lead not found")

        # Create contact attempt record
        from industry_deep_scan.models import ContactAttempt
        import uuid

        contact = ContactAttempt(
            id=str(uuid.uuid4()),
            business_id=lead_id,
            contact_method=request.contact_method,
            outcome=request.outcome,
            notes=request.notes,
            contacted_by=request.contacted_by,
            created_at=datetime.utcnow(),
        )

        session.add(contact)

        # Update lead status if first successful contact
        if request.outcome == "connected" and business.status == LeadStatus.NEW:
            business.status = LeadStatus.CONTACTED
            business.last_contacted = datetime.utcnow()

        return ContactAttemptResponse(
            id=contact.id,
            lead_id=lead_id,
            contact_method=request.contact_method,
            outcome=request.outcome,
            notes=request.notes,
            contacted_by=request.contacted_by,
            created_at=contact.created_at.isoformat(),
        )


@app.get("/leads/{lead_id}/contacts")
async def get_contact_history(
    lead_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Get contact attempt history for a lead."""
    async with get_session() as session:
        business_repo = BusinessRepository(session)

        business = await business_repo.get_by_id(lead_id)
        if not business:
            raise HTTPException(status_code=404, detail="Lead not found")

        # Get contact history
        from sqlalchemy import select
        from industry_deep_scan.models import ContactAttempt

        result = await session.execute(
            select(ContactAttempt)
            .where(ContactAttempt.business_id == lead_id)
            .order_by(ContactAttempt.created_at.desc())
        )
        contacts = result.scalars().all()

        return {
            "lead_id": lead_id,
            "contacts": [
                {
                    "id": c.id,
                    "method": c.contact_method,
                    "outcome": c.outcome,
                    "notes": c.notes,
                    "contacted_by": c.contacted_by,
                    "created_at": c.created_at.isoformat(),
                }
                for c in contacts
            ],
            "total_attempts": len(contacts),
        }


# === Bulk Operations Routes ===


class BulkStatusUpdate(BaseModel):
    """Request for bulk status update."""

    lead_ids: list[str]
    status: str
    assigned_to: Optional[str] = None


@app.post("/leads/bulk/status")
async def bulk_update_status(
    request: BulkStatusUpdate,
    api_key: str = Depends(verify_api_key),
):
    """
    Update status for multiple leads at once.

    Useful for batch processing after campaigns.
    """
    async with get_session() as session:
        business_repo = BusinessRepository(session)

        updated = 0
        errors = []

        for lead_id in request.lead_ids:
            try:
                business = await business_repo.get_by_id(lead_id)
                if business:
                    business.status = LeadStatus(request.status)
                    if request.assigned_to:
                        business.assigned_to = request.assigned_to
                    business.updated_at = datetime.utcnow()
                    updated += 1
                else:
                    errors.append({"id": lead_id, "error": "Not found"})
            except Exception as e:
                errors.append({"id": lead_id, "error": str(e)})

        return {
            "updated": updated,
            "errors": errors,
            "total": len(request.lead_ids),
        }


class BulkBlacklistRequest(BaseModel):
    """Request to blacklist businesses."""

    lead_ids: list[str]
    reason: Optional[str] = None


@app.post("/leads/bulk/blacklist")
async def bulk_blacklist(
    request: BulkBlacklistRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Blacklist multiple leads.

    Blacklisted leads won't appear in searches or exports.
    """
    async with get_session() as session:
        business_repo = BusinessRepository(session)

        blacklisted = 0
        for lead_id in request.lead_ids:
            business = await business_repo.get_by_id(lead_id)
            if business:
                business.is_blacklisted = True
                business.blacklist_reason = request.reason
                business.updated_at = datetime.utcnow()
                blacklisted += 1

        return {
            "blacklisted": blacklisted,
            "total": len(request.lead_ids),
        }


# === Data Quality Routes ===


@app.get("/data/quality")
async def get_data_quality_stats(
    api_key: str = Depends(verify_api_key),
):
    """
    Get data quality statistics for the lead database.

    Useful for monitoring data completeness.
    """
    async with get_session() as session:
        from sqlalchemy import func, select
        from industry_deep_scan.models import Business

        # Total leads
        total_result = await session.execute(select(func.count(Business.id)))
        total = total_result.scalar() or 0

        # Leads with phone
        phone_result = await session.execute(
            select(func.count(Business.id)).where(Business.phone.isnot(None))
        )
        with_phone = phone_result.scalar() or 0

        # Leads with email
        email_result = await session.execute(
            select(func.count(Business.id)).where(Business.email.isnot(None))
        )
        with_email = email_result.scalar() or 0

        # Leads with website
        website_result = await session.execute(
            select(func.count(Business.id)).where(Business.website.isnot(None))
        )
        with_website = website_result.scalar() or 0

        # Leads with industry
        industry_result = await session.execute(
            select(func.count(Business.id)).where(Business.industry.isnot(None))
        )
        with_industry = industry_result.scalar() or 0

        # Leads with revenue estimate
        revenue_result = await session.execute(
            select(func.count(Business.id)).where(Business.annual_revenue_estimate.isnot(None))
        )
        with_revenue = revenue_result.scalar() or 0

        # Average score
        avg_score_result = await session.execute(
            select(func.avg(Business.lead_score))
        )
        avg_score = avg_score_result.scalar() or 0

        return {
            "total_leads": total,
            "completeness": {
                "phone": {"count": with_phone, "percent": (with_phone / total * 100) if total else 0},
                "email": {"count": with_email, "percent": (with_email / total * 100) if total else 0},
                "website": {"count": with_website, "percent": (with_website / total * 100) if total else 0},
                "industry": {"count": with_industry, "percent": (with_industry / total * 100) if total else 0},
                "revenue_estimate": {"count": with_revenue, "percent": (with_revenue / total * 100) if total else 0},
            },
            "average_score": round(avg_score, 2),
            "checked_at": datetime.utcnow().isoformat(),
        }


@app.get("/data/duplicates")
async def find_duplicate_leads(
    threshold: float = Query(default=0.85, ge=0.5, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
    api_key: str = Depends(verify_api_key),
):
    """
    Find potential duplicate leads in the database.

    Uses fuzzy matching on business name, phone, and address.
    """
    async with get_session() as session:
        business_repo = BusinessRepository(session)

        # Get recent leads to check
        leads = await business_repo.get_leads(limit=500)

        from industry_deep_scan.utils import is_duplicate_business

        duplicates = []
        checked = set()

        for i, lead1 in enumerate(leads):
            for j, lead2 in enumerate(leads[i + 1:], i + 1):
                pair_key = tuple(sorted([lead1.id, lead2.id]))
                if pair_key in checked:
                    continue
                checked.add(pair_key)

                is_dup, confidence = is_duplicate_business(
                    name1=lead1.name,
                    name2=lead2.name,
                    phone1=lead1.phone,
                    phone2=lead2.phone,
                    address1=lead1.address,
                    address2=lead2.address,
                    city1=lead1.city,
                    city2=lead2.city,
                    threshold=threshold,
                )

                if is_dup:
                    duplicates.append({
                        "lead1": {
                            "id": lead1.id,
                            "name": lead1.name,
                            "phone": lead1.phone,
                            "city": lead1.city,
                        },
                        "lead2": {
                            "id": lead2.id,
                            "name": lead2.name,
                            "phone": lead2.phone,
                            "city": lead2.city,
                        },
                        "confidence": round(confidence, 2),
                    })

                if len(duplicates) >= limit:
                    break
            if len(duplicates) >= limit:
                break

        return {
            "duplicates": duplicates,
            "count": len(duplicates),
            "threshold": threshold,
            "checked_pairs": len(checked),
        }


# === Pipeline Analytics Routes ===


@app.get("/analytics/pipeline")
async def get_pipeline_stats(
    api_key: str = Depends(verify_api_key),
):
    """
    Get detailed pipeline funnel statistics.
    """
    async with get_session() as session:
        from sqlalchemy import func, select
        from industry_deep_scan.models import Business

        pipeline = {}
        total = 0

        for status in LeadStatus:
            result = await session.execute(
                select(func.count(Business.id)).where(Business.status == status)
            )
            count = result.scalar() or 0
            pipeline[status.value] = count
            total += count

        # Calculate conversion rates
        conversions = {}
        stages = ["new", "contacted", "qualified", "proposal_sent", "funded"]

        for i in range(len(stages) - 1):
            current = pipeline.get(stages[i], 0)
            next_stage = pipeline.get(stages[i + 1], 0)
            rate = (next_stage / current * 100) if current > 0 else 0
            conversions[f"{stages[i]}_to_{stages[i + 1]}"] = round(rate, 1)

        # Overall conversion
        overall = (pipeline.get("funded", 0) / pipeline.get("new", 1)) * 100

        return {
            "pipeline": pipeline,
            "total_leads": total,
            "conversions": conversions,
            "overall_conversion_rate": round(overall, 2),
        }


@app.get("/analytics/velocity")
async def get_pipeline_velocity(
    days: int = Query(default=30, ge=7, le=90),
    api_key: str = Depends(verify_api_key),
):
    """
    Get pipeline velocity metrics - how fast leads move through stages.
    """
    async with get_session() as session:
        from sqlalchemy import func, select
        from industry_deep_scan.models import Business

        cutoff = datetime.utcnow() - timedelta(days=days)

        # Get leads that have moved through pipeline
        result = await session.execute(
            select(Business).where(
                Business.status.in_([LeadStatus.QUALIFIED, LeadStatus.PROPOSAL_SENT, LeadStatus.FUNDED]),
                Business.created_at >= cutoff,
            )
        )
        leads = result.scalars().all()

        if not leads:
            return {
                "average_days_to_contact": 0,
                "average_days_to_qualify": 0,
                "average_days_to_close": 0,
                "sample_size": 0,
            }

        # Calculate averages (using updated_at as proxy for stage transitions)
        days_to_qualify = []
        days_to_close = []

        for lead in leads:
            if lead.status in [LeadStatus.QUALIFIED, LeadStatus.PROPOSAL_SENT, LeadStatus.FUNDED]:
                days_diff = (lead.updated_at - lead.created_at).days
                days_to_qualify.append(days_diff)

            if lead.status == LeadStatus.FUNDED:
                days_diff = (lead.updated_at - lead.created_at).days
                days_to_close.append(days_diff)

        return {
            "average_days_to_qualify": round(sum(days_to_qualify) / len(days_to_qualify), 1) if days_to_qualify else 0,
            "average_days_to_close": round(sum(days_to_close) / len(days_to_close), 1) if days_to_close else 0,
            "sample_size": len(leads),
            "period_days": days,
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "industry_deep_scan.api.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=settings.api.debug,
    )
