"""
Follow-Up Sequences
===================

Automated multi-step follow-up sequences for lead nurturing.
Ensures no lead falls through the cracks with consistent outreach.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from uuid import uuid4

import structlog

from industry_deep_scan.models import SignalType, SignalPriority

logger = structlog.get_logger()


class ContactChannel(str, Enum):
    """Contact channels for outreach."""

    PHONE = "phone"
    EMAIL = "email"
    SMS = "sms"
    LINKEDIN = "linkedin"
    VOICEMAIL_DROP = "voicemail_drop"


class StepTrigger(str, Enum):
    """Triggers for moving to next step."""

    TIME_ELAPSED = "time_elapsed"
    NO_RESPONSE = "no_response"
    VOICEMAIL_LEFT = "voicemail_left"
    EMAIL_NOT_OPENED = "email_not_opened"
    EMAIL_OPENED_NO_REPLY = "email_opened_no_reply"


class StepOutcome(str, Enum):
    """Possible outcomes of a sequence step."""

    PENDING = "pending"
    COMPLETED = "completed"
    CONNECTED = "connected"
    VOICEMAIL = "voicemail"
    NO_ANSWER = "no_answer"
    EMAIL_SENT = "email_sent"
    EMAIL_OPENED = "email_opened"
    EMAIL_CLICKED = "email_clicked"
    EMAIL_REPLIED = "email_replied"
    SMS_SENT = "sms_sent"
    SMS_REPLIED = "sms_replied"
    LINKEDIN_SENT = "linkedin_sent"
    LINKEDIN_ACCEPTED = "linkedin_accepted"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class SequenceStep:
    """Single step in a follow-up sequence."""

    step_number: int
    channel: ContactChannel
    delay_hours: int  # Hours after previous step
    template_key: str  # Reference to message template
    subject: Optional[str] = None  # For email
    escalation_trigger: Optional[StepTrigger] = None
    max_attempts: int = 1
    notes: str = ""


@dataclass
class FollowUpSequence:
    """Complete follow-up sequence definition."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    signal_types: list[SignalType] = field(default_factory=list)
    priority_levels: list[SignalPriority] = field(default_factory=list)
    steps: list[SequenceStep] = field(default_factory=list)
    total_duration_days: int = 21
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def step_count(self) -> int:
        return len(self.steps)


@dataclass
class LeadSequenceState:
    """Tracks a lead's progress through a sequence."""

    id: str = field(default_factory=lambda: str(uuid4()))
    business_id: str = ""
    sequence_id: str = ""
    current_step: int = 1
    status: str = "active"  # active, completed, paused, stopped
    started_at: datetime = field(default_factory=datetime.utcnow)
    next_action_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    step_outcomes: dict = field(default_factory=dict)  # step_number -> outcome


