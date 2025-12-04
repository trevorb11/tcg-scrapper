"""
LLM Signal Classifier
=====================

Uses OpenAI or Anthropic to:
1. Validate signal relevance
2. Extract funding indicators
3. Classify signal type and priority
4. Generate recommended approach/pitch
5. Estimate urgency and deal potential

This is the intelligence layer that turns raw data into actionable leads.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from industry_deep_scan.config import get_settings
from industry_deep_scan.models import SignalCategory, SignalPriority, SignalType
from industry_deep_scan.sources.base import RawSignal

logger = structlog.get_logger()
settings = get_settings()


@dataclass
class FundingIndicator:
    """Individual funding indicator extracted by LLM."""

    indicator: str  # Description of the indicator
    strength: float  # 0-1 confidence
    category: str  # cash_flow, growth, distress, opportunity
    evidence: str  # Quote from source


@dataclass
class ClassificationResult:
    """Complete classification result from LLM analysis."""

    # Validation
    is_valid_signal: bool = True
    confidence: float = 0.0  # 0-1

    # Classification
    signal_type: Optional[SignalType] = None
    category: Optional[SignalCategory] = None
    priority: SignalPriority = SignalPriority.LOW

    # Scoring
    urgency_score: float = 0.0  # 1-10
    deal_potential_score: float = 0.0  # 1-10
    estimated_funding_need: Optional[str] = None  # e.g., "$50K-$100K"

    # Analysis
    funding_indicators: list[FundingIndicator] = field(default_factory=list)
    llm_analysis: str = ""  # Full analysis text
    recommended_approach: str = ""  # Suggested pitch/approach
    key_talking_points: list[str] = field(default_factory=list)

    # Business intelligence
    industry_classification: Optional[str] = None
    estimated_revenue_range: Optional[str] = None
    employee_estimate: Optional[str] = None
    business_health: Optional[str] = None  # healthy, stressed, distressed, growing

    # Metadata
    processing_time_ms: float = 0.0
    model_used: str = ""
    tokens_used: int = 0


class LLMClassifier:
    """
    LLM-powered signal classification engine.

    Supports both OpenAI and Anthropic models.
    Includes caching, rate limiting, and cost tracking.
    """

    # System prompt for signal classification
    SYSTEM_PROMPT = """You are an expert MCA (Merchant Cash Advance) underwriter and business analyst. Your job is to analyze business signals and identify funding opportunities.

MCA businesses provide short-term working capital to small businesses. Key indicators of funding need include:

CASH FLOW STRESS SIGNALS (High Priority):
- Payment delays to vendors
- Tax liens or judgments
- BBB complaints about service quality
- Review declines (indicating understaffing/cost cutting)
- Hiring freezes or layoffs
- "Must sell" or distressed business listings

RAPID GROWTH SIGNALS (High Priority):
- New contracts or partnerships
- Expansion announcements
- Hiring surges
- New location openings
- Equipment purchases
- Fleet expansions

DISTRESS + HIGH REVENUE (Highest Priority):
- Established business showing stress signals
- High review volume but declining ratings
- Multiple complaints but continued operation
- Layoffs at growing company (cash crunch)

OPPORTUNITY SIGNALS (Medium Priority):
- Business for sale listings
- Permit filings for expansion
- New business registrations
- Equipment upgrade needs
- Seasonal ramp-up needs

When analyzing a signal, consider:
1. Is this a real funding opportunity or noise?
2. What specific indicators suggest they need capital?
3. How urgent is their need (timing)?
4. What's the likely deal size potential?
5. What's the best approach to reach them?

Provide actionable intelligence for sales teams."""

    CLASSIFICATION_PROMPT_TEMPLATE = """Analyze this business signal and classify it for MCA lead generation.

SIGNAL INFORMATION:
Business Name: {business_name}
Location: {location}
Industry: {industry}
Source: {source_type}
Date: {source_date}

SIGNAL CONTENT:
Title: {title}
{description}

RAW DATA:
{raw_content}

ADDITIONAL CONTEXT:
{metadata}

Analyze this signal and respond with a JSON object containing:

