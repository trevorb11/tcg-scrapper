"""
Business-for-Sale Listings Source Connectors
=============================================

Monitor business listing sites for acquisition signals:
- Businesses actively for sale (owner exit opportunity)
- Distressed sales (cash flow issues)
- Growth acquisitions (competitor intel)

Key sites:
- BizBuySell (largest)
- BusinessBroker.net
- LoopNet (commercial real estate with businesses)
- BusinessesForSale.com
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


class BizBuySellSource(BaseSource):
    """
    BizBuySell.com scraper - largest business-for-sale marketplace.

    Businesses for sale often need bridge financing:
    - Current owner may need cash before sale closes
    - Buyer may need working capital
    - Transition period funding
    """

    source_type = SourceType.BUSINESS_LISTINGS
    BASE_URL = "https://www.bizbuysell.com"

    # Industry categories on BizBuySell
    INDUSTRY_PATHS = {
        "restaurant": "restaurants-and-food",
        "construction": "construction",
        "auto_repair": "automotive",
        "trucking": "transportation",
        "retail": "retail",
        "manufacturing": "manufacturing",
        "medical": "health-care-and-fitness",
        "service": "service-businesses",
        "landscaping": "service-businesses",
        "hvac": "construction",
        "plumbing": "construction",
    }

    # State code to URL format mapping
    STATE_SLUGS = {
        "CA": "california",
        "TX": "texas",
        "FL": "florida",
        "NY": "new-york",
        "IL": "illinois",
        "PA": "pennsylvania",
        "OH": "ohio",
        "GA": "georgia",
        "NC": "north-carolina",
        "MI": "michigan",
        "NJ": "new-jersey",
        "VA": "virginia",
        "WA": "washington",
        "AZ": "arizona",
        "MA": "massachusetts",
        "TN": "tennessee",
        "IN": "indiana",
        "MD": "maryland",
        "MO": "missouri",
        "WI": "wisconsin",
        "CO": "colorado",
        "MN": "minnesota",
    }

    def _parse_price(self, text: str) -> Optional[float]:
        """Extract price from listing text."""
        if not text:
            return None

        # Remove $ and commas, handle K/M suffixes
        text = text.upper().replace("$", "").replace(",", "").strip()

        match = re.search(r"([\d.]+)\s*([KM])?", text)
        if match:
            value = float(match.group(1))
            suffix = match.group(2)
            if suffix == "K":
                value *= 1000
            elif suffix == "M":
                value *= 1000000
            return value

        return None

    def _parse_cash_flow(self, text: str) -> Optional[float]:
        """Extract cash flow from listing text."""
        if not text:
            return None

        # Look for cash flow patterns
        patterns = [
            r"cash\s*flow[:\s]*\$?([\d,]+)",
            r"cf[:\s]*\$?([\d,]+)",
            r"sde[:\s]*\$?([\d,]+)",  # Seller's Discretionary Earnings
            r"ebitda[:\s]*\$?([\d,]+)",
        ]

        text_lower = text.lower()
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                return float(match.group(1).replace(",", ""))

        return None

    def _parse_revenue(self, text: str) -> Optional[float]:
        """Extract revenue from listing text."""
        if not text:
            return None

        patterns = [
            r"revenue[:\s]*\$?([\d,]+)",
            r"gross[:\s]*\$?([\d,]+)",
            r"sales[:\s]*\$?([\d,]+)",
        ]

        text_lower = text.lower()
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                return float(match.group(1).replace(",", ""))

        return None

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        min_revenue: float = 100000,
        max_price: float = 5000000,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan BizBuySell for business listings.

        Args:
            states: Target state codes
            cities: Not used (state-level search)
            industries: Target industry categories
            min_revenue: Minimum annual revenue (default $100K)
            max_price: Maximum listing price (default $5M)
        """
        target_states = states or self.settings.scraping.target_states[:10]
        target_industries = industries or ["restaurant", "construction", "auto_repair", "trucking"]

        for state in target_states:
            state_slug = self.STATE_SLUGS.get(state, state.lower())

            for industry in target_industries:
                industry_path = self.INDUSTRY_PATHS.get(industry, industry)

                try:
                    # Build search URL
                    url = f"{self.BASE_URL}/{state_slug}-businesses-for-sale/{industry_path}"

                    self.logger.debug("Scanning BizBuySell", state=state, industry=industry)

                    html = await self.fetch(url)
                    soup = self.parse_html(html)

                    # Find listing cards
                    listings = soup.find_all("div", class_=re.compile(r"listing|result|card"))

                    for listing in listings[:25]:  # Limit per category
                        try:
                            # Extract business name/title
                            title_elem = listing.find(["h2", "h3", "a"], class_=re.compile(r"title|name|link"))
                            if not title_elem:
                                continue

                            title = title_elem.get_text(strip=True)

                            # Extract listing URL
                            link_elem = listing.find("a", href=re.compile(r"/listing|/business"))
                            listing_url = ""
                            if link_elem:
                                href = link_elem.get("href", "")
                                listing_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

                            # Extract price
                            price_elem = listing.find(class_=re.compile(r"price|asking"))
                            price = self._parse_price(price_elem.get_text() if price_elem else "")

                            # Filter by price
                            if price and price > max_price:
                                continue

                            # Extract financial metrics
                            metrics_elem = listing.find(class_=re.compile(r"metrics|details|financials"))
                            metrics_text = metrics_elem.get_text() if metrics_elem else ""

                            revenue = self._parse_revenue(metrics_text)
                            cash_flow = self._parse_cash_flow(metrics_text)

                            # Filter by revenue
                            if revenue and revenue < min_revenue:
                                continue

                            # Extract location
                            location_elem = listing.find(class_=re.compile(r"location|city|address"))
                            location_text = location_elem.get_text(strip=True) if location_elem else ""

                            city = None
                            if location_text:
                                parts = [p.strip() for p in location_text.split(",")]
                                city = parts[0] if parts else None

                            # Extract description
                            desc_elem = listing.find(class_=re.compile(r"description|summary|snippet"))
                            description = desc_elem.get_text(strip=True)[:500] if desc_elem else ""

                            # Determine priority based on financials
                            priority = SignalPriority.MEDIUM

                            # High revenue + for sale = high priority
                            if revenue and revenue > 500000:
                                priority = SignalPriority.HIGH

                            # Distressed indicators
                            distress_keywords = ["must sell", "motivated", "retiring", "health", "urgent", "quick sale"]
                            if any(kw in description.lower() for kw in distress_keywords):
                                priority = SignalPriority.HIGH

                            # Build raw content
                            raw_content = f"""
Business Listing: {title}

Asking Price: ${price:,.0f if price else 'Not disclosed'}
Revenue: ${revenue:,.0f if revenue else 'Not disclosed'}
Cash Flow: ${cash_flow:,.0f if cash_flow else 'Not disclosed'}

Location: {location_text or f'{city}, {state}' if city else state}
Industry: {industry}

Description:
{description}

Source: {listing_url}
"""

                            signal = RawSignal(
                                business_name=title,
                                business_city=city,
                                business_state=state,
                                title=f"Business for Sale: {title}",
                                description=f"Listed at ${price:,.0f}" if price else "Price on request",
                                raw_content=raw_content.strip(),
                                source_type=self.source_type,
                                source_url=listing_url,
                                source_date=datetime.utcnow(),
                                suggested_signal_type=SignalType.BUSINESS_FOR_SALE,
                                suggested_category=SignalCategory.ACQUISITION_TARGET,
                                suggested_priority=priority,
                                external_id=listing_url,
                                industry=industry,
                                annual_revenue=revenue,
                                metadata={
                                    "asking_price": price,
                                    "cash_flow": cash_flow,
                                    "listing_source": "bizbuysell",
                                },
                            )

                            if await self.validate_signal(signal):
                                yield signal

                        except Exception as e:
                            self.logger.warning("Error parsing BizBuySell listing", error=str(e))
                            continue

                    # Rate limit
                    await asyncio.sleep(1.5)

                except Exception as e:
                    self.logger.error(
                        "Error scanning BizBuySell category",
                        state=state,
                        industry=industry,
                        error=str(e),
                    )
                    continue


