"""
Notification System
===================

Multi-channel notification for lead alerts:
- Slack integration
- Email via SendGrid
- Webhooks for CRM integration
"""

from industry_deep_scan.notifications.service import NotificationService
from industry_deep_scan.notifications.slack import SlackNotifier
from industry_deep_scan.notifications.email import EmailNotifier
from industry_deep_scan.notifications.webhook import WebhookNotifier

__all__ = [
    "NotificationService",
    "SlackNotifier",
    "EmailNotifier",
    "WebhookNotifier",
]
