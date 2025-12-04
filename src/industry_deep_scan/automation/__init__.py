"""
Automation Modules
==================

Automated workflows for lead management, follow-ups, and escalations.
"""

from industry_deep_scan.automation.sequences import (
    FollowUpSequence,
    SequenceStep,
    SequenceEngine,
    ContactChannel,
    StepTrigger,
)
from industry_deep_scan.automation.escalation import (
    EscalationRule,
    EscalationEngine,
    EscalationTrigger,
)
from industry_deep_scan.automation.assignment import (
    AssignmentRule,
    AssignmentEngine,
    AgentProfile,
)

__all__ = [
    # Sequences
    "FollowUpSequence",
    "SequenceStep",
    "SequenceEngine",
    "ContactChannel",
    "StepTrigger",
    # Escalation
    "EscalationRule",
    "EscalationEngine",
    "EscalationTrigger",
    # Assignment
    "AssignmentRule",
    "AssignmentEngine",
    "AgentProfile",
]