class BusinessBrokerSource(BaseSource):
    """
    BusinessBroker.net scraper - another major listing site.

    Similar to BizBuySell but sometimes has different listings.
    """

    source_type = SourceType.BUSINESS_LISTINGS
    BASE_URL = "https://www.businessbroker.net"

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan BusinessBroker.net for listings.

        Similar structure to BizBuySell scanner.
        """
        target_states = states or self.settings.scraping.target_states[:5]
        target_industries = industries or ["restaurant", "construction", "automotive"]

        for state in target_states:
            for industry in target_industries:
                try:
                    # BusinessBroker.net search URL format
                    url = f"{self.BASE_URL}/businesses-for-sale/{state.lower()}/{industry.lower()}"

                    self.logger.debug("Scanning BusinessBroker", state=state, industry=industry)

                    html = await self.fetch(url)
                    soup = self.parse_html(html)

                    # Find listings
                    listings = soup.find_all("div", class_=re.compile(r"listing|business-item"))

                    for listing in listings[:20]:
                        try:
                            # Extract title
                            title_elem = listing.find(["h2", "h3", "a"])
                            if not title_elem:
                                continue

                            title = title_elem.get_text(strip=True)

                            # Skip generic titles
                            if len(title) < 5 or title.lower() in ["business for sale", "see listing"]:
                                continue

                            # Extract URL
                            link_elem = listing.find("a", href=True)
                            listing_url = ""
                            if link_elem:
                                href = link_elem["href"]
                                listing_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

                            # Extract details
                            details_text = listing.get_text()

                            # Extract price
                            price_match = re.search(r"\$[\d,]+(?:\.\d{2})?", details_text)
                            price = None
                            if price_match:
                                price = float(price_match.group().replace("$", "").replace(",", ""))

                            # Extract location
                            city = None
                            location_match = re.search(r"([A-Za-z\s]+),\s*([A-Z]{2})", details_text)
                            if location_match:
                                city = location_match.group(1).strip()

                            signal = RawSignal(
                                business_name=title,
                                business_city=city,
                                business_state=state,
                                title=f"Business for Sale: {title}",
                                description=f"Listed on BusinessBroker.net" + (f" - ${price:,.0f}" if price else ""),
                                raw_content=details_text[:1000],
                                source_type=self.source_type,
                                source_url=listing_url,
                                source_date=datetime.utcnow(),
                                suggested_signal_type=SignalType.BUSINESS_FOR_SALE,
                                suggested_category=SignalCategory.ACQUISITION_TARGET,
                                suggested_priority=SignalPriority.MEDIUM,
                                external_id=listing_url,
                                industry=industry,
                                metadata={
                                    "asking_price": price,
                                    "listing_source": "businessbroker",
                                },
                            )

                            if await self.validate_signal(signal):
                                yield signal

                        except Exception as e:
                            self.logger.warning("Error parsing BusinessBroker listing", error=str(e))
                            continue

                    await asyncio.sleep(1.5)

                except Exception as e:
                    self.logger.error(
                        "Error scanning BusinessBroker",
                        state=state,
                        industry=industry,
                        error=str(e),
                    )
                    continue