{{
    "is_valid_signal": true/false,  // Is this a real funding opportunity?
    "confidence": 0.0-1.0,  // How confident are you in this classification?

    "signal_type": "one of: cash_squeeze, payment_delay, vendor_dispute, tax_lien, judgment, rapid_growth, new_contract, expansion, hiring_surge, new_location, layoffs, review_decline, bbb_complaint, owner_change, equipment_purchase, seasonal_ramp, inventory_need, business_for_sale, news_mention, permit_filed, ucc_filing",

    "category": "one of: cash_flow_stress, rapid_growth, distress_high_revenue, expansion_opportunity, acquisition_target",

    "priority": "one of: critical, high, medium, low, informational",

    "urgency_score": 1-10,  // How time-sensitive is this opportunity?
    "deal_potential_score": 1-10,  // How likely to close and what size?

    "estimated_funding_need": "$XX,XXX - $XXX,XXX",  // Your estimate

    "funding_indicators": [
        {{
            "indicator": "Description of what indicates funding need",
            "strength": 0.0-1.0,
            "category": "cash_flow/growth/distress/opportunity",
            "evidence": "Quote or specific fact from the signal"
        }}
    ],

    "analysis": "2-3 sentence analysis of why this is or isn't a good lead",

    "recommended_approach": "Suggested pitch angle and key points to mention when contacting",

    "key_talking_points": ["Point 1", "Point 2", "Point 3"],

    "industry_classification": "Specific industry category",
    "estimated_revenue_range": "$XXX,XXX - $X,XXX,XXX",
    "employee_estimate": "XX-XX employees",
    "business_health": "one of: healthy, stressed, distressed, growing"
}}