class SequenceEngine:
    """
    Manages automated follow-up sequences.

    Features:
    - Multi-step sequences with various channels
    - Automatic progression based on outcomes
    - Template-based messaging
    - Escalation handling
    """

    def __init__(self):
        self.sequences: dict[str, FollowUpSequence] = {}
        self.lead_states: dict[str, LeadSequenceState] = {}  # business_id -> state
        self._init_default_sequences()

    def _init_default_sequences(self):
        """Initialize default follow-up sequences."""

        # Tax Lien - Urgent 14-day sequence
        tax_lien_sequence = FollowUpSequence(
            name="Tax Lien Urgent Outreach",
            description="Fast-paced sequence for tax lien signals",
            signal_types=[SignalType.TAX_LIEN, SignalType.JUDGMENT],
            priority_levels=[SignalPriority.CRITICAL, SignalPriority.HIGH],
            total_duration_days=14,
            steps=[
                SequenceStep(
                    step_number=1,
                    channel=ContactChannel.PHONE,
                    delay_hours=0,
                    template_key="tax_lien_initial_call",
                    escalation_trigger=StepTrigger.VOICEMAIL_LEFT,
                    notes="Immediate call - emphasize urgency",
                ),
                SequenceStep(
                    step_number=2,
                    channel=ContactChannel.VOICEMAIL_DROP,
                    delay_hours=2,
                    template_key="tax_lien_voicemail",
                    escalation_trigger=StepTrigger.TIME_ELAPSED,
                    notes="Professional voicemail if no answer",
                ),
                SequenceStep(
                    step_number=3,
                    channel=ContactChannel.EMAIL,
                    delay_hours=4,
                    template_key="tax_lien_initial_email",
                    subject="Quick Solution for Your Tax Situation - {business_name}",
                    escalation_trigger=StepTrigger.EMAIL_NOT_OPENED,
                ),
                SequenceStep(
                    step_number=4,
                    channel=ContactChannel.PHONE,
                    delay_hours=24,
                    template_key="tax_lien_followup_call",
                    escalation_trigger=StepTrigger.NO_RESPONSE,
                    notes="Second attempt - different time of day",
                ),
                SequenceStep(
                    step_number=5,
                    channel=ContactChannel.SMS,
                    delay_hours=48,
                    template_key="tax_lien_sms",
                    escalation_trigger=StepTrigger.TIME_ELAPSED,
                ),
                SequenceStep(
                    step_number=6,
                    channel=ContactChannel.EMAIL,
                    delay_hours=72,
                    template_key="tax_lien_urgency_email",
                    subject="Time-Sensitive: Funding Available for {business_name}",
                    escalation_trigger=StepTrigger.EMAIL_NOT_OPENED,
                ),
                SequenceStep(
                    step_number=7,
                    channel=ContactChannel.PHONE,
                    delay_hours=120,
                    template_key="tax_lien_final_call",
                    escalation_trigger=StepTrigger.NO_RESPONSE,
                    notes="Final attempt before manager escalation",
                ),
                SequenceStep(
                    step_number=8,
                    channel=ContactChannel.LINKEDIN,
                    delay_hours=168,
                    template_key="tax_lien_linkedin",
                    notes="LinkedIn connection request with note",
                ),
            ],
        )
        self.sequences[tax_lien_sequence.id] = tax_lien_sequence

        # Growth Signal - Consultative 21-day sequence
        growth_sequence = FollowUpSequence(
            name="Growth Opportunity Nurture",
            description="Longer nurture sequence for growth signals",
            signal_types=[
                SignalType.RAPID_GROWTH, SignalType.EXPANSION,
                SignalType.HIRING_SURGE, SignalType.NEW_LOCATION,
            ],
            priority_levels=[SignalPriority.HIGH, SignalPriority.MEDIUM],
            total_duration_days=21,
            steps=[
                SequenceStep(
                    step_number=1,
                    channel=ContactChannel.PHONE,
                    delay_hours=0,
                    template_key="growth_initial_call",
                    escalation_trigger=StepTrigger.VOICEMAIL_LEFT,
                    notes="Congratulatory tone - celebrate their growth",
                ),
                SequenceStep(
                    step_number=2,
                    channel=ContactChannel.EMAIL,
                    delay_hours=24,
                    template_key="growth_value_email",
                    subject="Congrats on the Growth, {first_name}! Quick Question...",
                    escalation_trigger=StepTrigger.EMAIL_NOT_OPENED,
                ),
                SequenceStep(
                    step_number=3,
                    channel=ContactChannel.PHONE,
                    delay_hours=72,
                    template_key="growth_followup_call",
                    escalation_trigger=StepTrigger.NO_RESPONSE,
                ),
                SequenceStep(
                    step_number=4,
                    channel=ContactChannel.EMAIL,
                    delay_hours=120,
                    template_key="growth_case_study_email",
                    subject="How {similar_company} Scaled with Growth Capital",
                    escalation_trigger=StepTrigger.EMAIL_NOT_OPENED,
                    notes="Include relevant industry case study",
                ),
                SequenceStep(
                    step_number=5,
                    channel=ContactChannel.LINKEDIN,
                    delay_hours=168,
                    template_key="growth_linkedin_connect",
                    notes="Personal connection request",
                ),
                SequenceStep(
                    step_number=6,
                    channel=ContactChannel.PHONE,
                    delay_hours=240,
                    template_key="growth_check_in_call",
                    escalation_trigger=StepTrigger.NO_RESPONSE,
                ),
                SequenceStep(
                    step_number=7,
                    channel=ContactChannel.EMAIL,
                    delay_hours=336,
                    template_key="growth_final_email",
                    subject="Still thinking about growth capital, {first_name}?",
                    escalation_trigger=StepTrigger.EMAIL_NOT_OPENED,
                ),
                SequenceStep(
                    step_number=8,
                    channel=ContactChannel.SMS,
                    delay_hours=408,
                    template_key="growth_final_sms",
                    notes="Casual check-in SMS",
                ),
            ],
        )
        self.sequences[growth_sequence.id] = growth_sequence

        # Cash Flow - Medium urgency 14-day sequence
        cashflow_sequence = FollowUpSequence(
            name="Cash Flow Solution",
            description="Balanced sequence for cash flow signals",
            signal_types=[
                SignalType.CASH_SQUEEZE, SignalType.PAYMENT_DELAY,
                SignalType.INVENTORY_NEED, SignalType.SEASONAL_RAMP,
            ],
            priority_levels=[SignalPriority.HIGH, SignalPriority.MEDIUM],
            total_duration_days=14,
            steps=[
                SequenceStep(
                    step_number=1,
                    channel=ContactChannel.PHONE,
                    delay_hours=0,
                    template_key="cashflow_initial_call",
                    escalation_trigger=StepTrigger.VOICEMAIL_LEFT,
                ),
                SequenceStep(
                    step_number=2,
                    channel=ContactChannel.EMAIL,
                    delay_hours=4,
                    template_key="cashflow_intro_email",
                    subject="Working Capital Solution for {business_name}",
                    escalation_trigger=StepTrigger.EMAIL_NOT_OPENED,
                ),
                SequenceStep(
                    step_number=3,
                    channel=ContactChannel.PHONE,
                    delay_hours=48,
                    template_key="cashflow_followup_call",
                    escalation_trigger=StepTrigger.NO_RESPONSE,
                ),
                SequenceStep(
                    step_number=4,
                    channel=ContactChannel.SMS,
                    delay_hours=72,
                    template_key="cashflow_sms",
                    escalation_trigger=StepTrigger.TIME_ELAPSED,
                ),
                SequenceStep(
                    step_number=5,
                    channel=ContactChannel.EMAIL,
                    delay_hours=120,
                    template_key="cashflow_benefits_email",
                    subject="Why Business Owners Choose MCA for Cash Flow",
                    escalation_trigger=StepTrigger.EMAIL_NOT_OPENED,
                ),
                SequenceStep(
                    step_number=6,
                    channel=ContactChannel.PHONE,
                    delay_hours=192,
                    template_key="cashflow_final_call",
                    escalation_trigger=StepTrigger.NO_RESPONSE,
                ),
            ],
        )
        self.sequences[cashflow_sequence.id] = cashflow_sequence

    def get_sequence_for_signal(
        self,
        signal_type: SignalType,
        priority: SignalPriority,
    ) -> Optional[FollowUpSequence]:
        """Find the best matching sequence for a signal."""
        for sequence in self.sequences.values():
            if not sequence.is_active:
                continue
            if signal_type in sequence.signal_types and priority in sequence.priority_levels:
                return sequence

        # Return generic sequence if no match
        return None

    def start_sequence(
        self,
        business_id: str,
        sequence: FollowUpSequence,
    ) -> LeadSequenceState:
        """Start a lead on a follow-up sequence."""
        state = LeadSequenceState(
            business_id=business_id,
            sequence_id=sequence.id,
            current_step=1,
            status="active",
            started_at=datetime.utcnow(),
            next_action_at=datetime.utcnow(),  # Start immediately
        )
        self.lead_states[business_id] = state

        logger.info(
            "Started sequence",
            business_id=business_id,
            sequence_name=sequence.name,
            total_steps=sequence.step_count,
        )

        return state

    def advance_sequence(
        self,
        business_id: str,
        outcome: StepOutcome,
    ) -> Optional[SequenceStep]:
        """
        Advance to next step based on outcome.

        Returns the next step to execute, or None if sequence is complete.
        """
        if business_id not in self.lead_states:
            return None

        state = self.lead_states[business_id]
        sequence = self.sequences.get(state.sequence_id)

        if not sequence or state.status != "active":
            return None

        # Record outcome for current step
        state.step_outcomes[state.current_step] = outcome.value

        # Check if connected - sequence complete
        if outcome in [
            StepOutcome.CONNECTED,
            StepOutcome.EMAIL_REPLIED,
            StepOutcome.SMS_REPLIED,
            StepOutcome.LINKEDIN_ACCEPTED,
        ]:
            state.status = "completed"
            state.completed_at = datetime.utcnow()
            logger.info(
                "Sequence completed - contact established",
                business_id=business_id,
                outcome=outcome.value,
            )
            return None

        # Move to next step
        state.current_step += 1

        if state.current_step > sequence.step_count:
            state.status = "completed"
            state.completed_at = datetime.utcnow()
            logger.info(
                "Sequence completed - all steps exhausted",
                business_id=business_id,
            )
            return None

        # Get next step and calculate timing
        next_step = sequence.steps[state.current_step - 1]
        state.next_action_at = datetime.utcnow() + timedelta(hours=next_step.delay_hours)

        logger.info(
            "Advanced to next step",
            business_id=business_id,
            step_number=state.current_step,
            channel=next_step.channel.value,
            next_action_at=state.next_action_at.isoformat(),
        )

        return next_step

    def get_pending_actions(self) -> list[tuple[str, SequenceStep]]:
        """Get all pending sequence actions that are due."""
        pending = []
        now = datetime.utcnow()

        for business_id, state in self.lead_states.items():
            if state.status != "active":
                continue
            if state.next_action_at and state.next_action_at <= now:
                sequence = self.sequences.get(state.sequence_id)
                if sequence and state.current_step <= sequence.step_count:
                    step = sequence.steps[state.current_step - 1]
                    pending.append((business_id, step))

        return pending

    def pause_sequence(self, business_id: str) -> bool:
        """Pause a sequence for a lead."""
        if business_id in self.lead_states:
            self.lead_states[business_id].status = "paused"
            return True
        return False

    def resume_sequence(self, business_id: str) -> bool:
        """Resume a paused sequence."""
        if business_id in self.lead_states:
            state = self.lead_states[business_id]
            if state.status == "paused":
                state.status = "active"
                state.next_action_at = datetime.utcnow()
                return True
        return False

    def stop_sequence(self, business_id: str, reason: str = "") -> bool:
        """Stop a sequence permanently."""
        if business_id in self.lead_states:
            state = self.lead_states[business_id]
            state.status = "stopped"
            state.completed_at = datetime.utcnow()
            logger.info(
                "Sequence stopped",
                business_id=business_id,
                reason=reason,
            )
            return True
        return False

    def get_sequence_status(self, business_id: str) -> Optional[dict]:
        """Get current sequence status for a lead."""
        if business_id not in self.lead_states:
            return None

        state = self.lead_states[business_id]
        sequence = self.sequences.get(state.sequence_id)

        return {
            "business_id": business_id,
            "sequence_name": sequence.name if sequence else "Unknown",
            "status": state.status,
            "current_step": state.current_step,
            "total_steps": sequence.step_count if sequence else 0,
            "started_at": state.started_at.isoformat(),
            "next_action_at": state.next_action_at.isoformat() if state.next_action_at else None,
            "completed_at": state.completed_at.isoformat() if state.completed_at else None,
            "step_outcomes": state.step_outcomes,
        }


