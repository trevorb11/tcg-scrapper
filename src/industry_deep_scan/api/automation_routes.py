"""
Automation API Routes
=====================

API endpoints for deal intelligence, sequences, escalations, and assignments.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from industry_deep_scan.automation import (
    SequenceEngine,
    EscalationEngine,
    AssignmentEngine,
    StepOutcome,
)
from industry_deep_scan.classifiers.deal_intelligence import DealIntelligenceEngine
from industry_deep_scan.database import (
    BusinessRepository,
    SignalRepository,
    get_session,
)
from industry_deep_scan.models import SignalPriority

router = APIRouter(tags=["automation"])

# Global engine instances (in production, use dependency injection)
_sequence_engine: Optional[SequenceEngine] = None
_escalation_engine: Optional[EscalationEngine] = None
_assignment_engine: Optional[AssignmentEngine] = None
_deal_intelligence: Optional[DealIntelligenceEngine] = None


def get_sequence_engine() -> SequenceEngine:
    global _sequence_engine
    if _sequence_engine is None:
        _sequence_engine = SequenceEngine()
    return _sequence_engine


def get_escalation_engine() -> EscalationEngine:
    global _escalation_engine
    if _escalation_engine is None:
        _escalation_engine = EscalationEngine()
    return _escalation_engine


def get_assignment_engine() -> AssignmentEngine:
    global _assignment_engine
    if _assignment_engine is None:
        _assignment_engine = AssignmentEngine()
    return _assignment_engine


def get_deal_intelligence() -> DealIntelligenceEngine:
    global _deal_intelligence
    if _deal_intelligence is None:
        _deal_intelligence = DealIntelligenceEngine()
    return _deal_intelligence


# === Deal Intelligence Routes ===


class DealIntelligenceResponse(BaseModel):
    """Deal intelligence response."""

    lead_id: str
    business_name: str

    # Deal sizing
    deal_size_min: float
    deal_size_likely: float
    deal_size_max: float
    deal_size_confidence: float
    deal_size_reasoning: str

    # Timeline
    funding_urgency: str
    estimated_days_to_decision: int
    timeline_confidence: float
    timeline_reasoning: str

    # Approval
    approval_probability: float
    mca_fit_score: float
    receptiveness_score: float
    risk_factors: list[str]
    positive_factors: list[str]

    # Sales enablement
    recommended_approach: str
    talk_track_hooks: list[str]
    objection_anticipation: list[str]


@router.get("/leads/{lead_id}/deal-intelligence", response_model=DealIntelligenceResponse)
async def get_deal_intelligence_for_lead(lead_id: str):
    """
    Get comprehensive deal intelligence for a lead.

    Returns:
    - Deal size estimates (min/likely/max)
    - Funding timeline and urgency
    - Approval probability assessment
    - AI-generated talk tracks and objection handlers
    """
    async with get_session() as session:
        business_repo = BusinessRepository(session)
        signal_repo = SignalRepository(session)

        business = await business_repo.get_by_id(lead_id)
        if not business:
            raise HTTPException(status_code=404, detail="Lead not found")

        signals = await signal_repo.get_signals_by_business(lead_id)

        engine = get_deal_intelligence()
        intel = engine.analyze(business, signals)

        return DealIntelligenceResponse(
            lead_id=lead_id,
            business_name=business.name,
            deal_size_min=intel.deal_size.min_amount,
            deal_size_likely=intel.deal_size.likely_amount,
            deal_size_max=intel.deal_size.max_amount,
            deal_size_confidence=intel.deal_size.confidence,
            deal_size_reasoning=intel.deal_size.reasoning,
            funding_urgency=intel.timeline.urgency.value,
            estimated_days_to_decision=intel.timeline.estimated_days,
            timeline_confidence=intel.timeline.confidence,
            timeline_reasoning=intel.timeline.reasoning,
            approval_probability=intel.approval.approval_probability,
            mca_fit_score=intel.approval.mca_fit_score,
            receptiveness_score=intel.approval.receptiveness_score,
            risk_factors=intel.approval.risk_factors,
            positive_factors=intel.approval.positive_factors,
            recommended_approach=intel.recommended_approach,
            talk_track_hooks=intel.talk_track_hooks,
            objection_anticipation=intel.objection_anticipation,
        )


# === Sequence Routes ===


class SequenceInfo(BaseModel):
    """Sequence information."""

    id: str
    name: str
    description: str
    total_steps: int
    total_duration_days: int
    is_active: bool


class SequenceStatusResponse(BaseModel):
    """Sequence status for a lead."""

    business_id: str
    sequence_name: str
    status: str
    current_step: int
    total_steps: int
    started_at: str
    next_action_at: Optional[str]
    completed_at: Optional[str]
    step_outcomes: dict


@router.get("/sequences")
async def list_sequences():
    """Get all available follow-up sequences."""
    engine = get_sequence_engine()
    sequences = []

    for seq in engine.sequences.values():
        sequences.append(SequenceInfo(
            id=seq.id,
            name=seq.name,
            description=seq.description,
            total_steps=seq.step_count,
            total_duration_days=seq.total_duration_days,
            is_active=seq.is_active,
        ))

    return {"sequences": sequences, "count": len(sequences)}


@router.post("/leads/{lead_id}/sequences/start")
async def start_sequence_for_lead(
    lead_id: str,
    sequence_id: Optional[str] = None,
):
    """
    Start a follow-up sequence for a lead.

    If no sequence_id is provided, automatically selects best sequence
    based on lead's signals.
    """
    async with get_session() as session:
        business_repo = BusinessRepository(session)
        signal_repo = SignalRepository(session)

        business = await business_repo.get_by_id(lead_id)
        if not business:
            raise HTTPException(status_code=404, detail="Lead not found")

        signals = await signal_repo.get_signals_by_business(lead_id)

        engine = get_sequence_engine()

        # Find or specify sequence
        if sequence_id:
            if sequence_id not in engine.sequences:
                raise HTTPException(status_code=404, detail="Sequence not found")
            sequence = engine.sequences[sequence_id]
        else:
            # Auto-select based on signals
            if signals:
                sequence = engine.get_sequence_for_signal(
                    signals[0].signal_type,
                    signals[0].priority,
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail="No signals found - cannot auto-select sequence",
                )

        if not sequence:
            raise HTTPException(
                status_code=400,
                detail="No matching sequence found for this lead's signals",
            )

        state = engine.start_sequence(lead_id, sequence)

        return {
            "message": "Sequence started",
            "business_id": lead_id,
            "sequence_name": sequence.name,
            "total_steps": sequence.step_count,
            "first_step": {
                "channel": sequence.steps[0].channel.value,
                "template_key": sequence.steps[0].template_key,
            },
        }


@router.get("/leads/{lead_id}/sequences/status", response_model=SequenceStatusResponse)
async def get_sequence_status(lead_id: str):
    """Get current sequence status for a lead."""
    engine = get_sequence_engine()
    status = engine.get_sequence_status(lead_id)

    if not status:
        raise HTTPException(status_code=404, detail="Lead not enrolled in any sequence")

    return SequenceStatusResponse(**status)


class AdvanceSequenceRequest(BaseModel):
    """Request to advance sequence."""

    outcome: str  # StepOutcome value


@router.post("/leads/{lead_id}/sequences/advance")
async def advance_sequence(lead_id: str, request: AdvanceSequenceRequest):
    """Advance to next step in sequence based on outcome."""
    engine = get_sequence_engine()

    try:
        outcome = StepOutcome(request.outcome)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid outcome. Valid values: {[o.value for o in StepOutcome]}",
        )

    next_step = engine.advance_sequence(lead_id, outcome)

    if next_step:
        return {
            "message": "Advanced to next step",
            "next_step": {
                "step_number": next_step.step_number,
                "channel": next_step.channel.value,
                "delay_hours": next_step.delay_hours,
                "template_key": next_step.template_key,
            },
        }
    else:
        return {
            "message": "Sequence completed",
            "status": engine.get_sequence_status(lead_id),
        }


@router.post("/leads/{lead_id}/sequences/pause")
async def pause_sequence(lead_id: str):
    """Pause sequence for a lead."""
    engine = get_sequence_engine()
    if engine.pause_sequence(lead_id):
        return {"message": "Sequence paused", "business_id": lead_id}
    raise HTTPException(status_code=404, detail="Lead not enrolled in any sequence")


@router.post("/leads/{lead_id}/sequences/resume")
async def resume_sequence(lead_id: str):
    """Resume paused sequence."""
    engine = get_sequence_engine()
    if engine.resume_sequence(lead_id):
        return {"message": "Sequence resumed", "business_id": lead_id}
    raise HTTPException(status_code=404, detail="Lead not enrolled or not paused")


@router.post("/leads/{lead_id}/sequences/stop")
async def stop_sequence(lead_id: str, reason: str = ""):
    """Stop sequence permanently."""
    engine = get_sequence_engine()
    if engine.stop_sequence(lead_id, reason):
        return {"message": "Sequence stopped", "business_id": lead_id, "reason": reason}
    raise HTTPException(status_code=404, detail="Lead not enrolled in any sequence")


@router.get("/sequences/pending-actions")
async def get_pending_sequence_actions():
    """Get all pending sequence actions that are due."""
    engine = get_sequence_engine()
    pending = engine.get_pending_actions()

    return {
        "pending_actions": [
            {
                "business_id": business_id,
                "step_number": step.step_number,
                "channel": step.channel.value,
                "template_key": step.template_key,
            }
            for business_id, step in pending
        ],
        "count": len(pending),
    }


# === Escalation Routes ===


@router.get("/escalations/rules")
async def list_escalation_rules():
    """Get all escalation rules."""
    engine = get_escalation_engine()
    rules = engine.get_rules()

    return {
        "rules": [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "trigger": r.trigger.value,
                "action": r.action.value,
                "target_role": r.target_role,
                "priority": r.priority,
                "is_active": r.is_active,
            }
            for r in rules
        ],
        "count": len(rules),
    }


@router.get("/escalations/active")
async def get_escalated_leads():
    """Get all currently escalated leads."""
    engine = get_escalation_engine()
    escalated = engine.get_escalated_leads()

    return {
        "escalated_leads": [
            {
                "business_id": state.business_id,
                "escalation_level": state.escalation_level,
                "escalated_to": state.escalated_to,
                "escalated_at": state.escalated_at.isoformat() if state.escalated_at else None,
                "reason": state.escalation_reason,
            }
            for state in escalated
        ],
        "count": len(escalated),
    }


@router.post("/leads/{lead_id}/escalations/check")
async def check_lead_escalation(lead_id: str):
    """Check if a lead should be escalated."""
    async with get_session() as session:
        business_repo = BusinessRepository(session)
        signal_repo = SignalRepository(session)

        business = await business_repo.get_by_id(lead_id)
        if not business:
            raise HTTPException(status_code=404, detail="Lead not found")

        signals = await signal_repo.get_signals_by_business(lead_id)

        # Get deal size estimate
        deal_engine = get_deal_intelligence()
        deal_size = deal_engine.estimate_deal_size(business, signals)

        engine = get_escalation_engine()
        events = engine.check_escalation(
            business_id=lead_id,
            priority=business.priority,
            status=business.status,
            created_at=business.created_at,
            assigned_to=business.assigned_to,
            signal_count=len(signals),
            deal_size_estimate=deal_size.likely_amount,
            contact_attempts=0,  # Would come from contact history
            last_contacted=business.last_contacted,
            next_follow_up=business.next_follow_up,
        )

        return {
            "business_id": lead_id,
            "escalations_triggered": len(events),
            "events": [
                {
                    "trigger": e.trigger.value,
                    "action": e.action_taken.value,
                    "escalated_to": e.escalated_to,
                    "reason": e.reason,
                }
                for e in events
            ],
        }


class ResolveEscalationRequest(BaseModel):
    """Request to resolve escalation."""

    resolution_notes: str = ""


@router.post("/leads/{lead_id}/escalations/resolve")
async def resolve_escalation(lead_id: str, request: ResolveEscalationRequest):
    """Resolve escalation for a lead."""
    engine = get_escalation_engine()
    if engine.resolve_escalation(lead_id, request.resolution_notes):
        return {
            "message": "Escalation resolved",
            "business_id": lead_id,
            "notes": request.resolution_notes,
        }
    raise HTTPException(status_code=404, detail="No active escalation for this lead")


@router.get("/leads/{lead_id}/escalations/history")
async def get_escalation_history(lead_id: str):
    """Get escalation history for a lead."""
    engine = get_escalation_engine()
    history = engine.get_escalation_history(lead_id)

    return {
        "business_id": lead_id,
        "history": [
            {
                "id": e.id,
                "trigger": e.trigger.value,
                "action": e.action_taken.value,
                "escalated_to": e.escalated_to,
                "reason": e.reason,
                "created_at": e.created_at.isoformat(),
                "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
                "resolution_notes": e.resolution_notes,
            }
            for e in history
        ],
    }


# === Assignment Routes ===


@router.get("/agents")
async def list_agents():
    """Get all agents."""
    engine = get_assignment_engine()

    return {
        "agents": [
            {
                "id": agent.id,
                "name": agent.name,
                "email": agent.email,
                "territory_states": agent.territory_states,
                "specialist_industries": agent.specialist_industries,
                "close_rate": agent.close_rate,
                "avg_deal_size": agent.avg_deal_size,
                "is_available": agent.has_capacity,
            }
            for agent in engine.agents.values()
        ],
    }


@router.get("/agents/workloads")
async def get_agent_workloads():
    """Get workload summary for all agents."""
    engine = get_assignment_engine()
    return {"workloads": engine.get_all_workloads()}


@router.get("/agents/{agent_id}/workload")
async def get_agent_workload(agent_id: str):
    """Get workload for a specific agent."""
    engine = get_assignment_engine()
    workload = engine.get_agent_workload(agent_id)

    if not workload:
        raise HTTPException(status_code=404, detail="Agent not found")

    return workload


@router.post("/leads/{lead_id}/assign")
async def assign_lead_to_agent(
    lead_id: str,
    agent_id: Optional[str] = None,
):
    """
    Assign a lead to an agent.

    If no agent_id is provided, automatically assigns to best available agent.
    """
    async with get_session() as session:
        business_repo = BusinessRepository(session)
        signal_repo = SignalRepository(session)

        business = await business_repo.get_by_id(lead_id)
        if not business:
            raise HTTPException(status_code=404, detail="Lead not found")

        signals = await signal_repo.get_signals_by_business(lead_id)

        # Get deal size estimate
        deal_engine = get_deal_intelligence()
        deal_size = deal_engine.estimate_deal_size(business, signals)

        engine = get_assignment_engine()

        result = engine.assign_lead(
            business_id=lead_id,
            state=business.state or "",
            city=business.city,
            industry=business.industry,
            priority=business.priority,
            deal_size_estimate=deal_size.likely_amount,
        )

        if not result:
            raise HTTPException(
                status_code=400,
                detail="No suitable agent available for assignment",
            )

        # Update business record
        business.assigned_to = result.agent_name

        return {
            "message": "Lead assigned",
            "business_id": lead_id,
            "assigned_to": result.agent_name,
            "assignment_score": result.assignment_score,
            "reason": result.assignment_reason,
        }


class ReassignRequest(BaseModel):
    """Request to reassign lead."""

    reason: str = ""


@router.post("/leads/{lead_id}/reassign")
async def reassign_lead(lead_id: str, request: ReassignRequest):
    """Reassign a lead to a different agent."""
    async with get_session() as session:
        business_repo = BusinessRepository(session)
        signal_repo = SignalRepository(session)

        business = await business_repo.get_by_id(lead_id)
        if not business:
            raise HTTPException(status_code=404, detail="Lead not found")

        if not business.assigned_to:
            raise HTTPException(status_code=400, detail="Lead is not currently assigned")

        signals = await signal_repo.get_signals_by_business(lead_id)

        deal_engine = get_deal_intelligence()
        deal_size = deal_engine.estimate_deal_size(business, signals)

        engine = get_assignment_engine()

        # Find current agent ID
        current_agent_id = None
        for agent_id, agent in engine.agents.items():
            if agent.name == business.assigned_to:
                current_agent_id = agent_id
                break

        if not current_agent_id:
            raise HTTPException(status_code=400, detail="Current agent not found")

        result = engine.reassign_lead(
            business_id=lead_id,
            current_agent_id=current_agent_id,
            state=business.state or "",
            city=business.city,
            industry=business.industry,
            priority=business.priority,
            deal_size_estimate=deal_size.likely_amount,
            reason=request.reason,
        )

        if not result:
            raise HTTPException(
                status_code=400,
                detail="No alternative agent available",
            )

        # Update business record
        business.assigned_to = result.agent_name

        return {
            "message": "Lead reassigned",
            "business_id": lead_id,
            "assigned_to": result.agent_name,
            "reason": result.assignment_reason,
        }


@router.get("/assignments/analytics")
async def get_assignment_analytics():
    """Get assignment analytics."""
    engine = get_assignment_engine()
    return engine.get_assignment_analytics()
