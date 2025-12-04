"""
Intelligent Lead Assignment
===========================

Smart lead assignment based on agent specialization, territory, and capacity.
Gets leads to the right closer at the right time.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

import structlog

from industry_deep_scan.models import SignalPriority

logger = structlog.get_logger()


@dataclass
class AgentProfile:
    """Agent/closer profile for assignment."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    email: str = ""
    phone: str = ""

    # Territory
    territory_states: list[str] = field(default_factory=list)
    territory_cities: list[str] = field(default_factory=list)

    # Specialization
    specialist_industries: list[str] = field(default_factory=list)
    specialist_signals: list[str] = field(default_factory=list)  # Signal types

    # Performance metrics
    close_rate: float = 0.0  # Historical close rate
    avg_deal_size: float = 0.0  # Average deal they close
    total_deals_closed: int = 0

    # Capacity
    max_daily_assignments: int = 20
    current_daily_assignments: int = 0
    max_active_leads: int = 50
    current_active_leads: int = 0

    # Availability
    is_active: bool = True
    is_available: bool = True  # Current availability
    next_available_at: Optional[datetime] = None

    # Preferences
    min_deal_size: float = 0  # Minimum deal they want
    max_deal_size: float = float("inf")  # Maximum deal they can handle

    # Scoring
    specialization_multiplier: float = 1.0  # Bonus for specialization

    @property
    def has_capacity(self) -> bool:
        """Check if agent has capacity for new leads."""
        return (
            self.is_active
            and self.is_available
            and self.current_daily_assignments < self.max_daily_assignments
            and self.current_active_leads < self.max_active_leads
        )

    @property
    def capacity_score(self) -> float:
        """Score based on available capacity (0-1)."""
        if not self.has_capacity:
            return 0.0
        daily_remaining = 1 - (self.current_daily_assignments / self.max_daily_assignments)
        active_remaining = 1 - (self.current_active_leads / self.max_active_leads)
        return (daily_remaining + active_remaining) / 2