# Message templates (simplified - in production these would be in DB)
MESSAGE_TEMPLATES = {
    # Tax Lien Templates
    "tax_lien_initial_call": """
Hi {first_name}, this is {agent_name} from {company_name}.

I'm calling because I work with businesses dealing with tax situations, and I may have a quick solution that could help you resolve things faster.

We provide working capital within 48-72 hours - often the fastest way to get back in good standing.

Do you have 2 minutes to discuss your options?
""",
    "tax_lien_voicemail": """
Hi {first_name}, this is {agent_name} from {company_name}.

I'm reaching out because I specialize in helping businesses resolve tax situations quickly with fast working capital.

If you're looking for options, give me a call back at {agent_phone}. I can usually get businesses funded within 48 hours.

Again, that's {agent_phone}. Talk soon.
""",
    "tax_lien_initial_email": """
Hi {first_name},

I noticed {business_name} may be dealing with some tax complications. I work with business owners in similar situations every day, and I wanted to reach out because I may be able to help.

We provide working capital quickly - often within 48-72 hours - which many of our clients use to resolve tax situations and get back to focusing on their business.

Here's how it works:
- Quick application (10 minutes)
- Approval within hours
- Funding within 1-3 business days
- Flexible repayment tied to your revenue

Would you be open to a quick 10-minute call to discuss your options?

Best,
{agent_name}
{agent_phone}
""",
    # Growth Templates
    "growth_initial_call": """
Hi {first_name}, this is {agent_name} from {company_name}.

I'm calling to congratulate you - I noticed {business_name} is really growing! That's exciting.

I work with expanding businesses to provide growth capital for things like inventory, equipment, and hiring. Many of our clients use us to bridge the gap when revenue hasn't caught up with growth costs yet.

Is that something you're dealing with right now?
""",
    "growth_value_email": """
Hi {first_name},

Congratulations on the growth at {business_name}! I noticed some exciting things happening and wanted to reach out.

I work with growing businesses to provide working capital for:
- Inventory to meet increased demand
- Equipment upgrades
- Hiring and payroll during expansion
- New location costs

The challenge with growth is that expenses often come before revenue catches up. That's exactly what we help with.

Would you be open to a quick conversation about your growth plans?

Best,
{agent_name}
""",
    # Cash Flow Templates
    "cashflow_initial_call": """
Hi {first_name}, this is {agent_name} from {company_name}.

I work with business owners in the {industry} industry who need flexible working capital.

A lot of my clients use us to smooth out cash flow - whether it's covering payroll, inventory, or just having a cushion for slower periods.

Is cash flow something you've been thinking about lately?
""",
    "cashflow_intro_email": """
Hi {first_name},

Running a business means constantly juggling cash flow - I get it. That's why I wanted to reach out.

We provide working capital that gives you breathing room:
- Fund within 48-72 hours
- Repayment flexes with your revenue
- No fixed monthly payments to stress about
- Use for any business purpose

If you're interested in exploring your options, I'd love to have a quick conversation.

Best,
{agent_name}
{agent_phone}
""",
    # SMS Templates
    "tax_lien_sms": """
Hi {first_name}, {agent_name} here. Following up on my voicemail about working capital options for {business_name}. Can help resolve things quickly. Good time for a 5-min call? Reply CALL and I'll ring you.
""",
    "growth_final_sms": """
Hi {first_name}! Just checking in on {business_name}. Still happy to discuss growth capital if helpful. No pressure - let me know if timing is better later. - {agent_name}
""",
    "cashflow_sms": """
Hi {first_name}, following up on working capital for {business_name}. Quick funding available if you need cash flow help. Reply CALL if you'd like to chat. - {agent_name}
""",
    # LinkedIn Templates
    "tax_lien_linkedin": """
Hi {first_name}, I noticed {business_name} and wanted to connect. I work with business owners in similar situations and may have some helpful options. Would love to connect and share some ideas when the timing is right.
""",
    "growth_linkedin_connect": """
Hi {first_name}, congratulations on the growth at {business_name}! I work with expanding businesses and would love to connect. Always great to know local business owners in the {industry} space.
""",
}


def get_template(template_key: str, **variables) -> str:
    """Get and fill a message template."""
    template = MESSAGE_TEMPLATES.get(template_key, "")
    try:
        return template.format(**variables)
    except KeyError:
        return template
