"""
LinkedIn Source Connector
=========================

Monitor LinkedIn for company signals:
- Hiring freezes / layoffs
- New contracts / partnerships
- Expansion announcements
- Leadership changes

Note: LinkedIn's ToS restricts scraping. This module is designed for:
1. Manual data import (CSV from Sales Navigator)
2. Official LinkedIn API (requires partnership)
3. Light monitoring of public company pages
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

import structlog

from industry_deep_scan.models import SignalCategory, SignalPriority, SignalType, SourceType
from industry_deep_scan.sources.base import BaseSource, RawSignal

logger = structlog.get_logger()


class LinkedInSource(BaseSource):
    """
    LinkedIn data source for company signals.

    Supports multiple input methods:
    1. CSV import from Sales Navigator exports
    2. JSON import from API integrations
    3. Manual entry via the UI

    For automated LinkedIn data, consider integrating with:
    - LinkedIn Marketing API (for advertising customers)
    - PhantomBuster (third-party automation)
    - Clay.com (enrichment platform)
    """

    source_type = SourceType.LINKEDIN

    # Signal keywords for classification
    SIGNAL_PATTERNS = {
        # Growth signals
        "hiring": (SignalType.HIRING_SURGE, SignalCategory.RAPID_GROWTH),
        "we're hiring": (SignalType.HIRING_SURGE, SignalCategory.RAPID_GROWTH),
        "join our team": (SignalType.HIRING_SURGE, SignalCategory.RAPID_GROWTH),
        "new positions": (SignalType.HIRING_SURGE, SignalCategory.RAPID_GROWTH),
        "expansion": (SignalType.EXPANSION, SignalCategory.RAPID_GROWTH),
        "new office": (SignalType.NEW_LOCATION, SignalCategory.EXPANSION_OPPORTUNITY),
        "new location": (SignalType.NEW_LOCATION, SignalCategory.EXPANSION_OPPORTUNITY),
        "grand opening": (SignalType.NEW_LOCATION, SignalCategory.EXPANSION_OPPORTUNITY),
        "partnership": (SignalType.NEW_CONTRACT, SignalCategory.RAPID_GROWTH),
        "contract": (SignalType.NEW_CONTRACT, SignalCategory.RAPID_GROWTH),
        "deal": (SignalType.NEW_CONTRACT, SignalCategory.RAPID_GROWTH),

        # Distress signals
        "layoff": (SignalType.LAYOFFS, SignalCategory.DISTRESS_HIGH_REVENUE),
        "restructuring": (SignalType.LAYOFFS, SignalCategory.DISTRESS_HIGH_REVENUE),
        "downsizing": (SignalType.LAYOFFS, SignalCategory.DISTRESS_HIGH_REVENUE),
        "workforce reduction": (SignalType.LAYOFFS, SignalCategory.DISTRESS_HIGH_REVENUE),
        "hiring freeze": (SignalType.CASH_SQUEEZE, SignalCategory.CASH_FLOW_STRESS),
        "cost cutting": (SignalType.CASH_SQUEEZE, SignalCategory.CASH_FLOW_STRESS),
        "budget cuts": (SignalType.CASH_SQUEEZE, SignalCategory.CASH_FLOW_STRESS),

        # Equipment / investment
        "new equipment": (SignalType.EQUIPMENT_PURCHASE, SignalCategory.EXPANSION_OPPORTUNITY),
        "fleet": (SignalType.EQUIPMENT_PURCHASE, SignalCategory.EXPANSION_OPPORTUNITY),
        "machinery": (SignalType.EQUIPMENT_PURCHASE, SignalCategory.EXPANSION_OPPORTUNITY),
    }

    async def import_from_csv(
        self,
        file_path: str,
        name_column: str = "Company Name",
        update_column: str = "Latest Update",
        **column_mappings,
    ) -> AsyncIterator[RawSignal]:
        """
        Import LinkedIn data from CSV export.

        Expected columns:
        - Company Name
        - Industry
        - Company Size
        - Location
        - Website
        - Latest Update (company post text)
        - Employee Count
        """
        path = Path(file_path)
        if not path.exists():
            self.logger.error("LinkedIn CSV file not found", path=file_path)
            return

        self.logger.info("Importing LinkedIn data from CSV", path=file_path)

        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    company_name = row.get(name_column, "").strip()
                    if not company_name:
                        continue

                    update_text = row.get(update_column, "").strip()

                    # Detect signal from update text
                    signal_type = None
                    category = None

                    if update_text:
                        text_lower = update_text.lower()
                        for keyword, (sig_type, cat) in self.SIGNAL_PATTERNS.items():
                            if keyword in text_lower:
                                signal_type = sig_type
                                category = cat
                                break

                    # Skip if no signal detected
                    if not signal_type:
                        continue

                    # Parse location
                    location = row.get(column_mappings.get("location", "Location"), "")
                    city, state = None, None
                    if location:
                        parts = [p.strip() for p in location.split(",")]
                        if len(parts) >= 2:
                            city = parts[0]
                            state = self.parse_state(parts[-1])

                    # Parse employee count
                    employee_str = row.get(column_mappings.get("employees", "Employee Count"), "")
                    employee_count = None
                    if employee_str:
                        import re
                        match = re.search(r"(\d+)", employee_str.replace(",", ""))
                        if match:
                            employee_count = int(match.group(1))

                    signal = RawSignal(
                        business_name=company_name,
                        business_city=city,
                        business_state=state,
                        business_website=row.get(column_mappings.get("website", "Website")),
                        title=f"LinkedIn Signal: {company_name}",
                        description=update_text[:500] if update_text else f"{signal_type.value} detected",
                        raw_content=update_text or f"Signal type: {signal_type.value}",
                        source_type=self.source_type,
                        source_date=datetime.utcnow(),
                        suggested_signal_type=signal_type,
                        suggested_category=category,
                        suggested_priority=SignalPriority.MEDIUM,
                        industry=row.get(column_mappings.get("industry", "Industry")),
                        employee_count=employee_count,
                        linkedin_id=row.get(column_mappings.get("linkedin_id", "LinkedIn ID")),
                        metadata={
                            "company_size": row.get("Company Size"),
                            "import_source": "csv",
                        },
                    )

                    if await self.validate_signal(signal):
                        yield signal

                except Exception as e:
                    self.logger.warning("Error processing LinkedIn CSV row", error=str(e))
                    continue

    async def import_from_json(self, file_path: str) -> AsyncIterator[RawSignal]:
        """
        Import LinkedIn data from JSON file.

        Expected format:
        [
            {
                "company_name": "Acme Corp",
                "linkedin_id": "acme-corp",
                "industry": "Construction",
                "employee_count": 50,
                "location": {"city": "Denver", "state": "CO"},
                "recent_posts": [
                    {"text": "We're hiring 10 new positions!", "date": "2024-01-15"}
                ]
            }
        ]
        """
        path = Path(file_path)
        if not path.exists():
            self.logger.error("LinkedIn JSON file not found", path=file_path)
            return

        self.logger.info("Importing LinkedIn data from JSON", path=file_path)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for company in data:
            try:
                company_name = company.get("company_name", "").strip()
                if not company_name:
                    continue

                # Process each recent post
                posts = company.get("recent_posts", [])

                for post in posts:
                    post_text = post.get("text", "")

                    # Detect signal
                    signal_type = None
                    category = None

                    if post_text:
                        text_lower = post_text.lower()
                        for keyword, (sig_type, cat) in self.SIGNAL_PATTERNS.items():
                            if keyword in text_lower:
                                signal_type = sig_type
                                category = cat
                                break

                    if not signal_type:
                        continue

                    location = company.get("location", {})

                    signal = RawSignal(
                        business_name=company_name,
                        business_city=location.get("city"),
                        business_state=location.get("state"),
                        business_website=company.get("website"),
                        title=f"LinkedIn Signal: {company_name}",
                        description=post_text[:500],
                        raw_content=post_text,
                        source_type=self.source_type,
                        source_url=f"https://linkedin.com/company/{company.get('linkedin_id', '')}",
                        source_date=datetime.fromisoformat(post.get("date")) if post.get("date") else datetime.utcnow(),
                        suggested_signal_type=signal_type,
                        suggested_category=category,
                        suggested_priority=SignalPriority.MEDIUM,
                        industry=company.get("industry"),
                        employee_count=company.get("employee_count"),
                        linkedin_id=company.get("linkedin_id"),
                        metadata={
                            "import_source": "json",
                        },
                    )

                    if await self.validate_signal(signal):
                        yield signal

            except Exception as e:
                self.logger.warning("Error processing LinkedIn JSON entry", error=str(e))
                continue

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        import_file: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan LinkedIn for signals.

        For automated scanning, provide an import file (CSV or JSON)
        that was generated from Sales Navigator or a third-party tool.

        Args:
            states: Not used for import mode
            cities: Not used for import mode
            industries: Filter imported data by industry
            import_file: Path to CSV or JSON file to import
        """
        if not import_file:
            self.logger.info(
                "LinkedIn scan requires import_file parameter. "
                "Use Sales Navigator export or third-party tool to generate data."
            )
            return

        path = Path(import_file)

        if path.suffix.lower() == ".csv":
            async for signal in self.import_from_csv(import_file):
                # Filter by industry if specified
                if industries and signal.industry:
                    if not any(ind.lower() in signal.industry.lower() for ind in industries):
                        continue
                yield signal

        elif path.suffix.lower() == ".json":
            async for signal in self.import_from_json(import_file):
                if industries and signal.industry:
                    if not any(ind.lower() in signal.industry.lower() for ind in industries):
                        continue
                yield signal

        else:
            self.logger.error("Unsupported file format", suffix=path.suffix)


