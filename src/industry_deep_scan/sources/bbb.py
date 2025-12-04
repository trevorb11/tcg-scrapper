"""
Better Business Bureau Source Connector
========================================

Monitor BBB for:
- New complaints (cash flow/service issues)
- Rating changes
- Accreditation status changes
- Unresolved complaints

High complaint volume often indicates cash flow problems
(can't fulfill orders, understaffed, quality issues).
"""

import asyncio
import re
from datetime import datetime
from typing import AsyncIterator, Optional
from urllib.parse import quote_plus

import structlog

from industry_deep_scan.models import SignalCategory, SignalPriority, SignalType, SourceType
from industry_deep_scan.sources.base import BaseSource, RawSignal

logger = structlog.get_logger()


class BBBSource(BaseSource):
    """
    Better Business Bureau scraper for complaint monitoring.

    Targets the BBB search and business profile pages.
    """

    source_type = SourceType.BBB
    BBB_BASE_URL = "https://www.bbb.org"

    # BBB rating to numeric score
    RATING_SCORES = {
        "A+": 4.3, "A": 4.0, "A-": 3.7,
        "B+": 3.3, "B": 3.0, "B-": 2.7,
        "C+": 2.3, "C": 2.0, "C-": 1.7,
        "D+": 1.3, "D": 1.0, "D-": 0.7,
        "F": 0.3, "NR": 0,
    }

    # Thresholds for signals
    MIN_COMPLAINTS_FOR_SIGNAL = 3  # At least 3 complaints
    COMPLAINT_RECENCY_DAYS = 365  # Look at last year

    # Industry categories on BBB
    INDUSTRY_CATEGORIES = {
        "construction": "construction",
        "contractor": "general-contractors",
        "restaurant": "restaurants",
        "auto_repair": "auto-repair-service",
        "trucking": "trucking",
        "medical": "physicians-surgeons",
        "plumbing": "plumbers",
        "hvac": "heating-contractors",
        "electrical": "electricians",
        "landscaping": "landscape-contractors",
        "roofing": "roofing-contractors",
    }

    def _parse_complaint_count(self, text: str) -> int:
        """Extract complaint count from BBB text."""
        patterns = [
            r"(\d+)\s+complaints?",
            r"complaints?:\s*(\d+)",
            r"(\d+)\s+customer\s+complaints?",
        ]

        for pattern in patterns:
            match = re.search(pattern, text.lower())
            if match:
                return int(match.group(1))

        return 0

    def _parse_bbb_rating(self, text: str) -> Optional[str]:
        """Extract BBB letter rating from text."""
        match = re.search(r"\b([A-F][+-]?|NR)\b", text.upper())
        return match.group(1) if match else None

    async def search_businesses(
        self,
        location: str,
        category: Optional[str] = None,
    ) -> list[dict]:
        """
        Search BBB for businesses in a location.

        Returns list of business dictionaries with basic info.
        """
        businesses = []

        # Build search URL
        search_term = category or ""
        encoded_location = quote_plus(location)
        encoded_term = quote_plus(search_term) if search_term else ""

        url = f"{self.BBB_BASE_URL}/search?find_text={encoded_term}&find_loc={encoded_location}"

        try:
            html = await self.fetch(url)
            soup = self.parse_html(html)

            # Find business cards in search results
            # BBB's DOM structure - may need adjustment
            result_items = soup.find_all("div", class_=re.compile(r"search-result|result-item|bds-listing"))

            for item in result_items[:30]:  # Limit per search
                try:
                    # Extract business name
                    name_elem = item.find(["a", "h3", "h4"], class_=re.compile(r"business-name|name|title"))
                    if not name_elem:
                        name_elem = item.find("a", href=re.compile(r"/profile/"))

                    if not name_elem:
                        continue

                    name = name_elem.get_text(strip=True)

                    # Extract profile URL
                    profile_url = ""
                    if name_elem.name == "a" and name_elem.get("href"):
                        href = name_elem["href"]
                        profile_url = href if href.startswith("http") else f"{self.BBB_BASE_URL}{href}"

                    # Extract rating
                    rating_elem = item.find(class_=re.compile(r"rating|grade"))
                    rating = self._parse_bbb_rating(rating_elem.get_text() if rating_elem else "")

                    # Extract location
                    location_elem = item.find(class_=re.compile(r"address|location|city"))
                    address = location_elem.get_text(strip=True) if location_elem else ""

                    businesses.append({
                        "name": name,
                        "profile_url": profile_url,
                        "rating": rating,
                        "address": address,
                    })

                except Exception as e:
                    self.logger.warning("Error parsing BBB search result", error=str(e))
                    continue

        except Exception as e:
            self.logger.error("Error searching BBB", location=location, error=str(e))

        return businesses

    async def get_business_profile(self, profile_url: str) -> Optional[dict]:
        """
        Get detailed business profile from BBB.

        Returns dict with complaints, rating, accreditation status, etc.
        """
        try:
            html = await self.fetch(profile_url)
            soup = self.parse_html(html)

            profile = {
                "url": profile_url,
                "complaints_total": 0,
                "complaints_last_year": 0,
                "complaints_closed": 0,
                "rating": None,
                "is_accredited": False,
                "years_in_business": None,
                "phone": None,
                "address": None,
            }

            # Extract complaint info
            complaints_section = soup.find(class_=re.compile(r"complaints|complaint-summary"))
            if complaints_section:
                text = complaints_section.get_text()

                # Total complaints
                total_match = re.search(r"(\d+)\s+(?:total\s+)?complaints?", text.lower())
                if total_match:
                    profile["complaints_total"] = int(total_match.group(1))

                # Last 12 months
                year_match = re.search(r"(\d+)\s+(?:complaints?\s+)?(?:in\s+)?last\s+(?:12\s+months?|year)", text.lower())
                if year_match:
                    profile["complaints_last_year"] = int(year_match.group(1))

                # Closed/resolved
                closed_match = re.search(r"(\d+)\s+(?:complaints?\s+)?closed", text.lower())
                if closed_match:
                    profile["complaints_closed"] = int(closed_match.group(1))

            # Extract rating
            rating_section = soup.find(class_=re.compile(r"bbb-rating|grade-container"))
            if rating_section:
                profile["rating"] = self._parse_bbb_rating(rating_section.get_text())

            # Accreditation status
            accredited_badge = soup.find(class_=re.compile(r"accredited|seal"))
            profile["is_accredited"] = accredited_badge is not None

            # Years in business
            years_elem = soup.find(text=re.compile(r"years?\s+in\s+business", re.I))
            if years_elem:
                years_match = re.search(r"(\d+)\s+years?", years_elem.string or str(years_elem.parent))
                if years_match:
                    profile["years_in_business"] = int(years_match.group(1))

            # Contact info
            phone_elem = soup.find(class_=re.compile(r"phone|telephone"))
            if phone_elem:
                profile["phone"] = self.extract_phone(phone_elem.get_text())

            address_elem = soup.find(class_=re.compile(r"address|location"))
            if address_elem:
                profile["address"] = address_elem.get_text(strip=True)

            return profile

        except Exception as e:
            self.logger.error("Error fetching BBB profile", url=profile_url, error=str(e))
            return None

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        min_complaints: int = 3,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan BBB for businesses with complaint signals.

        Args:
            states: Target state codes
            cities: Target cities (more precise)
            industries: Target industries
            min_complaints: Minimum complaints to trigger signal
        """
        # Build location list
        locations = []
        target_states = states or self.settings.scraping.target_states[:5]

        if cities:
            locations = cities
        else:
            # Use state capitals and major cities
            state_cities = {
                "CA": ["Los Angeles, CA", "San Francisco, CA", "San Diego, CA"],
                "TX": ["Houston, TX", "Dallas, TX", "Austin, TX", "San Antonio, TX"],
                "FL": ["Miami, FL", "Tampa, FL", "Orlando, FL", "Jacksonville, FL"],
                "NY": ["New York, NY", "Buffalo, NY", "Albany, NY"],
                "IL": ["Chicago, IL"],
                "PA": ["Philadelphia, PA", "Pittsburgh, PA"],
                "OH": ["Columbus, OH", "Cleveland, OH", "Cincinnati, OH"],
                "GA": ["Atlanta, GA"],
                "NC": ["Charlotte, NC", "Raleigh, NC"],
                "MI": ["Detroit, MI", "Grand Rapids, MI"],
            }

            for state in target_states:
                locations.extend(state_cities.get(state, [state]))

        # Build category list
        target_industries = industries or ["construction", "contractor", "auto_repair", "restaurant"]
        categories = [self.INDUSTRY_CATEGORIES.get(ind, ind) for ind in target_industries]

        self.logger.info(
            "Starting BBB scan",
            locations=len(locations),
            categories=categories,
        )

        for location in locations:
            for category in categories:
                try:
                    self.logger.debug("Scanning BBB", location=location, category=category)

                    businesses = await self.search_businesses(location, category)

                    for biz in businesses:
                        try:
                            if not biz.get("profile_url"):
                                continue

                            # Get detailed profile
                            profile = await self.get_business_profile(biz["profile_url"])
                            if not profile:
                                continue

                            # Check if this is a signal
                            complaints = profile.get("complaints_last_year", 0) or profile.get("complaints_total", 0)

                            if complaints < min_complaints:
                                continue

                            # Calculate signal strength
                            signal_strength = min(10, complaints)
                            rating = profile.get("rating")
                            rating_score = self.RATING_SCORES.get(rating, 2.0) if rating else 2.0

                            # Low rating + high complaints = strong signal
                            if rating_score < 2.0 and complaints >= 5:
                                signal_strength = min(10, signal_strength + 2)

                            # Determine priority
                            priority = SignalPriority.LOW
                            if signal_strength >= 7:
                                priority = SignalPriority.HIGH
                            elif signal_strength >= 5:
                                priority = SignalPriority.MEDIUM

                            # Parse location from address
                            address = profile.get("address") or biz.get("address", "")
                            city, state = None, None
                            if address:
                                parts = [p.strip() for p in address.split(",")]
                                if len(parts) >= 2:
                                    city = parts[-2] if len(parts) > 2 else parts[0]
                                    state = self.parse_state(parts[-1])

                            # Build description
                            description = f"BBB Rating: {rating or 'Not Rated'}. "
                            description += f"{complaints} complaints in last 12 months. "
                            if not profile.get("is_accredited"):
                                description += "Not BBB Accredited. "

                            # Raw content for LLM
                            raw_content = f"""
