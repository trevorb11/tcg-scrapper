"""
Web Dashboard
=============

Browser-based dashboard for viewing and managing leads.
Uses Jinja2 templates with Tailwind CSS.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from industry_deep_scan.config import get_settings
from industry_deep_scan.database import (
    BusinessRepository,
    SignalRepository,
    get_session,
)
from industry_deep_scan.models import LeadStatus, SignalPriority

settings = get_settings()

# Templates directory
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Dashboard home page with summary stats."""
    async with get_session() as session:
        business_repo = BusinessRepository(session)
        signal_repo = SignalRepository(session)

        # Get counts
        hot_leads = await business_repo.get_hot_leads(limit=10)
        recent_signals = await signal_repo.get_recent(hours=24, limit=10)
        stats = await signal_repo.get_signal_stats(days=7)

        # Get leads needing follow-up
        follow_ups = await business_repo.get_follow_ups_due()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "hot_leads": hot_leads,
        "recent_signals": recent_signals,
        "stats": stats,
        "follow_ups": follow_ups[:5],
        "now": datetime.utcnow(),
    })


@router.get("/leads", response_class=HTMLResponse)
async def leads_list(
    request: Request,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    state: Optional[str] = None,
    industry: Optional[str] = None,
    min_score: float = 0,
    page: int = 1,
    search: Optional[str] = None,
):
    """Leads list page with filtering."""
    page_size = 25
    offset = (page - 1) * page_size

    async with get_session() as session:
        business_repo = BusinessRepository(session)
        signal_repo = SignalRepository(session)

        lead_status = LeadStatus(status) if status else None
        signal_priority = SignalPriority(priority) if priority else None

        leads = await business_repo.get_leads(
            status=lead_status,
            min_score=min_score,
            priority=signal_priority,
            state=state,
            industry=industry,
            limit=page_size,
            offset=offset,
        )

        # Get signal counts for each lead
        leads_with_signals = []
        for lead in leads:
            signals = await signal_repo.get_signals_by_business(lead.id)
            leads_with_signals.append({
                "business": lead,
                "signal_count": len(signals),
                "top_signal": signals[0] if signals else None,
            })

    # States for filter dropdown
    states = ["CA", "TX", "FL", "NY", "IL", "PA", "OH", "GA", "NC", "MI", "NJ", "VA", "WA", "AZ", "MA"]

    return templates.TemplateResponse("leads.html", {
        "request": request,
        "leads": leads_with_signals,
        "states": states,
        "current_status": status,
        "current_priority": priority,
        "current_state": state,
        "current_industry": industry,
        "current_min_score": min_score,
        "page": page,
        "search": search,
    })


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
async def lead_detail(request: Request, lead_id: str):
    """Lead detail page with full history."""
    async with get_session() as session:
        business_repo = BusinessRepository(session)
        signal_repo = SignalRepository(session)

        lead = await business_repo.get_by_id(lead_id)
        if not lead:
            return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

        signals = await signal_repo.get_signals_by_business(lead_id)

    return templates.TemplateResponse("lead_detail.html", {
        "request": request,
        "lead": lead,
        "signals": signals,
        "statuses": [s.value for s in LeadStatus],
    })


@router.post("/leads/{lead_id}/update")
async def update_lead(
    lead_id: str,
    status: str = Form(None),
    assigned_to: str = Form(None),
    notes: str = Form(None),
):
    """Update lead status/notes."""
    async with get_session() as session:
        business_repo = BusinessRepository(session)

        lead = await business_repo.get_by_id(lead_id)
        if lead:
            if status:
                lead.status = LeadStatus(status)
            if assigned_to:
                lead.assigned_to = assigned_to
            if notes:
                lead.notes = notes
            lead.updated_at = datetime.utcnow()

    return RedirectResponse(f"/dashboard/leads/{lead_id}", status_code=303)


@router.get("/signals", response_class=HTMLResponse)
async def signals_list(
    request: Request,
    hours: int = 24,
    source: Optional[str] = None,
    priority: Optional[str] = None,
    page: int = 1,
):
    """Signals list page."""
    page_size = 50

    async with get_session() as session:
        signal_repo = SignalRepository(session)

        from industry_deep_scan.models import SourceType

        source_type = SourceType(source) if source else None
        signal_priority = SignalPriority(priority) if priority else None

        signals = await signal_repo.get_recent(
            hours=hours,
            source_type=source_type,
            priority=signal_priority,
            limit=page_size,
        )

    sources = ["news", "yelp", "bbb", "business_listings", "court_records", "equipment_permits"]

    return templates.TemplateResponse("signals.html", {
        "request": request,
        "signals": signals,
        "sources": sources,
        "current_hours": hours,
        "current_source": source,
        "current_priority": priority,
        "page": page,
    })


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, days: int = 7):
    """Analytics and reports page."""
    async with get_session() as session:
        signal_repo = SignalRepository(session)
        business_repo = BusinessRepository(session)

        stats = await signal_repo.get_signal_stats(days)

        # Get lead pipeline counts
        pipeline = {}
        for status in LeadStatus:
            leads = await business_repo.get_leads(status=status, limit=1000)
            pipeline[status.value] = len(leads)

    return templates.TemplateResponse("analytics.html", {
        "request": request,
        "stats": stats,
        "pipeline": pipeline,
        "days": days,
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page."""
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": settings,
    })
