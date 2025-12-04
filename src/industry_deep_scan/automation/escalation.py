"""
Escalation Rules Engine
=======================

Smart escalation rules to ensure high-value leads get management attention.
Prevents leads from going stale and enforces SLAs.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Callable
from uuid import uuid4

import structlog

from industry_deep_scan.models import SignalPriority, LeadStatus

logger = structlog.get_logger()


class EscalationTrigger(str, Enum):
    """Conditions that trigger escalation."""

    # Time-based
    NO_CONTACT_CRITICAL = "no_contact_critical"  # Critical lead not contacted
    NO_CONTACT_HIGH = "no_contact_high"  # High lead not contacted
    STALE_LEAD = "stale_lead"  # Lead stuck in stage too long
    NO_FOLLOW_UP = "no_follow_up"  # Follow-up overdue

    # Value-based
    HIGH_VALUE_UNASSIGNED = "high_value_unassigned"  # Big deal sitting idle
    MULTIPLE_SIGNALS = "multiple_signals"  # Lead with 3+ signals
    DECLINING_SCORE = "declining_score"  # Score dropped significantly

    # Outcome-based
    CONTACT_FAILED = "contact_failed"  # Multiple contact attempts failed
    COMPETITOR_DETECTED = "competitor_detected"  # Competitor activity seen
    URGENT_RESPONSE = "urgent_response"  # Lead responded urgently


class EscalationAction(str, Enum):
    """Actions to take on escalation."""

    ALERT_MANAGER = "alert_manager"
    REASSIGN_TOP_CLOSER = "reassign_top_closer"
    ADD_TO_PRIORITY_QUEUE = "add_to_priority_queue"
    SEND_SLACK_ALERT = "send_slack_alert"
    MANAGER_TAKEOVER = "manager_takeover"
    FLAG_FOR_REVIEW = "flag_for_review"


@dataclass
class EscalationRule:
    """Definition of an escalation rule."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    trigger: EscalationTrigger = EscalationTrigger.STALE_LEAD
    conditions: dict = field(default_factory=dict)
    action: EscalationAction = EscalationAction.ALERT_MANAGER
    target_role: str = "manager"  # Who gets notified/assigned
    priority: int = 1  # Higher = more important
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class EscalationEvent:
    """Record of an escalation that occurred."""

    id: str = field(default_factory=lambda: str(uuid4()))
    business_id: str = ""
    rule_id: str = ""
    trigger: EscalationTrigger = EscalationTrigger.STALE_LEAD
    action_taken: EscalationAction = EscalationAction.ALERT_MANAGER
    escalated_to: str = ""
    reason: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    resolution_notes: str = ""


@dataclass
class LeadEscalationState:
    """Current escalation state for a lead."""

    business_id: str
    is_escalated: bool = False
    escalation_level: int = 0  # 0 = not escalated, 1+ = escalation levels
    escalated_to: Optional[str] = None
    escalated_at: Optional[datetime] = None
    escalation_reason: Optional[str] = None
    pending_actions: list[EscalationAction] = field(default_factory=list)