Business: {biz['name']}
BBB Rating: {rating or 'Not Rated'}
Accredited: {'Yes' if profile.get('is_accredited') else 'No'}
Years in Business: {profile.get('years_in_business', 'Unknown')}

Complaint Summary:
- Total Complaints: {profile.get('complaints_total', 0)}
- Last 12 Months: {profile.get('complaints_last_year', 0)}
- Closed/Resolved: {profile.get('complaints_closed', 0)}

Address: {address}
Phone: {profile.get('phone', 'Not listed')}
"""

                            signal = RawSignal(
                                business_name=biz["name"],
                                business_city=city,
                                business_state=state,
                                business_address=address,
                                business_phone=profile.get("phone"),
                                title=f"BBB Complaints: {biz['name']} ({complaints} complaints)",
                                description=description.strip(),
                                raw_content=raw_content.strip(),
                                source_type=self.source_type,
                                source_url=biz["profile_url"],
                                source_date=datetime.utcnow(),
                                suggested_signal_type=SignalType.BBB_COMPLAINT,
                                suggested_category=SignalCategory.CASH_FLOW_STRESS,
                                suggested_priority=priority,
                                external_id=biz["profile_url"],
                                bbb_id=biz["profile_url"].split("/")[-1] if biz["profile_url"] else None,
                                industry=category,
                                year_established=(
                                    datetime.now().year - profile.get("years_in_business", 0)
                                    if profile.get("years_in_business")
                                    else None
                                ),
                                metadata={
                                    "bbb_rating": rating,
                                    "rating_score": rating_score,
                                    "is_accredited": profile.get("is_accredited"),
                                    "complaints_total": profile.get("complaints_total"),
                                    "complaints_last_year": profile.get("complaints_last_year"),
                                    "signal_strength": signal_strength,
                                },
                            )

                            if await self.validate_signal(signal):
                                yield signal

                        except Exception as e:
                            self.logger.warning(
                                "Error processing BBB business",
                                business=biz.get("name"),
                                error=str(e),
                            )
                            continue

                    # Rate limit between searches
                    await asyncio.sleep(2)

                except Exception as e:
                    self.logger.error(
                        "Error scanning BBB category",
                        location=location,
                        category=category,
                        error=str(e),
                    )
                    continue
