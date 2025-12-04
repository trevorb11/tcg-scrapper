"""
Lead Scoring Engine
===================

Calculates overall lead scores based on:
- Signal strength and type
- Industry multipliers
- Revenue estimates
- Geographic factors
- Multiple signal stacking
"""

from datetime import datetime, timedelta
from typing import Optional

import structlog

from industry_deep_scan.config import get_settings
from industry_deep_scan.models import (
    Business,
    Signal,
    SignalCategory,
    SignalPriority,
    SignalType,
)
from industry_deep_scan.classifiers.llm_classifier import ClassificationResult

logger = structlog.get_logger()
settings = get_settings()


class LeadScorer:
    """
    Multi-factor lead scoring engine.

    Combines signal data, business attributes, and classification
    results into a single actionable score.
    """

    def __init__(self):
        self.settings = settings.scoring

        # Base scores by signal category
        self.category_scores = {
            SignalCategory.CASH_FLOW_STRESS: 9.0,
            SignalCategory.DISTRESS_HIGH_REVENUE: 9.5,
            SignalCategory.RAPID_GROWTH: 8.0,
            SignalCategory.EXPANSION_OPPORTUNITY: 7.0,
            SignalCategory.ACQUISITION_TARGET: 6.5,
        }

        # Signal type multipliers
        self.signal_multipliers = {
            SignalType.TAX_LIEN: 1.3,
            SignalType.JUDGMENT: 1.2,
            SignalType.CASH_SQUEEZE: 1.2,
            SignalType.LAYOFFS: 1.1,
            SignalType.NEW_CONTRACT: 1.15,
            SignalType.EXPANSION: 1.1,
            SignalType.HIRING_SURGE: 1.05,
            SignalType.EQUIPMENT_PURCHASE: 1.1,
            SignalType.BUSINESS_FOR_SALE: 0.9,  # Lower - may be exiting
            SignalType.REVIEW_DECLINE: 1.0,
            SignalType.BBB_COMPLAINT: 1.05,
        }

        # Industry multipliers for high-value sectors
        self.industry_multipliers = {
            "construction": 1.3,
            "trucking": 1.25,
            "restaurant": 1.2,
            "medical": 1.15,
            "manufacturing": 1.2,
            "auto repair": 1.15,
            "retail": 1.0,
            "landscaping": 1.1,
            "hvac": 1.2,
            "plumbing": 1.15,
            "electrical": 1.15,
            "transportation": 1.2,
            "logistics": 1.2,
        }

    def _get_industry_multiplier(self, industry: Optional[str]) -> float:
        """Get multiplier for industry."""
        if not industry:
            return 1.0

        industry_lower = industry.lower()

        for ind, mult in self.industry_multipliers.items():
            if ind in industry_lower:
                return mult

        return 1.0

    def _get_revenue_multiplier(self, revenue: Optional[float]) -> float:
        """Get multiplier based on revenue range."""
        if not revenue:
            return 1.0

        ideal_min, ideal_max = self.settings.ideal_revenue_range

        if ideal_min <= revenue <= ideal_max:
            return 1.2  # Sweet spot
        elif revenue < self.settings.min_estimated_revenue:
            return 0.7  # Too small
        elif revenue > ideal_max:
            # Large businesses - good but may not need MCA
            return 0.9 + min(0.2, revenue / 10000000 * 0.1)

        return 1.0

    def _get_recency_multiplier(self, signal_date: Optional[datetime]) -> float:
        """Get multiplier based on signal recency."""
        if not signal_date:
            return 0.8

        days_old = (datetime.utcnow() - signal_date).days

        if days_old <= 1:
            return 1.3  # Very fresh - act now
        elif days_old <= 3:
            return 1.2
        elif days_old <= 7:
            return 1.1
        elif days_old <= 14:
            return 1.0
        elif days_old <= 30:
            return 0.9
        else:
            return 0.7  # Old signal

    def _get_stacking_bonus(self, signal_count: int) -> float:
        """Get bonus for multiple signals on same business."""
        if signal_count <= 1:
            return 0
        elif signal_count == 2:
            return 0.5
        elif signal_count == 3:
            return 1.0
        else:
            return 1.5  # Lots of signals = hot lead

    def score_signal(
        self,
        classification: ClassificationResult,
        industry: Optional[str] = None,
        revenue: Optional[float] = None,
        signal_date: Optional[datetime] = None,
    ) -> tuple[float, SignalPriority]:
        """
        Calculate score for a single classified signal.

        Args:
            classification: LLM classification result
            industry: Business industry
            revenue: Estimated revenue
            signal_date: Date of the signal

        Returns:
            Tuple of (score, priority)
        """
        # Start with base category score
        base_score = self.category_scores.get(classification.category, 5.0)

        # Apply signal type multiplier
        signal_mult = self.signal_multipliers.get(classification.signal_type, 1.0)

        # Apply other multipliers
        industry_mult = self._get_industry_multiplier(industry)
        revenue_mult = self._get_revenue_multiplier(revenue)
        recency_mult = self._get_recency_multiplier(signal_date)

        # Apply LLM confidence
        confidence_factor = 0.5 + (classification.confidence * 0.5)

        # Include LLM scores if available
        urgency_factor = 1.0 + (classification.urgency_score - 5) * 0.05
        potential_factor = 1.0 + (classification.deal_potential_score - 5) * 0.05

        # Calculate final score
        score = (
            base_score
            * signal_mult
            * industry_mult
            * revenue_mult
            * recency_mult
            * confidence_factor
            * urgency_factor
            * potential_factor
        )

        # Normalize to 0-10 scale
        score = min(10.0, max(0.0, score))

        # Determine priority from score
        if score >= 9.0:
            priority = SignalPriority.CRITICAL
        elif score >= 7.5:
            priority = SignalPriority.HIGH
        elif score >= 5.5:
            priority = SignalPriority.MEDIUM
        elif score >= 3.0:
            priority = SignalPriority.LOW
        else:
            priority = SignalPriority.INFORMATIONAL

        return round(score, 2), priority

    def score_business(
        self,
        business: Business,
        signals: list[Signal],
    ) -> tuple[float, SignalPriority, dict]:
        """
        Calculate aggregate score for a business based on all signals.

        Args:
            business: Business entity
            signals: List of signals for this business

        Returns:
            Tuple of (score, priority, breakdown dict)
        """
        if not signals:
            return 0.0, SignalPriority.INFORMATIONAL, {}

        # Score each signal
        signal_scores = []
        for signal in signals:
            # Reconstruct classification from signal data
            score = signal.signal_strength or 5.0

            # Apply recency
            recency_mult = self._get_recency_multiplier(signal.source_date)
            score *= recency_mult

            signal_scores.append((signal, score))

        # Sort by score
        signal_scores.sort(key=lambda x: x[1], reverse=True)

        # Primary score is the highest signal
        primary_score = signal_scores[0][1]

        # Add stacking bonus
        stacking_bonus = self._get_stacking_bonus(len(signals))

        # Apply business-level multipliers
        industry_mult = self._get_industry_multiplier(business.industry)
        revenue_mult = self._get_revenue_multiplier(business.annual_revenue_estimate)

        # Calculate final score
        final_score = (primary_score + stacking_bonus) * industry_mult * revenue_mult

        # Normalize
        final_score = min(10.0, max(0.0, final_score))

        # Determine priority
        if final_score >= 9.0:
            priority = SignalPriority.CRITICAL
        elif final_score >= 7.5:
            priority = SignalPriority.HIGH
        elif final_score >= 5.5:
            priority = SignalPriority.MEDIUM
        elif final_score >= 3.0:
            priority = SignalPriority.LOW
        else:
            priority = SignalPriority.INFORMATIONAL

        # Build breakdown
        breakdown = {
            "primary_signal_score": round(signal_scores[0][1], 2),
            "stacking_bonus": stacking_bonus,
            "industry_multiplier": industry_mult,
            "revenue_multiplier": revenue_mult,
            "signal_count": len(signals),
            "signal_types": [s.signal_type.value for s, _ in signal_scores],
            "final_score": round(final_score, 2),
        }

        return round(final_score, 2), priority, breakdown

    def prioritize_leads(
        self,
        businesses: list[tuple[Business, list[Signal]]],
    ) -> list[tuple[Business, float, SignalPriority, dict]]:
        """
        Score and rank a list of businesses.

        Args:
            businesses: List of (business, signals) tuples

        Returns:
            Sorted list of (business, score, priority, breakdown) tuples
        """
        scored = []

        for business, signals in businesses:
            score, priority, breakdown = self.score_business(business, signals)
            scored.append((business, score, priority, breakdown))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored


