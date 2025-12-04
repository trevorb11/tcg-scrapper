"""
Scan Scheduler
==============

Automated scheduling of source scans using APScheduler.

Supports:
- Configurable intervals per source
- Cron-style scheduling
- Daily digest generation
- Graceful shutdown
"""

import asyncio
from datetime import datetime
from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from industry_deep_scan.config import get_settings
from industry_deep_scan.engine import DeepScanEngine
from industry_deep_scan.models import SourceType

logger = structlog.get_logger()
settings = get_settings()


class ScanScheduler:
    """
    Automated scan scheduler.

    Manages scheduled execution of source scans at configurable intervals.
    """

    def __init__(self, engine: Optional[DeepScanEngine] = None):
        self.engine = engine
        self.scheduler = AsyncIOScheduler()
        self._running = False

    async def setup(self) -> None:
        """Initialize scheduler and engine."""
        if self.engine is None:
            self.engine = DeepScanEngine()
            await self.engine.setup()

        self._configure_jobs()

        logger.info("Scheduler initialized")

    async def teardown(self) -> None:
        """Shutdown scheduler."""
        if self._running:
            self.scheduler.shutdown(wait=True)
            self._running = False

        if self.engine:
            await self.engine.teardown()

        logger.info("Scheduler shutdown complete")

    def _configure_jobs(self) -> None:
        """Configure scheduled jobs based on settings."""
        scheduler_settings = settings.scheduler

        # News scans (frequent)
        self.scheduler.add_job(
            self._scan_news,
            trigger=IntervalTrigger(minutes=scheduler_settings.news_scan_interval),
            id="scan_news",
            name="News Source Scan",
            replace_existing=True,
        )

        # Review scans (every 2 hours)
        self.scheduler.add_job(
            self._scan_reviews,
            trigger=IntervalTrigger(minutes=scheduler_settings.review_scan_interval),
            id="scan_reviews",
            name="Review Source Scan",
            replace_existing=True,
        )

        # BBB scans (every 6 hours)
        self.scheduler.add_job(
            self._scan_bbb,
            trigger=IntervalTrigger(minutes=scheduler_settings.bbb_scan_interval),
            id="scan_bbb",
            name="BBB Source Scan",
            replace_existing=True,
        )

        # Business listings (hourly)
        self.scheduler.add_job(
            self._scan_listings,
            trigger=IntervalTrigger(minutes=scheduler_settings.listings_scan_interval),
            id="scan_listings",
            name="Business Listings Scan",
            replace_existing=True,
        )

        # Court records / liens (every 12 hours)
        self.scheduler.add_job(
            self._scan_liens,
            trigger=IntervalTrigger(minutes=scheduler_settings.liens_scan_interval),
            id="scan_liens",
            name="Court Records Scan",
            replace_existing=True,
        )

        # Permit filings (every 12 hours)
        self.scheduler.add_job(
            self._scan_permits,
            trigger=IntervalTrigger(minutes=scheduler_settings.permits_scan_interval),
            id="scan_permits",
            name="Permit Filings Scan",
            replace_existing=True,
        )

        # Daily digest (8 AM)
        self.scheduler.add_job(
            self._send_daily_digest,
            trigger=CronTrigger(hour=settings.notifications.daily_digest_hour, minute=0),
            id="daily_digest",
            name="Daily Lead Digest",
            replace_existing=True,
        )

        # Full refresh (nightly at 2 AM)
        self.scheduler.add_job(
            self._full_refresh,
            trigger=CronTrigger(hour=2, minute=0),
            id="full_refresh",
            name="Full Data Refresh",
            replace_existing=True,
        )

        # Reset classifier daily stats (midnight)
        self.scheduler.add_job(
            self._reset_daily_stats,
            trigger=CronTrigger(hour=0, minute=0),
            id="reset_stats",
            name="Reset Daily Stats",
            replace_existing=True,
        )

        logger.info("Scheduled jobs configured", job_count=len(self.scheduler.get_jobs()))

    async def start(self) -> None:
        """Start the scheduler."""
        if not self._running:
            self.scheduler.start()
            self._running = True
            logger.info("Scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        await self.teardown()

    def get_jobs(self) -> list[dict]:
        """Get list of scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return jobs

    # === Scan Job Implementations ===

    async def _scan_news(self) -> None:
        """Scan news sources."""
        logger.info("Running scheduled news scan")
        try:
            result = await self.engine.run_source_scan(SourceType.NEWS)
            logger.info("News scan complete", signals=result.get("signals_found", 0))
        except Exception as e:
            logger.error("News scan failed", error=str(e))

    async def _scan_reviews(self) -> None:
        """Scan review sources (Yelp, Google)."""
        logger.info("Running scheduled review scan")
        try:
            result = await self.engine.run_source_scan(SourceType.YELP)
            logger.info("Review scan complete", signals=result.get("signals_found", 0))
        except Exception as e:
            logger.error("Review scan failed", error=str(e))

    async def _scan_bbb(self) -> None:
        """Scan BBB for complaints."""
        logger.info("Running scheduled BBB scan")
        try:
            result = await self.engine.run_source_scan(SourceType.BBB)
            logger.info("BBB scan complete", signals=result.get("signals_found", 0))
        except Exception as e:
            logger.error("BBB scan failed", error=str(e))

    async def _scan_listings(self) -> None:
        """Scan business-for-sale listings."""
        logger.info("Running scheduled listings scan")
        try:
            result = await self.engine.run_source_scan(SourceType.BUSINESS_LISTINGS)
            logger.info("Listings scan complete", signals=result.get("signals_found", 0))
        except Exception as e:
            logger.error("Listings scan failed", error=str(e))

    async def _scan_liens(self) -> None:
        """Scan court records for liens."""
        logger.info("Running scheduled liens scan")
        try:
            result = await self.engine.run_source_scan(SourceType.COURT_RECORDS)
            logger.info("Liens scan complete", signals=result.get("signals_found", 0))
        except Exception as e:
            logger.error("Liens scan failed", error=str(e))

    async def _scan_permits(self) -> None:
        """Scan permit filings."""
        logger.info("Running scheduled permits scan")
        try:
            result = await self.engine.run_source_scan(SourceType.EQUIPMENT_PERMITS)
            logger.info("Permits scan complete", signals=result.get("signals_found", 0))
        except Exception as e:
            logger.error("Permits scan failed", error=str(e))

    async def _send_daily_digest(self) -> None:
        """Send daily lead digest."""
        if not settings.notifications.daily_digest_enabled:
            return

        logger.info("Generating daily digest")
        try:
            # Get hot leads
            leads = await self.engine.get_hot_leads(limit=20)
            stats = await self.engine.get_signal_stats(days=1)

            # Import notification module
            from industry_deep_scan.notifications import NotificationService

            notifier = NotificationService()
            await notifier.send_daily_digest(leads, stats)

            logger.info("Daily digest sent", lead_count=len(leads))
        except Exception as e:
            logger.error("Daily digest failed", error=str(e))

    async def _full_refresh(self) -> None:
        """Run full data refresh (all sources)."""
        logger.info("Running full data refresh")
        try:
            result = await self.engine.run_full_scan()
            logger.info(
                "Full refresh complete",
                signals=result["totals"]["signals_found"],
                errors=result["totals"]["errors"],
            )
        except Exception as e:
            logger.error("Full refresh failed", error=str(e))

    async def _reset_daily_stats(self) -> None:
        """Reset daily statistics counters."""
        logger.info("Resetting daily stats")
        self.engine.classifier.reset_daily_stats()


async def run_scheduler() -> None:
    """
    Run the scheduler as a standalone service.

    Usage:
        python -m industry_deep_scan.scheduler
    """
    scheduler = ScanScheduler()

    try:
        await scheduler.setup()
        await scheduler.start()

        # Keep running until interrupted
        logger.info("Scheduler running. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(60)

    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        await scheduler.stop()


if __name__ == "__main__":
    asyncio.run(run_scheduler())