Respond ONLY with the JSON object, no other text."""

    def __init__(self):
        self.settings = settings
        self._client = None
        self._cache: dict[str, ClassificationResult] = {}
        self._daily_cost = 0.0
        self._request_count = 0
        self._last_request_time = 0.0

    async def setup(self) -> None:
        """Initialize LLM client."""
        if self.settings.llm.provider == "openai":
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self.settings.llm.openai_api_key.get_secret_value()
            )
        else:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(
                api_key=self.settings.llm.anthropic_api_key.get_secret_value()
            )

    def _get_cache_key(self, signal: RawSignal) -> str:
        """Generate cache key for signal."""
        content = f"{signal.business_name}:{signal.raw_content[:500]}"
        return hashlib.md5(content.encode()).hexdigest()

    async def _rate_limit(self) -> None:
        """Apply rate limiting."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time

        # Requests per minute limit
        min_interval = 60.0 / self.settings.llm.requests_per_minute

        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)

        self._last_request_time = asyncio.get_event_loop().time()

    def _check_cost_limit(self) -> bool:
        """Check if daily cost limit exceeded."""
        return self._daily_cost < self.settings.llm.max_cost_per_day

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
    )
    async def _call_openai(self, prompt: str) -> tuple[str, int]:
        """Call OpenAI API."""
        response = await self._client.chat.completions.create(
            model=self.settings.llm.openai_model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=self.settings.llm.max_tokens,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        tokens = response.usage.total_tokens if response.usage else 0

        # Estimate cost (GPT-4 Turbo pricing)
        cost = (tokens / 1000) * 0.01
        self._daily_cost += cost

        return content, tokens

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
    )
    async def _call_anthropic(self, prompt: str) -> tuple[str, int]:
        """Call Anthropic API."""
        response = await self._client.messages.create(
            model=self.settings.llm.anthropic_model,
            max_tokens=self.settings.llm.max_tokens,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text
        tokens = response.usage.input_tokens + response.usage.output_tokens

        # Estimate cost (Claude 3 Opus pricing)
        cost = (tokens / 1000) * 0.015
        self._daily_cost += cost

        return content, tokens

    def _parse_response(self, response_text: str) -> ClassificationResult:
        """Parse LLM JSON response into ClassificationResult."""
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re

            json_match = re.search(r"\{[\s\S]*\}", response_text)
            if json_match:
                data = json.loads(json_match.group())
            else:
                logger.warning("Failed to parse LLM response as JSON")
                return ClassificationResult(is_valid_signal=False, confidence=0.0)

        # Map string values to enums
        signal_type_map = {st.value: st for st in SignalType}
        category_map = {sc.value: sc for sc in SignalCategory}
        priority_map = {sp.value: sp for sp in SignalPriority}

        # Parse funding indicators
        indicators = []
        for ind in data.get("funding_indicators", []):
            indicators.append(
                FundingIndicator(
                    indicator=ind.get("indicator", ""),
                    strength=float(ind.get("strength", 0.5)),
                    category=ind.get("category", "opportunity"),
                    evidence=ind.get("evidence", ""),
                )
            )

        return ClassificationResult(
            is_valid_signal=data.get("is_valid_signal", True),
            confidence=float(data.get("confidence", 0.5)),
            signal_type=signal_type_map.get(data.get("signal_type")),
            category=category_map.get(data.get("category")),
            priority=priority_map.get(data.get("priority"), SignalPriority.LOW),
            urgency_score=float(data.get("urgency_score", 5)),
            deal_potential_score=float(data.get("deal_potential_score", 5)),
            estimated_funding_need=data.get("estimated_funding_need"),
            funding_indicators=indicators,
            llm_analysis=data.get("analysis", ""),
            recommended_approach=data.get("recommended_approach", ""),
            key_talking_points=data.get("key_talking_points", []),
            industry_classification=data.get("industry_classification"),
            estimated_revenue_range=data.get("estimated_revenue_range"),
            employee_estimate=data.get("employee_estimate"),
            business_health=data.get("business_health"),
        )

    async def classify(self, signal: RawSignal) -> ClassificationResult:
        """
        Classify a raw signal using LLM.

        Args:
            signal: Raw signal from a source connector

        Returns:
            ClassificationResult with full analysis
        """
        start_time = asyncio.get_event_loop().time()

        # Check cache
        cache_key = self._get_cache_key(signal)
        if self.settings.llm.cache_responses and cache_key in self._cache:
            logger.debug("Returning cached classification", business=signal.business_name)
            return self._cache[cache_key]

        # Check cost limit
        if not self._check_cost_limit():
            logger.warning("Daily LLM cost limit exceeded")
            return ClassificationResult(
                is_valid_signal=True,
                confidence=0.3,
                signal_type=signal.suggested_signal_type,
                category=signal.suggested_category,
                priority=signal.suggested_priority or SignalPriority.LOW,
                llm_analysis="Cost limit exceeded - using rule-based classification",
            )

        # Apply rate limiting
        await self._rate_limit()

        # Initialize client if needed
        if self._client is None:
            await self.setup()

        # Build prompt
        location = f"{signal.business_city}, {signal.business_state}" if signal.business_city else signal.business_state or "Unknown"

        prompt = self.CLASSIFICATION_PROMPT_TEMPLATE.format(
            business_name=signal.business_name,
            location=location,
            industry=signal.industry or "Unknown",
            source_type=signal.source_type.value,
            source_date=signal.source_date.strftime("%Y-%m-%d") if signal.source_date else "Recent",
            title=signal.title,
            description=signal.description or "",
            raw_content=signal.raw_content[:2000] if signal.raw_content else "",
            metadata=json.dumps(signal.metadata, indent=2) if signal.metadata else "{}",
        )

        try:
            # Call LLM
            if self.settings.llm.provider == "openai":
                response_text, tokens = await self._call_openai(prompt)
            else:
                response_text, tokens = await self._call_anthropic(prompt)

            # Parse response
            result = self._parse_response(response_text)

            # Add metadata
            elapsed = (asyncio.get_event_loop().time() - start_time) * 1000
            result.processing_time_ms = elapsed
            result.model_used = (
                self.settings.llm.openai_model
                if self.settings.llm.provider == "openai"
                else self.settings.llm.anthropic_model
            )
            result.tokens_used = tokens

            # Cache result
            if self.settings.llm.cache_responses:
                self._cache[cache_key] = result

            logger.info(
                "Signal classified",
                business=signal.business_name,
                priority=result.priority.value,
                confidence=result.confidence,
                tokens=tokens,
            )

            return result

        except Exception as e:
            logger.error("Error classifying signal", error=str(e))

            # Return rule-based fallback
            return ClassificationResult(
                is_valid_signal=True,
                confidence=0.3,
                signal_type=signal.suggested_signal_type,
                category=signal.suggested_category,
                priority=signal.suggested_priority or SignalPriority.LOW,
                llm_analysis=f"Classification error: {str(e)}",
            )

    async def classify_batch(
        self,
        signals: list[RawSignal],
        max_concurrent: int = 5,
    ) -> list[tuple[RawSignal, ClassificationResult]]:
        """
        Classify multiple signals concurrently.

        Args:
            signals: List of raw signals
            max_concurrent: Maximum concurrent LLM calls

        Returns:
            List of (signal, classification) tuples
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def classify_with_semaphore(signal: RawSignal) -> tuple[RawSignal, ClassificationResult]:
            async with semaphore:
                result = await self.classify(signal)
                return signal, result

        tasks = [classify_with_semaphore(s) for s in signals]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions
        valid_results = []
        for r in results:
            if isinstance(r, Exception):
                logger.error("Batch classification error", error=str(r))
            else:
                valid_results.append(r)

        return valid_results

    def get_stats(self) -> dict:
        """Get classifier statistics."""
        return {
            "request_count": self._request_count,
            "daily_cost": round(self._daily_cost, 4),
            "cache_size": len(self._cache),
            "cost_limit": self.settings.llm.max_cost_per_day,
            "cost_remaining": round(self.settings.llm.max_cost_per_day - self._daily_cost, 4),
        }

    def reset_daily_stats(self) -> None:
        """Reset daily counters (call at midnight)."""
        self._daily_cost = 0.0
        self._request_count = 0


class RuleBasedClassifier:
    """
    Fallback rule-based classifier when LLM is unavailable or for low-priority signals.

    Uses keyword matching and heuristics for quick classification.
    """

    # Keyword to signal type mappings
    KEYWORD_MAPPINGS = {
        SignalType.CASH_SQUEEZE: [
            "cash flow", "cash crunch", "struggling", "financial trouble",
            "cannot pay", "late payment", "payment issues",
        ],
        SignalType.LAYOFFS: [
            "layoff", "laid off", "downsizing", "workforce reduction",
            "cutting jobs", "job cuts", "letting go",
        ],
        SignalType.EXPANSION: [
            "expansion", "expanding", "growth", "growing", "new location",
            "opening", "grand opening",
        ],
        SignalType.NEW_CONTRACT: [
            "contract", "awarded", "deal", "partnership", "agreement",
        ],
        SignalType.HIRING_SURGE: [
            "hiring", "recruiting", "new positions", "job openings",
            "adding staff", "growing team",
        ],
        SignalType.EQUIPMENT_PURCHASE: [
            "equipment", "machinery", "fleet", "vehicles", "tools",
            "upgrade", "purchase",
        ],
        SignalType.REVIEW_DECLINE: [
            "bad review", "negative review", "complaint", "unsatisfied",
            "poor service", "declined", "worse",
        ],
        SignalType.TAX_LIEN: [
            "tax lien", "irs lien", "federal tax", "state tax",
        ],
        SignalType.BUSINESS_FOR_SALE: [
            "for sale", "selling business", "exit", "retire",
            "must sell", "motivated seller",
        ],
    }

    # Priority scoring rules
    PRIORITY_RULES = {
        SignalType.CASH_SQUEEZE: SignalPriority.HIGH,
        SignalType.LAYOFFS: SignalPriority.HIGH,
        SignalType.TAX_LIEN: SignalPriority.CRITICAL,
        SignalType.JUDGMENT: SignalPriority.HIGH,
        SignalType.EXPANSION: SignalPriority.MEDIUM,
        SignalType.NEW_CONTRACT: SignalPriority.HIGH,
        SignalType.HIRING_SURGE: SignalPriority.MEDIUM,
        SignalType.EQUIPMENT_PURCHASE: SignalPriority.MEDIUM,
        SignalType.BUSINESS_FOR_SALE: SignalPriority.MEDIUM,
        SignalType.REVIEW_DECLINE: SignalPriority.MEDIUM,
    }

    def classify(self, signal: RawSignal) -> ClassificationResult:
        """
        Classify signal using keyword rules.

        Args:
            signal: Raw signal to classify

        Returns:
            ClassificationResult (lower confidence than LLM)
        """
        content = f"{signal.title} {signal.description} {signal.raw_content}".lower()

        # Find matching signal type
        signal_type = signal.suggested_signal_type
        max_matches = 0

        for st, keywords in self.KEYWORD_MAPPINGS.items():
            matches = sum(1 for kw in keywords if kw in content)
            if matches > max_matches:
                max_matches = matches
                signal_type = st

        # Determine priority
        priority = self.PRIORITY_RULES.get(signal_type, SignalPriority.LOW)

        # Map signal type to category
        category_map = {
            SignalType.CASH_SQUEEZE: SignalCategory.CASH_FLOW_STRESS,
            SignalType.LAYOFFS: SignalCategory.DISTRESS_HIGH_REVENUE,
            SignalType.TAX_LIEN: SignalCategory.CASH_FLOW_STRESS,
            SignalType.EXPANSION: SignalCategory.RAPID_GROWTH,
            SignalType.NEW_CONTRACT: SignalCategory.RAPID_GROWTH,
            SignalType.HIRING_SURGE: SignalCategory.RAPID_GROWTH,
            SignalType.BUSINESS_FOR_SALE: SignalCategory.ACQUISITION_TARGET,
        }

        category = category_map.get(signal_type, SignalCategory.EXPANSION_OPPORTUNITY)

        return ClassificationResult(
            is_valid_signal=True,
            confidence=0.5,  # Lower confidence for rule-based
            signal_type=signal_type,
            category=category,
            priority=priority,
            urgency_score=7.0 if priority == SignalPriority.CRITICAL else 5.0,
            deal_potential_score=5.0,
            llm_analysis="Classified using rule-based system",
        )