class DailyDigestScorer:
    """
    Scores for daily digest / summary reports.

    Focuses on:
    - New high-priority signals
    - Trending businesses (multiple recent signals)
    - Follow-up reminders
    """

    def __init__(self, base_scorer: Optional[LeadScorer] = None):
        self.scorer = base_scorer or LeadScorer()

    def get_digest_leads(
        self,
        businesses: list[tuple[Business, list[Signal]]],
        limit: int = 20,
    ) -> dict:
        """
        Get leads for daily digest.

        Returns dict with categorized leads.
        """
        scored = self.scorer.prioritize_leads(businesses)

        # Categorize
        critical = [x for x in scored if x[2] == SignalPriority.CRITICAL][:5]
        high = [x for x in scored if x[2] == SignalPriority.HIGH][:10]
        trending = self._get_trending(businesses)[:5]

        return {
            "critical_leads": [
                {
                    "business": b.name,
                    "score": s,
                    "signals": len(sigs),
                    "industry": b.industry,
                    "location": f"{b.city}, {b.state}",
                }
                for b, sigs in businesses
                for b2, s, p, _ in critical
                if b.id == b2.id
            ],
            "high_priority_leads": [
                {
                    "business": b.name,
                    "score": s,
                    "priority": p.value,
                }
                for b, s, p, _ in high
            ],
            "trending_businesses": trending,
            "total_new_signals": sum(len(sigs) for _, sigs in businesses),
            "total_businesses": len(businesses),
        }

    def _get_trending(
        self,
        businesses: list[tuple[Business, list[Signal]]],
    ) -> list[dict]:
        """Get businesses with multiple recent signals (trending)."""
        recent_cutoff = datetime.utcnow() - timedelta(days=7)

        trending = []
        for business, signals in businesses:
            recent_signals = [s for s in signals if s.created_at >= recent_cutoff]

            if len(recent_signals) >= 2:
                trending.append({
                    "business": business.name,
                    "recent_signal_count": len(recent_signals),
                    "signal_types": list(set(s.signal_type.value for s in recent_signals)),
                    "latest_signal": max(s.created_at for s in recent_signals).isoformat(),
                })

        # Sort by signal count
        trending.sort(key=lambda x: x["recent_signal_count"], reverse=True)

        return trending