class LinkedInManualEntry:
    """
    Helper class for manually adding LinkedIn signals.

    Use this when a sales rep spots a signal on LinkedIn manually.
    """

    @staticmethod
    def create_signal(
        company_name: str,
        signal_type: SignalType,
        description: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        linkedin_url: Optional[str] = None,
        employee_count: Optional[int] = None,
        industry: Optional[str] = None,
        added_by: Optional[str] = None,
    ) -> RawSignal:
        """Create a manual LinkedIn signal entry."""
        # Map signal type to category
        category_map = {
            SignalType.HIRING_SURGE: SignalCategory.RAPID_GROWTH,
            SignalType.EXPANSION: SignalCategory.RAPID_GROWTH,
            SignalType.NEW_LOCATION: SignalCategory.EXPANSION_OPPORTUNITY,
            SignalType.NEW_CONTRACT: SignalCategory.RAPID_GROWTH,
            SignalType.LAYOFFS: SignalCategory.DISTRESS_HIGH_REVENUE,
            SignalType.CASH_SQUEEZE: SignalCategory.CASH_FLOW_STRESS,
            SignalType.EQUIPMENT_PURCHASE: SignalCategory.EXPANSION_OPPORTUNITY,
        }

        return RawSignal(
            business_name=company_name,
            business_city=city,
            business_state=state,
            title=f"LinkedIn Signal: {company_name}",
            description=description,
            raw_content=description,
            source_type=SourceType.LINKEDIN,
            source_url=linkedin_url,
            source_date=datetime.utcnow(),
            suggested_signal_type=signal_type,
            suggested_category=category_map.get(signal_type, SignalCategory.RAPID_GROWTH),
            suggested_priority=SignalPriority.MEDIUM,
            industry=industry,
            employee_count=employee_count,
            metadata={
                "entry_type": "manual",
                "added_by": added_by,
            },
        )
