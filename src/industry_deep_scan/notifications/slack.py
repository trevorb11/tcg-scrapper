"""
Slack Notifier
==============

Sends lead alerts and digests to Slack.
"""

import asyncio
from typing import Optional

import structlog
from slack_sdk.webhook.async_client import AsyncWebhookClient

from industry_deep_scan.config import get_settings
from industry_deep_scan.models import SignalPriority

logger = structlog.get_logger()
settings = get_settings()


class SlackNotifier:
    """
    Slack notification channel using webhooks.

    Sends formatted messages to a Slack channel for:
    - High-priority lead alerts (immediate)
    - Daily digests (scheduled)
    - Scan status updates (optional)
    """

    def __init__(self):
        self.webhook_url = settings.notifications.slack_webhook_url.get_secret_value()
        self.channel = settings.notifications.slack_channel
        self.client = AsyncWebhookClient(self.webhook_url) if self.webhook_url else None

    async def send_alert(
        self,
        message: dict,
        priority: SignalPriority = SignalPriority.HIGH,
    ) -> bool:
        """
        Send high-priority lead alert to Slack.
        """
        if not self.client:
            logger.warning("Slack not configured, skipping notification")
            return False

        # Build Slack blocks
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": message.get("title", "New Lead Alert"),
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Business:*\n{message.get('business_name', 'Unknown')}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Industry:*\n{message.get('industry', 'Unknown')}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Location:*\n{message.get('location', 'Unknown')}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Score:*\n{message.get('score', 0):.1f}/10",
                    },
                ],
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Phone:*\n{message.get('phone', 'N/A')}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Signal:*\n{message.get('signal_type', 'Unknown')}",
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Signal Details:*\n{message.get('signal_title', '')}",
                },
            },
        ]

        # Add recommended approach if available
        if message.get("recommended_approach"):
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Recommended Approach:*\n_{message['recommended_approach'][:500]}_",
                },
            })

        # Add source link if available
        if message.get("source_url"):
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<{message['source_url']}|View Source>",
                },
            })

        # Add divider
        blocks.append({"type": "divider"})

        try:
            response = await self.client.send(
                text=f"New {priority.value} priority lead: {message.get('business_name', 'Unknown')}",
                blocks=blocks,
            )

            if response.status_code == 200:
                logger.info("Slack alert sent", business=message.get("business_name"))
                return True
            else:
                logger.error("Slack alert failed", status=response.status_code)
                return False

        except Exception as e:
            logger.error("Slack notification error", error=str(e))
            return False

    async def send_digest(self, message: dict) -> bool:
        """
        Send daily digest to Slack.
        """
        if not self.client:
            return False

        summary = message.get("summary", {})

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": message.get("title", "Daily Lead Digest"),
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Total New Leads:*\n{summary.get('total_leads', 0)}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*🚨 Critical:*\n{summary.get('critical_leads', 0)}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*⚡ High Priority:*\n{summary.get('high_priority_leads', 0)}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Signals (24h):*\n{summary.get('new_signals_24h', 0)}",
                    },
                ],
            },
            {"type": "divider"},
        ]

        # Add critical leads
        critical_leads = message.get("critical_leads", [])
        if critical_leads:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*🚨 Critical Leads - Call Immediately:*",
                },
            })

            for lead in critical_leads[:3]:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"• *{lead.get('business_name', 'Unknown')}* "
                            f"({lead.get('industry', 'N/A')}) - "
                            f"Score: {lead.get('score', 0):.1f}"
                        ),
                    },
                })

        # Add high priority leads
        high_leads = message.get("high_priority_leads", [])
        if high_leads:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*⚡ High Priority Leads:*",
                },
            })

            lead_list = "\n".join([
                f"• {l.get('business_name', 'Unknown')} - Score: {l.get('score', 0):.1f}"
                for l in high_leads[:5]
            ])

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": lead_list,
                },
            })

        try:
            response = await self.client.send(
                text=f"Daily Digest: {summary.get('total_leads', 0)} new leads",
                blocks=blocks,
            )

            return response.status_code == 200

        except Exception as e:
            logger.error("Slack digest error", error=str(e))
            return False
