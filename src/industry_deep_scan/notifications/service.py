"""
Notification Service
====================

Orchestrates multi-channel notifications for lead alerts.
"""

import asyncio
from datetime import datetime
from typing import Optional

import structlog

from industry_deep_scan.config import get_settings
from industry_deep_scan.models import Business, Signal, SignalPriority

logger = structlog.get_logger()
settings = get_settings()


class NotificationService:
    """
    Central notification service.

    Coordinates sending alerts across multiple channels:
    - Slack for instant team notifications
    - Email for daily digests and high-priority alerts
    - Webhooks for CRM/system integration
    """

    def __init__(self):
        self.settings = settings.notifications
        self._notifiers = []
        self._setup_notifiers()

    def _setup_notifiers(self) -> None:
        """Initialize enabled notification channels."""
        if self.settings.slack_enabled:
            from industry_deep_scan.notifications.slack import SlackNotifier

            self._notifiers.append(SlackNotifier())
            logger.info("Slack notifications enabled")

        if self.settings.email_enabled:
            from industry_deep_scan.notifications.email import EmailNotifier

            self._notifiers.append(EmailNotifier())
            logger.info("Email notifications enabled")

        if self.settings.webhook_enabled:
            from industry_deep_scan.notifications.webhook import WebhookNotifier

            self._notifiers.append(WebhookNotifier())
            logger.info("Webhook notifications enabled")

    async def notify_high_priority_signal(
        self,
        business: Business,
        signal: Signal,
    ) -> None:
        """
        Send immediate notification for high-priority signals.

        Called when a critical or high-priority signal is detected.
        """
        if signal.priority not in [SignalPriority.CRITICAL, SignalPriority.HIGH]:
            return

        if not self._notifiers:
            return

        message = self._format_signal_alert(business, signal)

        tasks = [
            notifier.send_alert(message, priority=signal.priority)
            for notifier in self._notifiers
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(
            "High-priority notification sent",
            business=business.name,
            priority=signal.priority.value,
        )

    async def send_daily_digest(
        self,
        leads: list[dict],
        stats: dict,
    ) -> None:
        """
        Send daily digest of leads and activity.

        Called by the scheduler each morning.
        """
        if not self._notifiers:
            return

        message = self._format_daily_digest(leads, stats)

        tasks = [
            notifier.send_digest(message)
            for notifier in self._notifiers
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Daily digest sent", lead_count=len(leads))

    async def send_scan_complete(
        self,
        results: dict,
    ) -> None:
        """
        Notify when a scan completes (for monitoring).
        """
        if not self._notifiers:
            return

        message = self._format_scan_complete(results)

        # Only send to webhook (not spam Slack/email with scan completions)
        for notifier in self._notifiers:
            if hasattr(notifier, "send_event"):
                await notifier.send_event("scan_complete", message)

    def _format_signal_alert(self, business: Business, signal: Signal) -> dict:
        """Format signal alert message."""
        priority_emoji = {
            SignalPriority.CRITICAL: "🚨",
            SignalPriority.HIGH: "⚡",
            SignalPriority.MEDIUM: "📊",
            SignalPriority.LOW: "ℹ️",
        }

        return {
            "title": f"{priority_emoji.get(signal.priority, '📊')} New {signal.priority.value.upper()} Priority Lead",
            "business_name": business.name,
            "industry": business.industry or "Unknown",
            "location": f"{business.city}, {business.state}" if business.city else business.state or "Unknown",
            "phone": business.phone or "Not available",
            "website": business.website or "Not available",
            "score": business.lead_score,
            "signal_type": signal.signal_type.value,
            "signal_title": signal.title,
            "signal_source": signal.source_type.value,
            "source_url": signal.source_url or "",
            "recommended_approach": signal.recommended_approach or "",
            "analysis": signal.llm_analysis or "",
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _format_daily_digest(self, leads: list[dict], stats: dict) -> dict:
        """Format daily digest message."""
        # Categorize leads
        critical = [l for l in leads if l.get("priority") == "critical"]
        high = [l for l in leads if l.get("priority") == "high"]

        return {
            "title": f"📈 Daily Lead Digest - {datetime.now().strftime('%B %d, %Y')}",
            "summary": {
                "total_leads": len(leads),
                "critical_leads": len(critical),
                "high_priority_leads": len(high),
                "new_signals_24h": stats.get("total", 0),
            },
            "critical_leads": critical[:5],
            "high_priority_leads": high[:10],
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _format_scan_complete(self, results: dict) -> dict:
        """Format scan complete message."""
        return {
            "event": "scan_complete",
            "signals_found": results.get("totals", {}).get("signals_found", 0),
            "errors": results.get("totals", {}).get("errors", 0),
            "sources": list(results.get("sources", {}).keys()),
            "start_time": results.get("start_time"),
            "end_time": results.get("end_time"),
            "timestamp": datetime.utcnow().isoformat(),
        }
