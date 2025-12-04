"""
Webhook Notifier
================

Sends lead data to external systems via webhooks.
Useful for CRM integration (Salesforce, HubSpot, Zoho, etc.)
"""

import hashlib
import hmac
import json
from datetime import datetime
from typing import Optional

import aiohttp
import structlog

from industry_deep_scan.config import get_settings
from industry_deep_scan.models import SignalPriority

logger = structlog.get_logger()
settings = get_settings()


class WebhookNotifier:
    """
    Webhook notification channel.

    Sends JSON payloads to configured endpoints for:
    - New lead alerts (for CRM creation)
    - Signal events (for automation triggers)
    - Scan completion (for monitoring)
    """

    def __init__(self):
        self.webhook_url = settings.notifications.webhook_url
        self.secret = settings.notifications.webhook_secret.get_secret_value()
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _sign_payload(self, payload: str) -> str:
        """Generate HMAC signature for payload."""
        if not self.secret:
            return ""

        return hmac.new(
            self.secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def send_alert(
        self,
        message: dict,
        priority: SignalPriority = SignalPriority.HIGH,
    ) -> bool:
        """
        Send lead alert to webhook endpoint.

        Payload format is designed for easy CRM mapping:
        - Standard field names
        - Flat structure where possible
        - ISO timestamps
        """
        if not self.webhook_url:
            return False

        payload = {
            "event_type": "new_lead",
            "priority": priority.value,
            "timestamp": datetime.utcnow().isoformat(),
            "lead": {
                "business_name": message.get("business_name"),
                "industry": message.get("industry"),
                "phone": message.get("phone"),
                "website": message.get("website"),
                "address": {
                    "city": message.get("location", "").split(",")[0].strip() if message.get("location") else None,
                    "state": message.get("location", "").split(",")[-1].strip() if message.get("location") else None,
                },
                "lead_score": message.get("score"),
            },
            "signal": {
                "type": message.get("signal_type"),
                "title": message.get("signal_title"),
                "source": message.get("signal_source"),
                "source_url": message.get("source_url"),
                "recommended_approach": message.get("recommended_approach"),
                "analysis": message.get("analysis"),
            },
        }

        return await self._send(payload)

    async def send_digest(self, message: dict) -> bool:
        """
        Send daily digest to webhook endpoint.
        """
        if not self.webhook_url:
            return False

        payload = {
            "event_type": "daily_digest",
            "timestamp": datetime.utcnow().isoformat(),
            "summary": message.get("summary"),
            "critical_leads": [
                {
                    "business_name": l.get("business_name"),
                    "score": l.get("score"),
                    "industry": l.get("industry"),
                }
                for l in message.get("critical_leads", [])
            ],
            "high_priority_leads": [
                {
                    "business_name": l.get("business_name"),
                    "score": l.get("score"),
                }
                for l in message.get("high_priority_leads", [])
            ],
            "stats": message.get("stats"),
        }

        return await self._send(payload)

    async def send_event(self, event_type: str, data: dict) -> bool:
        """
        Send generic event to webhook.

        Used for scan completions, errors, etc.
        """
        if not self.webhook_url:
            return False

        payload = {
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data,
        }

        return await self._send(payload)

    async def _send(self, payload: dict) -> bool:
        """Send payload to webhook endpoint."""
        try:
            session = await self._get_session()

            payload_json = json.dumps(payload)

            headers = {
                "Content-Type": "application/json",
                "X-Webhook-Signature": self._sign_payload(payload_json),
                "X-Event-Type": payload.get("event_type", "unknown"),
                "X-Timestamp": payload.get("timestamp", ""),
            }

            async with session.post(
                self.webhook_url,
                data=payload_json,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status in [200, 201, 202, 204]:
                    logger.info(
                        "Webhook sent",
                        event=payload.get("event_type"),
                        status=response.status,
                    )
                    return True
                else:
                    logger.error(
                        "Webhook failed",
                        status=response.status,
                        response=await response.text(),
                    )
                    return False

        except Exception as e:
            logger.error("Webhook error", error=str(e))
            return False

    async def close(self):
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()


class CRMWebhookAdapter:
    """
    Adapter for specific CRM webhook formats.

    Extend this for custom CRM integrations.
    """

    @staticmethod
    def format_for_hubspot(message: dict) -> dict:
        """Format lead data for HubSpot webhook."""
        return {
            "properties": {
                "company": message.get("business_name"),
                "industry": message.get("industry"),
                "phone": message.get("phone"),
                "website": message.get("website"),
                "lead_score": str(message.get("score", 0)),
                "lead_source": "Industry Deep Scan",
                "notes": message.get("recommended_approach", ""),
            },
        }

    @staticmethod
    def format_for_salesforce(message: dict) -> dict:
        """Format lead data for Salesforce webhook."""
        location = message.get("location", "")
        city, state = "", ""
        if "," in location:
            parts = location.split(",")
            city = parts[0].strip()
            state = parts[-1].strip()

        return {
            "Company": message.get("business_name"),
            "Industry": message.get("industry"),
            "Phone": message.get("phone"),
            "Website": message.get("website"),
            "City": city,
            "State": state,
            "Rating": "Hot" if message.get("score", 0) >= 8 else "Warm",
            "LeadSource": "Industry Deep Scan",
            "Description": message.get("recommended_approach", ""),
        }

    @staticmethod
    def format_for_zoho(message: dict) -> dict:
        """Format lead data for Zoho CRM webhook."""
        return {
            "data": [
                {
                    "Company": message.get("business_name"),
                    "Industry": message.get("industry"),
                    "Phone": message.get("phone"),
                    "Website": message.get("website"),
                    "Lead_Source": "Industry Deep Scan",
                    "Description": message.get("recommended_approach", ""),
                    "Lead_Score": message.get("score", 0),
                }
            ],
        }