class EscalationEngine:
    """
    Manages escalation rules and their execution.

    Monitors leads for escalation conditions and triggers appropriate actions.
    """

    def __init__(self):
        self.rules: dict[str, EscalationRule] = {}
        self.escalation_events: list[EscalationEvent] = []
        self.lead_states: dict[str, LeadEscalationState] = {}
        self._init_default_rules()

    def _init_default_rules(self):
        """Initialize default escalation rules."""

        # Critical lead not contacted within 2 hours
        rule1 = EscalationRule(
            name="Critical Lead SLA",
            description="Escalate CRITICAL leads not contacted within 2 hours",
            trigger=EscalationTrigger.NO_CONTACT_CRITICAL,
            conditions={
                "priority": SignalPriority.CRITICAL.value,
                "max_hours": 2,
                "status": LeadStatus.NEW.value,
            },
            action=EscalationAction.ALERT_MANAGER,
            target_role="manager",
            priority=10,
        )
        self.rules[rule1.id] = rule1

        # High lead not contacted within 24 hours
        rule2 = EscalationRule(
            name="High Lead SLA",
            description="Escalate HIGH leads not contacted within 24 hours",
            trigger=EscalationTrigger.NO_CONTACT_HIGH,
            conditions={
                "priority": SignalPriority.HIGH.value,
                "max_hours": 24,
                "status": LeadStatus.NEW.value,
            },
            action=EscalationAction.ADD_TO_PRIORITY_QUEUE,
            target_role="senior_agent",
            priority=8,
        )
        self.rules[rule2.id] = rule2

        # Lead stuck in status for too long
        rule3 = EscalationRule(
            name="Stale Lead",
            description="Escalate leads in same status for 7+ days",
            trigger=EscalationTrigger.STALE_LEAD,
            conditions={
                "max_days_in_status": 7,
                "statuses": [LeadStatus.NEW.value, LeadStatus.CONTACTED.value],
            },
            action=EscalationAction.FLAG_FOR_REVIEW,
            target_role="manager",
            priority=5,
        )
        self.rules[rule3.id] = rule3

        # High-value deal unassigned
        rule4 = EscalationRule(
            name="High Value Unassigned",
            description="Escalate deals >$200K without assignment",
            trigger=EscalationTrigger.HIGH_VALUE_UNASSIGNED,
            conditions={
                "min_deal_size": 200000,
                "max_unassigned_hours": 4,
            },
            action=EscalationAction.REASSIGN_TOP_CLOSER,
            target_role="top_closer",
            priority=9,
        )
        self.rules[rule4.id] = rule4

        # Multiple signals - hot lead
        rule5 = EscalationRule(
            name="Multi-Signal Hot Lead",
            description="Escalate leads with 3+ signals for priority handling",
            trigger=EscalationTrigger.MULTIPLE_SIGNALS,
            conditions={
                "min_signals": 3,
                "status": LeadStatus.NEW.value,
            },
            action=EscalationAction.ADD_TO_PRIORITY_QUEUE,
            target_role="senior_agent",
            priority=7,
        )
        self.rules[rule5.id] = rule5

        # Failed contact attempts
        rule6 = EscalationRule(
            name="Contact Failed",
            description="Escalate after 5 failed contact attempts",
            trigger=EscalationTrigger.CONTACT_FAILED,
            conditions={
                "max_failed_attempts": 5,
            },
            action=EscalationAction.MANAGER_TAKEOVER,
            target_role="manager",
            priority=6,
        )
        self.rules[rule6.id] = rule6

        # Follow-up overdue
        rule7 = EscalationRule(
            name="Overdue Follow-up",
            description="Escalate when follow-up is 2+ days overdue",
            trigger=EscalationTrigger.NO_FOLLOW_UP,
            conditions={
                "days_overdue": 2,
            },
            action=EscalationAction.SEND_SLACK_ALERT,
            target_role="assigned_agent",
            priority=4,
        )
        self.rules[rule7.id] = rule7

    def check_escalation(
        self,
        business_id: str,
        priority: SignalPriority,
        status: LeadStatus,
        created_at: datetime,
        assigned_to: Optional[str],
        signal_count: int,
        deal_size_estimate: float,
        contact_attempts: int,
        last_contacted: Optional[datetime],
        next_follow_up: Optional[datetime],
    ) -> list[EscalationEvent]:
        """
        Check if a lead should be escalated based on current state.

        Returns list of escalation events to process.
        """
        events = []
        now = datetime.utcnow()

        for rule in sorted(self.rules.values(), key=lambda r: -r.priority):
            if not rule.is_active:
                continue

            should_escalate = False
            reason = ""

            if rule.trigger == EscalationTrigger.NO_CONTACT_CRITICAL:
                if (
                    priority == SignalPriority.CRITICAL
                    and status == LeadStatus.NEW
                    and not last_contacted
                ):
                    hours_since_created = (now - created_at).total_seconds() / 3600
                    max_hours = rule.conditions.get("max_hours", 2)
                    if hours_since_created > max_hours:
                        should_escalate = True
                        reason = f"CRITICAL lead not contacted in {hours_since_created:.1f} hours"

            elif rule.trigger == EscalationTrigger.NO_CONTACT_HIGH:
                if (
                    priority == SignalPriority.HIGH
                    and status == LeadStatus.NEW
                    and not last_contacted
                ):
                    hours_since_created = (now - created_at).total_seconds() / 3600
                    max_hours = rule.conditions.get("max_hours", 24)
                    if hours_since_created > max_hours:
                        should_escalate = True
                        reason = f"HIGH lead not contacted in {hours_since_created:.1f} hours"

            elif rule.trigger == EscalationTrigger.HIGH_VALUE_UNASSIGNED:
                min_deal = rule.conditions.get("min_deal_size", 200000)
                max_hours = rule.conditions.get("max_unassigned_hours", 4)
                if deal_size_estimate >= min_deal and not assigned_to:
                    hours_since_created = (now - created_at).total_seconds() / 3600
                    if hours_since_created > max_hours:
                        should_escalate = True
                        reason = f"${deal_size_estimate:,.0f} deal unassigned for {hours_since_created:.1f} hours"

            elif rule.trigger == EscalationTrigger.MULTIPLE_SIGNALS:
                min_signals = rule.conditions.get("min_signals", 3)
                if signal_count >= min_signals and status == LeadStatus.NEW:
                    should_escalate = True
                    reason = f"Lead has {signal_count} signals - needs priority handling"

            elif rule.trigger == EscalationTrigger.CONTACT_FAILED:
                max_failed = rule.conditions.get("max_failed_attempts", 5)
                if contact_attempts >= max_failed:
                    should_escalate = True
                    reason = f"{contact_attempts} failed contact attempts"

            elif rule.trigger == EscalationTrigger.NO_FOLLOW_UP:
                if next_follow_up and status == LeadStatus.CONTACTED:
                    days_overdue = (now - next_follow_up).days
                    min_overdue = rule.conditions.get("days_overdue", 2)
                    if days_overdue >= min_overdue:
                        should_escalate = True
                        reason = f"Follow-up {days_overdue} days overdue"

            if should_escalate:
                # Check if already escalated for this rule
                existing = self.lead_states.get(business_id)
                if existing and existing.escalation_reason == reason:
                    continue

                event = EscalationEvent(
                    business_id=business_id,
                    rule_id=rule.id,
                    trigger=rule.trigger,
                    action_taken=rule.action,
                    escalated_to=rule.target_role,
                    reason=reason,
                )
                events.append(event)

                # Update lead state
                self.lead_states[business_id] = LeadEscalationState(
                    business_id=business_id,
                    is_escalated=True,
                    escalation_level=existing.escalation_level + 1 if existing else 1,
                    escalated_to=rule.target_role,
                    escalated_at=now,
                    escalation_reason=reason,
                    pending_actions=[rule.action],
                )

                logger.warning(
                    "Lead escalated",
                    business_id=business_id,
                    trigger=rule.trigger.value,
                    action=rule.action.value,
                    reason=reason,
                )

        return events

    def resolve_escalation(
        self,
        business_id: str,
        resolution_notes: str = "",
    ) -> bool:
        """Mark escalation as resolved."""
        if business_id not in self.lead_states:
            return False

        state = self.lead_states[business_id]
        state.is_escalated = False
        state.pending_actions = []

        # Find and update event
        for event in reversed(self.escalation_events):
            if event.business_id == business_id and not event.resolved_at:
                event.resolved_at = datetime.utcnow()
                event.resolution_notes = resolution_notes
                break

        logger.info(
            "Escalation resolved",
            business_id=business_id,
            notes=resolution_notes,
        )

        return True

    def get_escalated_leads(self) -> list[LeadEscalationState]:
        """Get all currently escalated leads."""
        return [
            state for state in self.lead_states.values()
            if state.is_escalated
        ]

    def get_escalation_history(
        self,
        business_id: str,
    ) -> list[EscalationEvent]:
        """Get escalation history for a lead."""
        return [
            event for event in self.escalation_events
            if event.business_id == business_id
        ]

    def add_rule(self, rule: EscalationRule) -> str:
        """Add a custom escalation rule."""
        self.rules[rule.id] = rule
        return rule.id

    def disable_rule(self, rule_id: str) -> bool:
        """Disable an escalation rule."""
        if rule_id in self.rules:
            self.rules[rule_id].is_active = False
            return True
        return False

    def get_rules(self) -> list[EscalationRule]:
        """Get all escalation rules."""
        return list(self.rules.values())
