"""
Deal Intelligence
=================

Advanced deal sizing, funding timeline prediction, and approval probability.
Helps brokers prioritize leads by deal potential and urgency.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import structlog

from industry_deep_scan.models import (
    Business,
    Signal,
    SignalCategory,
    SignalType,
    SourceType,
)

logger = structlog.get_logger()


class FundingUrgency(str, Enum):
    """Funding urgency levels."""

    CRITICAL = "critical"  # 7-14 days - immediate need
    HIGH = "high"  # 14-30 days - urgent
    MEDIUM = "medium"  # 30-60 days - planning stage
    LOW = "low"  # 60-90 days - exploratory
    UNKNOWN = "unknown"


@dataclass
class DealSizeEstimate:
    """Estimated deal size range."""

    min_amount: float
    likely_amount: float
    max_amount: float
    confidence: float  # 0-1
    reasoning: str


@dataclass
class FundingTimeline:
    """Predicted funding timeline."""

    urgency: FundingUrgency
    estimated_days: int
    confidence: float
    reasoning: str


@dataclass
class ApprovalProbability:
    """MCA approval probability assessment."""

    approval_probability: float  # 0-1
    mca_fit_score: float  # 0-10
    receptiveness_score: float  # 0-10
    risk_factors: list[str]
    positive_factors: list[str]
    reasoning: str


@dataclass
class DealIntelligence:
    """Complete deal intelligence package."""

    deal_size: DealSizeEstimate
    timeline: FundingTimeline
    approval: ApprovalProbability
    recommended_approach: str
    talk_track_hooks: list[str]
    objection_anticipation: list[str]


class DealIntelligenceEngine:
    """
    Predicts deal size, funding timeline, and approval probability.

    Uses signal type, industry data, and business characteristics
    to estimate deal potential and urgency.
    """

    # Deal size estimates by signal type (min, likely, max in thousands)
    SIGNAL_DEAL_SIZES = {
        SignalType.TAX_LIEN: (25, 75, 200),
        SignalType.JUDGMENT: (30, 100, 300),
        SignalType.CASH_SQUEEZE: (50, 150, 400),
        SignalType.PAYMENT_DELAY: (25, 75, 200),
        SignalType.VENDOR_DISPUTE: (20, 60, 150),
        SignalType.RAPID_GROWTH: (100, 250, 750),
        SignalType.NEW_CONTRACT: (75, 200, 500),
        SignalType.EXPANSION: (150, 400, 1000),
        SignalType.HIRING_SURGE: (50, 150, 400),
        SignalType.NEW_LOCATION: (100, 300, 750),
        SignalType.EQUIPMENT_PURCHASE: (50, 150, 500),
        SignalType.SEASONAL_RAMP: (30, 100, 300),
        SignalType.INVENTORY_NEED: (40, 120, 350),
        SignalType.BUSINESS_FOR_SALE: (50, 150, 400),
        SignalType.LAYOFFS: (25, 75, 200),
        SignalType.REVIEW_DECLINE: (20, 50, 150),
        SignalType.BBB_COMPLAINT: (15, 40, 100),
        SignalType.UCC_FILING: (50, 150, 400),
        SignalType.PERMIT_FILED: (75, 200, 500),
    }

    # Industry multipliers for deal size
    INDUSTRY_MULTIPLIERS = {
        "construction": 1.5,
        "trucking": 1.4,
        "manufacturing": 1.6,
        "medical": 1.3,
        "restaurant": 0.8,
        "retail": 0.7,
        "landscaping": 0.6,
        "auto repair": 0.9,
        "hvac": 1.1,
        "plumbing": 1.0,
        "electrical": 1.0,
    }

    # Urgency timelines by signal type (days)
    SIGNAL_URGENCY = {
        SignalType.TAX_LIEN: (7, FundingUrgency.CRITICAL),
        SignalType.JUDGMENT: (14, FundingUrgency.CRITICAL),
        SignalType.CASH_SQUEEZE: (14, FundingUrgency.HIGH),
        SignalType.PAYMENT_DELAY: (21, FundingUrgency.HIGH),
        SignalType.VENDOR_DISPUTE: (30, FundingUrgency.MEDIUM),
        SignalType.RAPID_GROWTH: (45, FundingUrgency.MEDIUM),
        SignalType.NEW_CONTRACT: (30, FundingUrgency.HIGH),
        SignalType.EXPANSION: (60, FundingUrgency.MEDIUM),
        SignalType.HIRING_SURGE: (30, FundingUrgency.HIGH),
        SignalType.NEW_LOCATION: (45, FundingUrgency.MEDIUM),
        SignalType.EQUIPMENT_PURCHASE: (21, FundingUrgency.HIGH),
        SignalType.SEASONAL_RAMP: (14, FundingUrgency.HIGH),
        SignalType.INVENTORY_NEED: (21, FundingUrgency.HIGH),
        SignalType.BUSINESS_FOR_SALE: (60, FundingUrgency.LOW),
        SignalType.LAYOFFS: (30, FundingUrgency.MEDIUM),
    }

    # Industry approval rates (historical)
    INDUSTRY_APPROVAL_RATES = {
        "construction": 0.92,
        "trucking": 0.88,
        "manufacturing": 0.85,
        "medical": 0.90,
        "restaurant": 0.72,
        "retail": 0.68,
        "landscaping": 0.78,
        "auto repair": 0.82,
        "hvac": 0.88,
        "plumbing": 0.85,
        "electrical": 0.86,
    }

    def estimate_deal_size(
        self,
        business: Business,
        signals: list[Signal],
    ) -> DealSizeEstimate:
        """
        Estimate deal size range based on signals and business characteristics.
        """
        if not signals:
            return DealSizeEstimate(
                min_amount=25000,
                likely_amount=75000,
                max_amount=200000,
                confidence=0.3,
                reasoning="No signals - using baseline estimates",
            )

        # Start with signal-based estimate
        signal_estimates = []
        for signal in signals:
            if signal.signal_type in self.SIGNAL_DEAL_SIZES:
                min_k, likely_k, max_k = self.SIGNAL_DEAL_SIZES[signal.signal_type]
                signal_estimates.append((min_k * 1000, likely_k * 1000, max_k * 1000))

        if not signal_estimates:
            signal_estimates = [(25000, 75000, 200000)]

        # Use highest signal estimate
        base_min = max(e[0] for e in signal_estimates)
        base_likely = max(e[1] for e in signal_estimates)
        base_max = max(e[2] for e in signal_estimates)

        # Apply industry multiplier
        industry_lower = (business.industry or "").lower()
        multiplier = 1.0
        for industry, mult in self.INDUSTRY_MULTIPLIERS.items():
            if industry in industry_lower:
                multiplier = mult
                break

        # Apply employee count adjustment
        emp_count = business.employee_count or 10
        if emp_count > 50:
            multiplier *= 1.5
        elif emp_count > 20:
            multiplier *= 1.2
        elif emp_count < 5:
            multiplier *= 0.7

        # Apply revenue adjustment if known
        if business.annual_revenue_estimate:
            revenue = business.annual_revenue_estimate
            if revenue > 5_000_000:
                multiplier *= 1.8
            elif revenue > 2_000_000:
                multiplier *= 1.4
            elif revenue > 1_000_000:
                multiplier *= 1.2
            elif revenue < 250_000:
                multiplier *= 0.5

        # Calculate final estimates
        final_min = int(base_min * multiplier)
        final_likely = int(base_likely * multiplier)
        final_max = int(base_max * multiplier)

        # Cap at reasonable MCA limits
        final_max = min(final_max, 2_000_000)
        final_likely = min(final_likely, final_max * 0.7)
        final_min = min(final_min, final_likely * 0.5)

        # Calculate confidence
        confidence = 0.5
        if business.annual_revenue_estimate:
            confidence += 0.2
        if business.employee_count:
            confidence += 0.1
        if len(signals) > 2:
            confidence += 0.1

        # Build reasoning
        reasons = []
        primary_signal = signals[0].signal_type.value if signals else "unknown"
        reasons.append(f"Primary signal: {primary_signal}")
        if business.industry:
            reasons.append(f"Industry: {business.industry} ({multiplier:.1f}x)")
        if business.employee_count:
            reasons.append(f"Employees: {business.employee_count}")
        if business.annual_revenue_estimate:
            reasons.append(f"Est. revenue: ${business.annual_revenue_estimate:,.0f}")

        return DealSizeEstimate(
            min_amount=final_min,
            likely_amount=final_likely,
            max_amount=final_max,
            confidence=min(confidence, 0.95),
            reasoning="; ".join(reasons),
        )

    def predict_funding_timeline(
        self,
        business: Business,
        signals: list[Signal],
    ) -> FundingTimeline:
        """
        Predict how urgently the business needs funding.
        """
        if not signals:
            return FundingTimeline(
                urgency=FundingUrgency.UNKNOWN,
                estimated_days=60,
                confidence=0.3,
                reasoning="No signals to assess urgency",
            )

        # Find most urgent signal
        most_urgent_days = 90
        most_urgent_level = FundingUrgency.LOW
        urgent_signal = None

        for signal in signals:
            if signal.signal_type in self.SIGNAL_URGENCY:
                days, urgency = self.SIGNAL_URGENCY[signal.signal_type]
                if days < most_urgent_days:
                    most_urgent_days = days
                    most_urgent_level = urgency
                    urgent_signal = signal

        # Adjust based on signal recency
        if urgent_signal and urgent_signal.source_date:
            days_old = (datetime.utcnow() - urgent_signal.source_date).days
            if days_old < 7:
                most_urgent_days = max(7, most_urgent_days - 7)
            elif days_old > 30:
                most_urgent_days = min(90, most_urgent_days + 14)

        # Multiple signals increase urgency
        distress_signals = sum(
            1 for s in signals
            if s.signal_type in [
                SignalType.TAX_LIEN, SignalType.JUDGMENT,
                SignalType.CASH_SQUEEZE, SignalType.PAYMENT_DELAY,
            ]
        )
        if distress_signals >= 2:
            most_urgent_days = max(7, most_urgent_days - 7)
            most_urgent_level = FundingUrgency.CRITICAL

        # Build reasoning
        reasons = []
        if urgent_signal:
            reasons.append(f"Primary urgency driver: {urgent_signal.signal_type.value}")
        if distress_signals >= 2:
            reasons.append(f"Multiple distress signals ({distress_signals})")
        reasons.append(f"Estimated {most_urgent_days} days to decision")

        confidence = 0.6
        if len(signals) > 1:
            confidence += 0.15
        if urgent_signal and urgent_signal.source_date:
            confidence += 0.1

        return FundingTimeline(
            urgency=most_urgent_level,
            estimated_days=most_urgent_days,
            confidence=min(confidence, 0.9),
            reasoning="; ".join(reasons),
        )

    def calculate_approval_probability(
        self,
        business: Business,
        signals: list[Signal],
    ) -> ApprovalProbability:
        """
        Calculate MCA approval probability based on business characteristics.
        """
        base_probability = 0.65  # Baseline
        mca_fit = 5.0
        receptiveness = 5.0
        risk_factors = []
        positive_factors = []

        # Industry factor
        industry_lower = (business.industry or "").lower()
        industry_rate = 0.75
        for ind, rate in self.INDUSTRY_APPROVAL_RATES.items():
            if ind in industry_lower:
                industry_rate = rate
                break

        if industry_rate > 0.85:
            positive_factors.append(f"Strong industry approval rate ({industry_rate:.0%})")
            mca_fit += 1.5
        elif industry_rate < 0.70:
            risk_factors.append(f"Lower industry approval rate ({industry_rate:.0%})")
            mca_fit -= 1.0

        base_probability = (base_probability + industry_rate) / 2

        # Revenue factor
        if business.annual_revenue_estimate:
            revenue = business.annual_revenue_estimate
            if 250_000 <= revenue <= 5_000_000:
                positive_factors.append("Revenue in MCA sweet spot ($250K-$5M)")
                mca_fit += 2.0
                base_probability += 0.1
            elif revenue > 5_000_000:
                positive_factors.append("Strong revenue base (>$5M)")
                mca_fit += 1.0
                base_probability += 0.05
            elif revenue < 150_000:
                risk_factors.append("Revenue below typical MCA threshold")
                mca_fit -= 2.0
                base_probability -= 0.15

        # Time in business
        if business.year_established:
            years = datetime.now().year - business.year_established
            if years >= 3:
                positive_factors.append(f"Established business ({years} years)")
                mca_fit += 1.0
                base_probability += 0.08
            elif years < 1:
                risk_factors.append("Business less than 1 year old")
                mca_fit -= 1.5
                base_probability -= 0.12

        # Signal quality affects receptiveness
        growth_signals = sum(
            1 for s in signals
            if s.signal_type in [
                SignalType.RAPID_GROWTH, SignalType.EXPANSION,
                SignalType.HIRING_SURGE, SignalType.NEW_LOCATION,
            ]
        )
        distress_signals = sum(
            1 for s in signals
            if s.signal_type in [
                SignalType.TAX_LIEN, SignalType.JUDGMENT,
                SignalType.CASH_SQUEEZE, SignalType.LAYOFFS,
            ]
        )

        if growth_signals > 0:
            positive_factors.append(f"Growth signals detected ({growth_signals})")
            receptiveness += 2.0

        if distress_signals > 0:
            positive_factors.append(f"Distress signals indicate need ({distress_signals})")
            receptiveness += 1.5
            # But distress can affect approval
            if distress_signals >= 2:
                risk_factors.append("Multiple distress signals")
                base_probability -= 0.05

        # Multiple signals = higher intent
        if len(signals) >= 3:
            positive_factors.append(f"Multiple signals ({len(signals)}) indicate active need")
            receptiveness += 1.5

        # Review quality
        if business.yelp_rating and business.yelp_rating >= 4.0:
            positive_factors.append("Strong Yelp rating indicates healthy business")
            mca_fit += 0.5
        elif business.yelp_rating and business.yelp_rating < 3.0:
            risk_factors.append("Low review ratings")
            mca_fit -= 0.5

        # BBB issues
        if business.bbb_complaint_count and business.bbb_complaint_count > 5:
            risk_factors.append(f"BBB complaints ({business.bbb_complaint_count})")
            base_probability -= 0.05

        # Cap scores
        mca_fit = max(1, min(10, mca_fit))
        receptiveness = max(1, min(10, receptiveness))
        base_probability = max(0.15, min(0.95, base_probability))

        # Build reasoning
        reasoning_parts = []
        if positive_factors:
            reasoning_parts.append(f"Positives: {', '.join(positive_factors[:3])}")
        if risk_factors:
            reasoning_parts.append(f"Risks: {', '.join(risk_factors[:3])}")
        reasoning_parts.append(f"MCA Fit: {mca_fit:.1f}/10, Receptiveness: {receptiveness:.1f}/10")

        return ApprovalProbability(
            approval_probability=round(base_probability, 2),
            mca_fit_score=round(mca_fit, 1),
            receptiveness_score=round(receptiveness, 1),
            risk_factors=risk_factors,
            positive_factors=positive_factors,
            reasoning="; ".join(reasoning_parts),
        )

    def generate_talk_track_hooks(
        self,
        business: Business,
        signals: list[Signal],
    ) -> list[str]:
        """
        Generate conversation hooks based on signals.
        """
        hooks = []

        for signal in signals[:3]:  # Top 3 signals
            if signal.signal_type == SignalType.TAX_LIEN:
                hooks.append(
                    f"I noticed there's a tax situation with your business. "
                    f"We specialize in helping businesses like yours get back on track "
                    f"with fast funding - often within 48 hours."
                )
            elif signal.signal_type == SignalType.RAPID_GROWTH:
                hooks.append(
                    f"Congratulations on your growth! I work with expanding businesses "
                    f"who need working capital to keep up with demand. "
                    f"How are you currently handling the cash flow challenges of scaling?"
                )
            elif signal.signal_type == SignalType.HIRING_SURGE:
                hooks.append(
                    f"I saw you're expanding your team - that's exciting! "
                    f"Many of our clients use growth capital to cover payroll "
                    f"while waiting for revenue to catch up."
                )
            elif signal.signal_type == SignalType.EQUIPMENT_PURCHASE:
                hooks.append(
                    f"I noticed you may be looking at new equipment. "
                    f"We help businesses finance equipment purchases without "
                    f"tying up all their working capital."
                )
            elif signal.signal_type == SignalType.NEW_LOCATION:
                hooks.append(
                    f"Opening a new location is a big step! "
                    f"Most of our clients use MCA funding to cover the upfront costs "
                    f"of build-out and inventory."
                )
            elif signal.signal_type == SignalType.SEASONAL_RAMP:
                hooks.append(
                    f"With your busy season approaching, are you prepared "
                    f"for the inventory and staffing costs? "
                    f"We help businesses bridge the gap before peak revenue hits."
                )
            elif signal.signal_type == SignalType.CASH_SQUEEZE:
                hooks.append(
                    f"Running a business means juggling cash flow constantly. "
                    f"We provide fast working capital so you can focus on operations "
                    f"instead of worrying about next week's payments."
                )

        if not hooks:
            hooks.append(
                f"Hi, I'm reaching out to business owners in the {business.industry or 'your'} "
                f"industry. We provide fast working capital for growth and operations - "
                f"is that something you'd be interested in discussing?"
            )

        return hooks

    def anticipate_objections(
        self,
        business: Business,
        signals: list[Signal],
    ) -> list[str]:
        """
        Anticipate likely objections based on business profile.
        """
        objections = []

        industry = (business.industry or "").lower()

        # Industry-specific objections
        if "restaurant" in industry:
            objections.append(
                "OBJECTION: 'Your rates are too high'\n"
                "RESPONSE: 'I understand - restaurant margins are tight. "
                "The key is using the capital to generate returns that exceed the cost. "
                "Most of our restaurant clients use funding for equipment upgrades or "
                "seasonal inventory that pays for itself 3-4x over.'"
            )
        elif "construction" in industry:
            objections.append(
                "OBJECTION: 'I have a line of credit'\n"
                "RESPONSE: 'Great! Many of our construction clients keep their credit line "
                "as backup and use MCA for specific projects. That way you're not tying up "
                "your credit limit and you have flexibility for unexpected opportunities.'"
            )

        # Signal-specific objections
        has_distress = any(
            s.signal_type in [SignalType.TAX_LIEN, SignalType.JUDGMENT, SignalType.CASH_SQUEEZE]
            for s in signals
        )

        if has_distress:
            objections.append(
                "OBJECTION: 'I'm not sure I can afford another payment'\n"
                "RESPONSE: 'That's a valid concern. The way MCA works, payments flex "
                "with your revenue - busy days mean slightly higher payments, slow days "
                "mean lower ones. Plus, getting ahead of your situation now prevents "
                "much bigger problems down the road.'"
            )

        # Common objections
        objections.append(
            "OBJECTION: 'I need to think about it'\n"
            "RESPONSE: 'Of course - this is an important decision. What specific "
            "information would help you make that decision? I can send you a detailed "
            "quote with exact payment amounts so you can see the real numbers.'"
        )

        objections.append(
            "OBJECTION: 'Send me information by email'\n"
            "RESPONSE: 'Happy to do that. To send you the most relevant information, "
            "can I ask a few quick questions? What's your approximate monthly revenue, "
            "and what would you use the funding for?'"
        )

        return objections[:5]

    def analyze(
        self,
        business: Business,
        signals: list[Signal],
    ) -> DealIntelligence:
        """
        Generate complete deal intelligence package.
        """
        deal_size = self.estimate_deal_size(business, signals)
        timeline = self.predict_funding_timeline(business, signals)
        approval = self.calculate_approval_probability(business, signals)
        hooks = self.generate_talk_track_hooks(business, signals)
        objections = self.anticipate_objections(business, signals)

        # Generate recommended approach
        if timeline.urgency == FundingUrgency.CRITICAL:
            approach = (
                "URGENT OUTREACH: Call immediately. Lead has critical funding need. "
                "Emphasize speed of funding (48-72 hours). Be direct about solution."
            )
        elif approval.approval_probability > 0.8:
            approach = (
                "HIGH-VALUE LEAD: Strong approval likelihood. Focus on building "
                "relationship and understanding specific needs. Can take consultative approach."
            )
        elif approval.receptiveness_score > 7:
            approach = (
                "RECEPTIVE LEAD: Business actively showing funding signals. "
                "Lead with value proposition. Move quickly to qualification."
            )
        else:
            approach = (
                "STANDARD OUTREACH: Qualify interest first. Ask discovery questions "
                "about current funding situation and upcoming needs."
            )

        return DealIntelligence(
            deal_size=deal_size,
            timeline=timeline,
            approval=approval,
            recommended_approach=approach,
            talk_track_hooks=hooks,
            objection_anticipation=objections,
        )
