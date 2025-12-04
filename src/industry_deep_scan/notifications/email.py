"""
Email Notifier
==============

Sends lead alerts via SendGrid.
"""

from typing import Optional

import structlog

from industry_deep_scan.config import get_settings
from industry_deep_scan.models import SignalPriority

logger = structlog.get_logger()
settings = get_settings()


class EmailNotifier:
    """
    Email notification channel using SendGrid.

    Sends formatted HTML emails for:
    - High-priority lead alerts
    - Daily digests
    """

    def __init__(self):
        self.api_key = settings.notifications.sendgrid_api_key.get_secret_value()
        self.from_email = settings.notifications.email_from
        self.recipients = settings.notifications.email_recipients
        self._client = None

    def _get_client(self):
        """Get SendGrid client (lazy initialization)."""
        if self._client is None and self.api_key:
            from sendgrid import SendGridAPIClient

            self._client = SendGridAPIClient(self.api_key)
        return self._client

    async def send_alert(
        self,
        message: dict,
        priority: SignalPriority = SignalPriority.HIGH,
    ) -> bool:
        """
        Send high-priority lead alert email.
        """
        if not self.recipients:
            logger.warning("No email recipients configured")
            return False

        client = self._get_client()
        if not client:
            logger.warning("SendGrid not configured")
            return False

        subject = f"🚨 {priority.value.upper()} Lead: {message.get('business_name', 'New Lead')}"

        html_content = self._build_alert_html(message)

        try:
            from sendgrid.helpers.mail import Mail

            mail = Mail(
                from_email=self.from_email,
                to_emails=self.recipients,
                subject=subject,
                html_content=html_content,
            )

            response = client.send(mail)

            if response.status_code in [200, 202]:
                logger.info("Email alert sent", business=message.get("business_name"))
                return True
            else:
                logger.error("Email send failed", status=response.status_code)
                return False

        except Exception as e:
            logger.error("Email notification error", error=str(e))
            return False

    async def send_digest(self, message: dict) -> bool:
        """
        Send daily digest email.
        """
        if not self.recipients:
            return False

        client = self._get_client()
        if not client:
            return False

        summary = message.get("summary", {})
        subject = f"📈 Daily Lead Digest: {summary.get('total_leads', 0)} New Leads"

        html_content = self._build_digest_html(message)

        try:
            from sendgrid.helpers.mail import Mail

            mail = Mail(
                from_email=self.from_email,
                to_emails=self.recipients,
                subject=subject,
                html_content=html_content,
            )

            response = client.send(mail)

            return response.status_code in [200, 202]

        except Exception as e:
            logger.error("Email digest error", error=str(e))
            return False

    def _build_alert_html(self, message: dict) -> str:
        """Build HTML content for alert email."""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #dc3545; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
        .content {{ background: #f8f9fa; padding: 20px; border-radius: 0 0 5px 5px; }}
        .field {{ margin-bottom: 15px; }}
        .label {{ font-weight: bold; color: #666; }}
        .value {{ font-size: 16px; }}
        .score {{ font-size: 24px; font-weight: bold; color: #28a745; }}
        .approach {{ background: #e9ecef; padding: 15px; border-left: 4px solid #007bff; margin-top: 20px; }}
        .cta {{ display: inline-block; background: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚨 High Priority Lead Alert</h1>
        </div>
        <div class="content">
            <div class="field">
                <span class="label">Business:</span>
                <span class="value" style="font-size: 20px; font-weight: bold;">{message.get('business_name', 'Unknown')}</span>
            </div>

            <div class="field">
                <span class="label">Industry:</span>
                <span class="value">{message.get('industry', 'Unknown')}</span>
            </div>

            <div class="field">
                <span class="label">Location:</span>
                <span class="value">{message.get('location', 'Unknown')}</span>
            </div>

            <div class="field">
                <span class="label">Phone:</span>
                <span class="value"><a href="tel:{message.get('phone', '')}">{message.get('phone', 'N/A')}</a></span>
            </div>

            <div class="field">
                <span class="label">Website:</span>
                <span class="value"><a href="{message.get('website', '#')}">{message.get('website', 'N/A')}</a></span>
            </div>

            <div class="field">
                <span class="label">Lead Score:</span>
                <span class="score">{message.get('score', 0):.1f}/10</span>
            </div>

            <div class="field">
                <span class="label">Signal Type:</span>
                <span class="value">{message.get('signal_type', 'Unknown')}</span>
            </div>

            <div class="field">
                <span class="label">Signal:</span>
                <span class="value">{message.get('signal_title', '')}</span>
            </div>

            {f'<div class="approach"><strong>Recommended Approach:</strong><br>{message.get("recommended_approach", "")}</div>' if message.get("recommended_approach") else ''}

            {f'<a href="{message.get("source_url", "#")}" class="cta">View Source</a>' if message.get("source_url") else ''}
        </div>
    </div>
</body>
</html>
"""

    def _build_digest_html(self, message: dict) -> str:
        """Build HTML content for digest email."""
        summary = message.get("summary", {})
        critical = message.get("critical_leads", [])
        high = message.get("high_priority_leads", [])

        critical_rows = "".join([
            f"<tr><td>{l.get('business_name', 'Unknown')}</td><td>{l.get('industry', 'N/A')}</td><td>{l.get('score', 0):.1f}</td></tr>"
            for l in critical[:5]
        ])

        high_rows = "".join([
            f"<tr><td>{l.get('business_name', 'Unknown')}</td><td>{l.get('industry', 'N/A')}</td><td>{l.get('score', 0):.1f}</td></tr>"
            for l in high[:10]
        ])

        return f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 700px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #28a745; color: white; padding: 20px; text-align: center; border-radius: 5px; }}
        .stats {{ display: flex; justify-content: space-around; padding: 20px; background: #f8f9fa; margin: 20px 0; border-radius: 5px; }}
        .stat {{ text-align: center; }}
        .stat-value {{ font-size: 32px; font-weight: bold; color: #007bff; }}
        .stat-label {{ font-size: 12px; color: #666; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f1f1f1; }}
        .section-title {{ font-size: 18px; font-weight: bold; margin-top: 30px; padding-bottom: 10px; border-bottom: 2px solid #dc3545; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📈 Daily Lead Digest</h1>
            <p>{message.get('title', 'Your daily summary of new leads')}</p>
        </div>

        <div class="stats">
            <div class="stat">
                <div class="stat-value">{summary.get('total_leads', 0)}</div>
                <div class="stat-label">Total Leads</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: #dc3545;">{summary.get('critical_leads', 0)}</div>
                <div class="stat-label">🚨 Critical</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: #ffc107;">{summary.get('high_priority_leads', 0)}</div>
                <div class="stat-label">⚡ High Priority</div>
            </div>
            <div class="stat">
                <div class="stat-value">{summary.get('new_signals_24h', 0)}</div>
                <div class="stat-label">New Signals</div>
            </div>
        </div>

        {f'''
        <div class="section-title">🚨 Critical Leads - Call Immediately</div>
        <table>
            <tr><th>Business</th><th>Industry</th><th>Score</th></tr>
            {critical_rows}
        </table>
        ''' if critical else ''}

        {f'''
        <div class="section-title">⚡ High Priority Leads</div>
        <table>
            <tr><th>Business</th><th>Industry</th><th>Score</th></tr>
            {high_rows}
        </table>
        ''' if high else ''}

        <p style="text-align: center; margin-top: 30px; color: #666;">
            <small>Generated by Industry Deep Scan</small>
        </p>
    </div>
</body>
</html>
"""
