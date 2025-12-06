"""
Deep Scan Engine
================

Main orchestration engine that coordinates:
- Source scanning
- Signal classification
- Lead scoring
- Database persistence
- Notification dispatch

This is the core component that ties everything together.
"""

import asyncio
from datetime import datetime
from typing import AsyncIterator, Optional

import structlog

from industry_deep_scan.config import get_settings
from industry_deep_scan.database import (
    BusinessRepository,
    ScanJobRepository,
    SignalRepository,
    get_session,
    init_db,
)
from industry_deep_scan.models import (
    Business,
    ScanJob,
    Signal,
    SignalCategory,
    SignalPriority,
    SignalType,
    SourceType,
)
from industry_deep_scan.sources import (
    BaseSource,
    BBBSource,
    BizBuySellSource,
    BusinessBrokerSource,
    CourtRecordsSource,
    EquipmentPermitSource,
    GoogleNewsSource,
    GoogleReviewsSource,
    LinkedInSource,
    LocalNewsSource,
    RawSignal,
    SOSFilingsSource,
    UCCFilingsSource,
    YelpSource,
)
from industry_deep_scan.classifiers import (
    ClassificationResult,
    LeadScorer,
    LLMClassifier,
)

logger = structlog.get_logger()
settings = get_settings()


class DeepScanEngine:
    """
    Main Industry Deep Scan orchestration engine.

    Coordinates all scanning, classification, and persistence operations.

    Usage:
        async with DeepScanEngine() as engine:
            await engine.run_full_scan()
    """

    def __init__(self):
        self.settings = settings
        self.classifier = LLMClassifier()
        self.scorer = LeadScorer()

        # Initialize sources
        self.sources: dict[SourceType, BaseSource] = {}
        self._init_sources()

    def _init_sources(self) -> None:
        """Initialize enabled source connectors."""
        if self.settings.sources.google_news_enabled:
            self.sources[SourceType.NEWS] = GoogleNewsSource()

        if self.settings.sources.yelp_enabled:
            self.sources[SourceType.YELP] = YelpSource()

        if self.settings.sources.bbb_enabled:
            self.sources[SourceType.BBB] = BBBSource()

        if self.settings.sources.bizbuysell_enabled:
            self.sources[SourceType.BUSINESS_LISTINGS] = BizBuySellSource()

        if self.settings.sources.court_records_enabled:
            self.sources[SourceType.COURT_RECORDS] = CourtRecordsSource()

        if self.settings.sources.equipment_permits_enabled:
            self.sources[SourceType.EQUIPMENT_PERMITS] = EquipmentPermitSource()

        if self.settings.sources.sos_filings_enabled:
            self.sources[SourceType.SOS_FILINGS] = SOSFilingsSource()

        if self.settings.sources.linkedin_enabled:
            self.sources[SourceType.LINKEDIN] = LinkedInSource()

        if self.settings.sources.ucc_filings_enabled:
            self.sources[SourceType.UCC_FILINGS] = UCCFilingsSource()

        logger.info("Initialized sources", count=len(self.sources))

    async def __aenter__(self):
        """Async context manager entry."""
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.teardown()

    async def setup(self) -> None:
        """Initialize engine resources."""
        # Initialize database
        await init_db()

        # Setup classifier
        await self.classifier.setup()

        # Setup sources
        for source in self.sources.values():
            await source.setup()

        logger.info("DeepScanEngine initialized")

    async def teardown(self) -> None:
        """Cleanup engine resources."""
        for source in self.sources.values():
            await source.teardown()

        logger.info("DeepScanEngine shutdown complete")

    async def scan_source(
        self,
        source_type: SourceType,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        classify: bool = True,
        **kwargs,
    ) -> AsyncIterator[tuple[RawSignal, Optional[ClassificationResult]]]:
        """
        Scan a single source and yield classified signals.

        Args:
            source_type: Type of source to scan
            states: Target states
            cities: Target cities
            industries: Target industries
            classify: Whether to run LLM classification
            **kwargs: Source-specific parameters

        Yields:
            Tuple of (raw_signal, classification_result)
        """
        source = self.sources.get(source_type)
        if not source:
            logger.warning("Source not configured", source=source_type.value)
            return

        logger.info("Starting source scan", source=source_type.value)

        async for raw_signal in source.scan(
            states=states,
            cities=cities,
            industries=industries,
            **kwargs,
        ):
            classification = None

            if classify:
                try:
                    classification = await self.classifier.classify(raw_signal)
                except Exception as e:
                    logger.error("Classification error", error=str(e))

            yield raw_signal, classification

    async def process_signal(
        self,
        raw_signal: RawSignal,
        classification: Optional[ClassificationResult] = None,
    ) -> tuple[Business, Signal]:
        """
        Process a raw signal into database entities.

        Args:
            raw_signal: Raw signal from source
            classification: Optional LLM classification

        Returns:
            Tuple of (business, signal)
        """
        async with get_session() as session:
            business_repo = BusinessRepository(session)
            signal_repo = SignalRepository(session)

            # Find or create business
            business_data = {
                "name": raw_signal.business_name,
                "city": raw_signal.business_city,
                "state": raw_signal.business_state,
                "address": raw_signal.business_address,
                "phone": raw_signal.business_phone,
                "website": raw_signal.business_website,
                "industry": raw_signal.industry or (classification.industry_classification if classification else None),
                "employee_count": raw_signal.employee_count,
                "year_established": raw_signal.year_established,
                "yelp_id": raw_signal.yelp_id,
                "google_place_id": raw_signal.google_place_id,
                "linkedin_company_id": raw_signal.linkedin_id,
                "bbb_id": raw_signal.bbb_id,
            }

            # Add rating data if from review source
            if raw_signal.source_type in [SourceType.YELP, SourceType.GOOGLE_REVIEWS]:
                if raw_signal.source_type == SourceType.YELP:
                    business_data["yelp_rating"] = raw_signal.rating
                    business_data["yelp_review_count"] = raw_signal.review_count
                else:
                    business_data["google_rating"] = raw_signal.rating
                    business_data["google_review_count"] = raw_signal.review_count

            business, is_new = await business_repo.find_or_create(business_data)

            # Determine signal attributes
            if classification:
                signal_type = classification.signal_type or raw_signal.suggested_signal_type or SignalType.NEWS_MENTION
                category = classification.category or raw_signal.suggested_category or SignalCategory.EXPANSION_OPPORTUNITY
                priority = classification.priority
                confidence = classification.confidence
                signal_strength = (classification.urgency_score + classification.deal_potential_score) / 2
            else:
                signal_type = raw_signal.suggested_signal_type or SignalType.NEWS_MENTION
                category = raw_signal.suggested_category or SignalCategory.EXPANSION_OPPORTUNITY
                priority = raw_signal.suggested_priority or SignalPriority.LOW
                confidence = 0.5
                signal_strength = 5.0

            # Create signal
            signal = Signal(
                business_id=business.id,
                signal_type=signal_type,
                category=category,
                priority=priority,
                title=raw_signal.title,
                description=raw_signal.description,
                raw_content=raw_signal.raw_content,
                source_type=raw_signal.source_type,
                source_url=raw_signal.source_url,
                source_date=raw_signal.source_date,
                confidence_score=confidence,
                signal_strength=signal_strength,
                urgency_score=classification.urgency_score if classification else 5.0,
                llm_analysis=classification.llm_analysis if classification else None,
                funding_indicators=str(classification.funding_indicators) if classification else None,
                recommended_approach=classification.recommended_approach if classification else None,
                is_processed=classification is not None,
            )

            # Check for duplicate
            if raw_signal.raw_content:
                content_hash = signal_repo.generate_content_hash(raw_signal.raw_content)
                if await signal_repo.exists_by_hash(business.id, content_hash):
                    logger.debug("Duplicate signal skipped", business=business.name)
                    return business, None

                signal.content_hash = content_hash

            await signal_repo.create(signal)

            # Update business score
            score, business_priority = self.scorer.score_signal(
                classification if classification else ClassificationResult(
                    signal_type=signal_type,
                    category=category,
                    priority=priority,
                ),
                industry=business.industry,
                revenue=business.annual_revenue_estimate,
                signal_date=raw_signal.source_date,
            )

            # Update business if new score is higher
            if score > business.lead_score:
                await business_repo.update_score(business.id, score, business_priority)
                business.lead_score = score
                business.priority = business_priority

            logger.info(
                "Signal processed",
                business=business.name,
                signal_type=signal_type.value,
                priority=priority.value,
                score=score,
            )

            return business, signal

    async def run_source_scan(
        self,
        source_type: SourceType,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        **kwargs,
    ) -> dict:
        """
        Run a complete scan for a single source.

        Args:
            source_type: Source to scan
            states: Target states
            cities: Target cities
            industries: Target industries

        Returns:
            Scan statistics dict
        """
        async with get_session() as session:
            job_repo = ScanJobRepository(session)
            job = await job_repo.create(source_type, {"states": states, "industries": industries})

        stats = {
            "source": source_type.value,
            "signals_found": 0,
            "businesses_created": 0,
            "businesses_updated": 0,
            "errors": 0,
            "start_time": datetime.utcnow().isoformat(),
        }

        try:
            async for raw_signal, classification in self.scan_source(
                source_type, states, cities, industries, **kwargs
            ):
                try:
                    business, signal = await self.process_signal(raw_signal, classification)

                    if signal:
                        stats["signals_found"] += 1
                        if business:
                            stats["businesses_updated"] += 1

                except Exception as e:
                    logger.error("Error processing signal", error=str(e))
                    stats["errors"] += 1

            stats["end_time"] = datetime.utcnow().isoformat()

            # Update job
            async with get_session() as session:
                job_repo = ScanJobRepository(session)
                await job_repo.complete(
                    job.id,
                    items_scanned=stats["signals_found"] + stats["errors"],
                    signals_found=stats["signals_found"],
                    errors=stats["errors"],
                )

        except Exception as e:
            logger.error("Source scan failed", source=source_type.value, error=str(e))
            stats["error"] = str(e)

            async with get_session() as session:
                job_repo = ScanJobRepository(session)
                await job_repo.fail(job.id, str(e))

        return stats

    async def run_full_scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        sources: Optional[list[SourceType]] = None,
        parallel: bool = False,
    ) -> dict:
        """
        Run a full scan across all (or specified) sources.

        Args:
            states: Target states (default from config)
            cities: Target cities
            industries: Target industries
            sources: Specific sources to scan (default all enabled)
            parallel: Run sources in parallel (faster but more resource intensive)

        Returns:
            Combined statistics dict
        """
        target_sources = sources or list(self.sources.keys())
        states = states or self.settings.scraping.target_states

        logger.info(
            "Starting full scan",
            sources=len(target_sources),
            states=len(states),
        )

        results = {
            "start_time": datetime.utcnow().isoformat(),
            "sources": {},
            "totals": {
                "signals_found": 0,
                "errors": 0,
            },
        }

        if parallel:
            # Run all sources concurrently
            tasks = [
                self.run_source_scan(source, states, cities, industries)
                for source in target_sources
            ]
            source_results = await asyncio.gather(*tasks, return_exceptions=True)

            for source, result in zip(target_sources, source_results):
                if isinstance(result, Exception):
                    results["sources"][source.value] = {"error": str(result)}
                    results["totals"]["errors"] += 1
                else:
                    results["sources"][source.value] = result
                    results["totals"]["signals_found"] += result.get("signals_found", 0)
                    results["totals"]["errors"] += result.get("errors", 0)
        else:
            # Run sequentially
            for source in target_sources:
                try:
                    result = await self.run_source_scan(source, states, cities, industries)
                    results["sources"][source.value] = result
                    results["totals"]["signals_found"] += result.get("signals_found", 0)
                    results["totals"]["errors"] += result.get("errors", 0)
                except Exception as e:
                    logger.error("Source scan failed", source=source.value, error=str(e))
                    results["sources"][source.value] = {"error": str(e)}
                    results["totals"]["errors"] += 1

        results["end_time"] = datetime.utcnow().isoformat()

        logger.info(
            "Full scan complete",
            signals=results["totals"]["signals_found"],
            errors=results["totals"]["errors"],
        )

        return results

    async def get_hot_leads(self, limit: int = 50) -> list[dict]:
        """
        Get highest priority leads for immediate outreach.

        Returns list of lead dicts with business info and signals.
        """
        async with get_session() as session:
            business_repo = BusinessRepository(session)
            signal_repo = SignalRepository(session)

            hot_businesses = await business_repo.get_hot_leads(limit)

            leads = []
            for business in hot_businesses:
                signals = await signal_repo.get_signals_by_business(business.id)

                leads.append({
                    "id": business.id,
                    "business_name": business.name,
                    "industry": business.industry,
                    "location": f"{business.city}, {business.state}" if business.city else business.state,
                    "phone": business.phone,
                    "website": business.website,
                    "score": business.lead_score,
                    "priority": business.priority.value,
                    "status": business.status.value,
                    "signals": [
                        {
                            "type": s.signal_type.value,
                            "category": s.category.value,
                            "title": s.title,
                            "date": s.source_date.isoformat() if s.source_date else None,
                            "source": s.source_type.value,
                            "recommended_approach": s.recommended_approach,
                        }
                        for s in signals[:5]
                    ],
                    "created_at": business.created_at.isoformat(),
                })

            return leads

    async def get_signal_stats(self, days: int = 7) -> dict:
        """Get signal statistics for the last N days."""
        async with get_session() as session:
            signal_repo = SignalRepository(session)
            return await signal_repo.get_signal_stats(days)

    async def get_classifier_stats(self) -> dict:
        """Get LLM classifier statistics."""
        return self.classifier.get_stats()


async def run_quick_scan(
    states: Optional[list[str]] = None,
    industries: Optional[list[str]] = None,
) -> dict:
    """
    Convenience function to run a quick scan.

    Usage:
        from industry_deep_scan.engine import run_quick_scan
        results = await run_quick_scan(states=["CA", "TX"])
    """
    async with DeepScanEngine() as engine:
        return await engine.run_full_scan(states=states, industries=industries)