@dataclass
class AssignmentRule:
    """Rule for automatic lead assignment."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    priority: int = 1  # Higher = evaluated first
    conditions: dict = field(default_factory=dict)
    target_agent_id: Optional[str] = None
    target_role: Optional[str] = None  # e.g., "top_closer", "manager"
    is_active: bool = True


@dataclass
class AssignmentResult:
    """Result of an assignment operation."""

    business_id: str
    assigned_to: str
    agent_name: str
    assignment_score: float
    assignment_reason: str
    assigned_at: datetime = field(default_factory=datetime.utcnow)
    auto_assigned: bool = True


class AssignmentEngine:
    """
    Intelligent lead assignment engine.

    Features:
    - Territory-based assignment
    - Industry specialization matching
    - Capacity-aware distribution
    - Performance-based routing
    - Priority handling
    """

    def __init__(self):
        self.agents: dict[str, AgentProfile] = {}
        self.rules: dict[str, AssignmentRule] = {}
        self.assignment_history: list[AssignmentResult] = []
        self._init_sample_agents()

    def _init_sample_agents(self):
        """Initialize sample agents for demonstration."""

        # Top closer - Construction specialist
        agent1 = AgentProfile(
            name="Mike Johnson",
            email="mike@broker.com",
            phone="555-0101",
            territory_states=["CA", "TX", "FL"],
            specialist_industries=["construction", "trucking"],
            close_rate=0.35,
            avg_deal_size=175000,
            total_deals_closed=250,
            max_daily_assignments=15,
            min_deal_size=50000,
            specialization_multiplier=1.5,
        )
        self.agents[agent1.id] = agent1

        # Senior agent - Restaurant/Retail
        agent2 = AgentProfile(
            name="Sarah Chen",
            email="sarah@broker.com",
            phone="555-0102",
            territory_states=["NY", "NJ", "PA", "MA"],
            specialist_industries=["restaurant", "retail"],
            close_rate=0.28,
            avg_deal_size=85000,
            total_deals_closed=180,
            max_daily_assignments=20,
            specialization_multiplier=1.3,
        )
        self.agents[agent2.id] = agent2

        # General closer
        agent3 = AgentProfile(
            name="David Martinez",
            email="david@broker.com",
            phone="555-0103",
            territory_states=["AZ", "NV", "CO", "UT"],
            specialist_industries=[],  # Generalist
            close_rate=0.22,
            avg_deal_size=100000,
            total_deals_closed=120,
            max_daily_assignments=25,
            specialization_multiplier=1.0,
        )
        self.agents[agent3.id] = agent3

        # New agent - learning
        agent4 = AgentProfile(
            name="Emily Wilson",
            email="emily@broker.com",
            phone="555-0104",
            territory_states=["OH", "MI", "IN", "IL"],
            specialist_industries=[],
            close_rate=0.15,
            avg_deal_size=60000,
            total_deals_closed=25,
            max_daily_assignments=30,
            max_deal_size=150000,  # Smaller deals while learning
            specialization_multiplier=0.8,
        )
        self.agents[agent4.id] = agent4

    def calculate_assignment_score(
        self,
        agent: AgentProfile,
        state: str,
        city: Optional[str],
        industry: Optional[str],
        priority: SignalPriority,
        deal_size_estimate: float,
    ) -> tuple[float, str]:
        """
        Calculate assignment score for an agent.

        Returns (score, reason).
        """
        if not agent.has_capacity:
            return 0.0, "No capacity"

        # Check deal size fit
        if deal_size_estimate < agent.min_deal_size:
            return 0.0, f"Deal ${deal_size_estimate:,.0f} below min ${agent.min_deal_size:,.0f}"
        if deal_size_estimate > agent.max_deal_size:
            return 0.0, f"Deal ${deal_size_estimate:,.0f} above max ${agent.max_deal_size:,.0f}"

        score = 50.0  # Base score
        reasons = []

        # Territory match (30 points max)
        if state in agent.territory_states:
            score += 25
            reasons.append(f"Territory match ({state})")
            if city and city.lower() in [c.lower() for c in agent.territory_cities]:
                score += 5
                reasons.append(f"City match ({city})")

        # Industry specialization (25 points max)
        if industry:
            industry_lower = industry.lower()
            for spec_industry in agent.specialist_industries:
                if spec_industry in industry_lower:
                    score += 25
                    reasons.append(f"Industry specialist ({spec_industry})")
                    break

        # Capacity factor (10 points max)
        capacity_points = agent.capacity_score * 10
        score += capacity_points
        if capacity_points > 5:
            reasons.append("Good capacity")

        # Performance factor (10 points max)
        performance_points = agent.close_rate * 30  # 30% close rate = 10 points
        score += min(performance_points, 10)
        if agent.close_rate > 0.25:
            reasons.append(f"Strong closer ({agent.close_rate:.0%})")

        # Deal size alignment (5 points max)
        if agent.avg_deal_size > 0:
            size_ratio = deal_size_estimate / agent.avg_deal_size
            if 0.5 <= size_ratio <= 2.0:  # Within 50-200% of their average
                score += 5
                reasons.append("Deal size in sweet spot")

        # Apply specialization multiplier
        score *= agent.specialization_multiplier

        # Priority boost for CRITICAL leads to top performers
        if priority == SignalPriority.CRITICAL and agent.close_rate > 0.30:
            score *= 1.2
            reasons.append("CRITICAL priority boost")

        reason_str = "; ".join(reasons) if reasons else "Default assignment"

        return round(score, 1), reason_str

    def assign_lead(
        self,
        business_id: str,
        state: str,
        city: Optional[str] = None,
        industry: Optional[str] = None,
        priority: SignalPriority = SignalPriority.MEDIUM,
        deal_size_estimate: float = 100000,
        exclude_agents: Optional[list[str]] = None,
    ) -> Optional[AssignmentResult]:
        """
        Assign a lead to the best available agent.

        Returns assignment result or None if no suitable agent.
        """
        exclude_agents = exclude_agents or []

        best_agent = None
        best_score = 0.0
        best_reason = ""

        for agent in self.agents.values():
            if agent.id in exclude_agents:
                continue

            score, reason = self.calculate_assignment_score(
                agent=agent,
                state=state,
                city=city,
                industry=industry,
                priority=priority,
                deal_size_estimate=deal_size_estimate,
            )

            if score > best_score:
                best_score = score
                best_agent = agent
                best_reason = reason

        if not best_agent or best_score == 0:
            logger.warning(
                "No suitable agent found for assignment",
                business_id=business_id,
                state=state,
                industry=industry,
            )
            return None

        # Update agent capacity
        best_agent.current_daily_assignments += 1
        best_agent.current_active_leads += 1

        result = AssignmentResult(
            business_id=business_id,
            assigned_to=best_agent.id,
            agent_name=best_agent.name,
            assignment_score=best_score,
            assignment_reason=best_reason,
        )

        self.assignment_history.append(result)

        logger.info(
            "Lead assigned",
            business_id=business_id,
            agent=best_agent.name,
            score=best_score,
            reason=best_reason,
        )

        return result

    def reassign_lead(
        self,
        business_id: str,
        current_agent_id: str,
        state: str,
        city: Optional[str] = None,
        industry: Optional[str] = None,
        priority: SignalPriority = SignalPriority.MEDIUM,
        deal_size_estimate: float = 100000,
        reason: str = "",
    ) -> Optional[AssignmentResult]:
        """Reassign a lead to a different agent."""
        # Reduce previous agent's active count
        if current_agent_id in self.agents:
            self.agents[current_agent_id].current_active_leads -= 1

        result = self.assign_lead(
            business_id=business_id,
            state=state,
            city=city,
            industry=industry,
            priority=priority,
            deal_size_estimate=deal_size_estimate,
            exclude_agents=[current_agent_id],
        )

        if result:
            result.assignment_reason = f"Reassigned: {reason}. {result.assignment_reason}"

        return result

    def get_agent_workload(self, agent_id: str) -> dict:
        """Get workload summary for an agent."""
        if agent_id not in self.agents:
            return {}

        agent = self.agents[agent_id]

        return {
            "agent_id": agent_id,
            "agent_name": agent.name,
            "daily_assignments": agent.current_daily_assignments,
            "max_daily": agent.max_daily_assignments,
            "active_leads": agent.current_active_leads,
            "max_active": agent.max_active_leads,
            "capacity_percent": round(agent.capacity_score * 100, 1),
            "is_available": agent.has_capacity,
        }

    def get_all_workloads(self) -> list[dict]:
        """Get workload for all agents."""
        return [
            self.get_agent_workload(agent_id)
            for agent_id in self.agents
        ]

    def update_agent_availability(
        self,
        agent_id: str,
        is_available: bool,
        next_available_at: Optional[datetime] = None,
    ) -> bool:
        """Update agent availability."""
        if agent_id not in self.agents:
            return False

        self.agents[agent_id].is_available = is_available
        self.agents[agent_id].next_available_at = next_available_at

        return True

    def reset_daily_assignments(self):
        """Reset daily assignment counts (call at midnight)."""
        for agent in self.agents.values():
            agent.current_daily_assignments = 0

        logger.info("Daily assignment counts reset")

    def complete_lead(self, agent_id: str, business_id: str) -> bool:
        """Mark a lead as completed (reduce active count)."""
        if agent_id not in self.agents:
            return False

        self.agents[agent_id].current_active_leads = max(
            0, self.agents[agent_id].current_active_leads - 1
        )

        return True

    def add_agent(self, agent: AgentProfile) -> str:
        """Add a new agent."""
        self.agents[agent.id] = agent
        return agent.id

    def update_agent_stats(
        self,
        agent_id: str,
        close_rate: Optional[float] = None,
        avg_deal_size: Optional[float] = None,
        total_deals_closed: Optional[int] = None,
    ) -> bool:
        """Update agent performance stats."""
        if agent_id not in self.agents:
            return False

        agent = self.agents[agent_id]

        if close_rate is not None:
            agent.close_rate = close_rate
        if avg_deal_size is not None:
            agent.avg_deal_size = avg_deal_size
        if total_deals_closed is not None:
            agent.total_deals_closed = total_deals_closed

        return True

    def get_pending_assignments(
        self,
        priority: Optional[SignalPriority] = None,
    ) -> list[str]:
        """
        Get business IDs that need assignment.

        This would integrate with the database in production.
        """
        # In production, this queries unassigned leads from DB
        return []

    def get_assignment_analytics(self) -> dict:
        """Get assignment analytics."""
        if not self.assignment_history:
            return {
                "total_assignments": 0,
                "avg_score": 0,
                "by_agent": {},
            }

        total = len(self.assignment_history)
        avg_score = sum(a.assignment_score for a in self.assignment_history) / total

        by_agent = {}
        for assignment in self.assignment_history:
            if assignment.agent_name not in by_agent:
                by_agent[assignment.agent_name] = 0
            by_agent[assignment.agent_name] += 1

        return {
            "total_assignments": total,
            "avg_score": round(avg_score, 1),
            "by_agent": by_agent,
        }
