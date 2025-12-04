"""
Permits & Filings Source Connectors
====================================

Monitor state-level filings for growth signals:
- Equipment permits (indicates expansion/purchase plans)
- Building permits (new locations, renovations)
- Business registrations (new entities)
- Secretary of State filings (changes, amendments)

These are leading indicators of funding needs.
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional
from urllib.parse import quote_plus

import structlog

from industry_deep_scan.models import SignalCategory, SignalPriority, SignalType, SourceType
from industry_deep_scan.sources.base import BaseSource, RawSignal

logger = structlog.get_logger()


class EquipmentPermitSource(BaseSource):
    """
    Equipment and building permit monitoring.

    Equipment permits indicate:
    - Planned capital expenditure
    - Business expansion
    - Equipment replacement needs

    Building permits indicate:
    - New location opening
    - Renovation/expansion
    - Growth investment

    Sources vary by city/county - this targets major metros.
    """

    source_type = SourceType.EQUIPMENT_PERMITS

    # Major city permit portals
    PERMIT_PORTALS = {
        "Los Angeles, CA": {
            "url": "https://www.ladbsservices2.lacity.org/OnlineServices/",
            "type": "building",
        },
        "New York, NY": {
            "url": "https://a810-bisweb.nyc.gov/bisweb/bispi00.jsp",
            "type": "building",
        },
        "Chicago, IL": {
            "url": "https://webapps1.chicago.gov/buildingrecords/",
            "type": "building",
        },
        "Houston, TX": {
            "url": "https://www.houstonpermittingcenter.org/",
            "type": "building",
        },
        "Phoenix, AZ": {
            "url": "https://www.phoenix.gov/pdd/permits",
            "type": "building",
        },
        "Philadelphia, PA": {
            "url": "https://www.phila.gov/li/",
            "type": "building",
        },
        "San Antonio, TX": {
            "url": "https://webapp9.sanantonio.gov/ePlan/",
            "type": "building",
        },
        "San Diego, CA": {
            "url": "https://www.sandiego.gov/development-services/",
            "type": "building",
        },
        "Dallas, TX": {
            "url": "https://developmentservices.dallascityhall.com/",
            "type": "building",
        },
        "Austin, TX": {
            "url": "https://www.austintexas.gov/department/development-services",
            "type": "building",
        },
    }

    # Permit types that indicate funding opportunities
    VALUABLE_PERMIT_TYPES = {
        "commercial": SignalPriority.HIGH,
        "restaurant": SignalPriority.HIGH,
        "industrial": SignalPriority.HIGH,
        "tenant improvement": SignalPriority.MEDIUM,
        "renovation": SignalPriority.MEDIUM,
        "new construction": SignalPriority.HIGH,
        "addition": SignalPriority.MEDIUM,
        "equipment": SignalPriority.HIGH,
        "mechanical": SignalPriority.MEDIUM,
        "electrical": SignalPriority.LOW,
        "plumbing": SignalPriority.LOW,
    }

    def _classify_permit(self, permit_text: str) -> tuple[Optional[SignalType], SignalPriority]:
        """Classify permit type and priority."""
        text_lower = permit_text.lower()

        for permit_type, priority in self.VALUABLE_PERMIT_TYPES.items():
            if permit_type in text_lower:
                # Determine signal type
                if "equipment" in text_lower or "mechanical" in text_lower:
                    return SignalType.EQUIPMENT_PURCHASE, priority
                elif "new construction" in text_lower or "addition" in text_lower:
                    return SignalType.EXPANSION, priority
                elif "renovation" in text_lower or "improvement" in text_lower:
                    return SignalType.EXPANSION, SignalPriority.MEDIUM
                else:
                    return SignalType.PERMIT_FILED, priority

        return None, SignalPriority.LOW

    def _extract_permit_value(self, text: str) -> Optional[float]:
        """Extract permit valuation from text."""
        patterns = [
            r"valuation[:\s]*\$?([\d,]+)",
            r"value[:\s]*\$?([\d,]+)",
            r"cost[:\s]*\$?([\d,]+)",
            r"\$\s*([\d,]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return float(match.group(1).replace(",", ""))

        return None

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        min_value: float = 50000,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan permit portals for recent filings.

        Args:
            states: Not used (city-level search)
            cities: Target cities (use format "City, ST")
            industries: Filter by industry keywords in permit description
            min_value: Minimum permit value to consider
        """
        target_cities = cities or list(self.PERMIT_PORTALS.keys())[:5]

        self.logger.info(
            "Starting permit scan",
            cities=len(target_cities),
            min_value=min_value,
        )

        for city in target_cities:
            portal = self.PERMIT_PORTALS.get(city)
            if not portal:
                continue

            try:
                async for signal in self._scan_city_permits(city, portal, industries, min_value):
                    yield signal

                await asyncio.sleep(2)

            except Exception as e:
                self.logger.error("Error scanning permits", city=city, error=str(e))

    async def _scan_city_permits(
        self,
        city: str,
        portal: dict,
        industries: Optional[list[str]],
        min_value: float,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan a specific city's permit portal.

        Note: This is a template - each city has a unique permit system
        that would need specific scraping logic.
        """
        try:
            html = await self.fetch(portal["url"])
            soup = self.parse_html(html)

            # Look for recent permit listings
            # Structure varies significantly by city
            permits = soup.find_all(["tr", "div"], class_=re.compile(r"permit|record|listing"))

            for permit in permits[:30]:
                try:
                    permit_text = permit.get_text()

                    # Check if commercial/business permit
                    if not any(kw in permit_text.lower() for kw in ["commercial", "business", "restaurant", "industrial"]):
                        continue

                    # Classify permit
                    signal_type, priority = self._classify_permit(permit_text)
                    if not signal_type:
                        continue

                    # Extract value
                    value = self._extract_permit_value(permit_text)
                    if value and value < min_value:
                        continue

                    # Filter by industry if specified
                    if industries:
                        if not any(ind.lower() in permit_text.lower() for ind in industries):
                            continue

                    # Extract business name
                    name_patterns = [
                        r"(?:applicant|owner|business)[:\s]*([A-Z][A-Za-z\s&']+(?:LLC|Inc|Corp)?)",
                        r"([A-Z][A-Za-z\s&']+(?:LLC|Inc|Corp))",
                    ]

                    business_name = None
                    for pattern in name_patterns:
                        match = re.search(pattern, permit_text)
                        if match:
                            business_name = match.group(1).strip()[:50]
                            break

                    if not business_name:
                        continue

                    # Extract permit number
                    permit_num_match = re.search(r"(?:permit|#|no\.?)[:\s]*([A-Z0-9-]+)", permit_text, re.I)
                    permit_number = permit_num_match.group(1) if permit_num_match else ""

                    # Extract address
                    address_match = re.search(r"(\d+\s+[A-Za-z\s]+(?:St|Ave|Blvd|Rd|Dr|Way|Ln)\.?)", permit_text)
                    address = address_match.group(1) if address_match else ""

                    # Parse city/state
                    city_name = city.split(",")[0].strip()
                    state = city.split(",")[1].strip() if "," in city else ""

                    description = f"{signal_type.value.replace('_', ' ').title()} permit"
                    if value:
                        description += f" - ${value:,.0f}"
                    if permit_number:
                        description += f" (#{permit_number})"

                    raw_content = f"""
Permit Filing: {signal_type.value}
Business: {business_name}
Location: {city}
Address: {address or 'Not specified'}
Permit #: {permit_number or 'Not available'}
Valuation: ${value:,.0f if value else 'Not specified'}

Description:
{permit_text[:500]}
"""

                    signal = RawSignal(
                        business_name=business_name,
                        business_city=city_name,
                        business_state=state,
                        business_address=address,
                        title=f"Permit Filed: {business_name}",
                        description=description,
                        raw_content=raw_content.strip(),
                        source_type=self.source_type,
                        source_url=portal["url"],
                        source_date=datetime.utcnow(),
                        suggested_signal_type=signal_type,
                        suggested_category=SignalCategory.EXPANSION_OPPORTUNITY,
                        suggested_priority=priority,
                        external_id=f"permit-{permit_number}" if permit_number else None,
                        metadata={
                            "permit_number": permit_number,
                            "permit_value": value,
                            "city": city,
                        },
                    )

                    if await self.validate_signal(signal):
                        yield signal

                except Exception as e:
                    self.logger.warning("Error parsing permit record", error=str(e))
                    continue

        except Exception as e:
            self.logger.error("Error fetching permit portal", city=city, error=str(e))


class SOSFilingsSource(BaseSource):
    """
    Secretary of State business filings monitor.

    SOS filings indicate:
    - New business formations (startup funding needs)
    - Entity amendments (growth, restructuring)
    - Annual reports (compliance status)
    - Agent changes (potential ownership transition)

    These are public records accessible via state SOS websites.
    """

    source_type = SourceType.SOS_FILINGS

    # State SOS business search URLs
    STATE_SOS_URLS = {
        "CA": "https://bizfileonline.sos.ca.gov/search/business",
        "TX": "https://mycpa.cpa.state.tx.us/coa/",
        "FL": "https://search.sunbiz.org/Inquiry/CorporationSearch/ByName",
        "NY": "https://apps.dos.ny.gov/publicInquiry/",
        "IL": "https://www.ilsos.gov/corporatellc/",
        "PA": "https://www.corporations.pa.gov/search/corpsearch",
        "OH": "https://businesssearch.ohiosos.gov/",
        "GA": "https://ecorp.sos.ga.gov/BusinessSearch",
        "NC": "https://www.sosnc.gov/online_services/search/business_registration_results",
        "MI": "https://cofs.lara.state.mi.us/SearchApi/Search/Search",
        "NJ": "https://www.njportal.com/DOR/BusinessNameSearch/",
        "VA": "https://cis.scc.virginia.gov/",
        "WA": "https://ccfs.sos.wa.gov/",
        "AZ": "https://ecorp.azcc.gov/EntitySearch/Index",
        "MA": "https://corp.sec.state.ma.us/CorpWeb/CorpSearch/CorpSearch.aspx",
        "CO": "https://www.sos.state.co.us/biz/BusinessEntityCriteriaExt.do",
    }

    # Filing types that indicate funding opportunities
    VALUABLE_FILING_TYPES = {
        "new filing": (SignalType.NEWS_MENTION, SignalCategory.EXPANSION_OPPORTUNITY),
        "formation": (SignalType.NEWS_MENTION, SignalCategory.EXPANSION_OPPORTUNITY),
        "articles of organization": (SignalType.NEWS_MENTION, SignalCategory.EXPANSION_OPPORTUNITY),
        "articles of incorporation": (SignalType.NEWS_MENTION, SignalCategory.EXPANSION_OPPORTUNITY),
        "amendment": (SignalType.EXPANSION, SignalCategory.RAPID_GROWTH),
        "name change": (SignalType.OWNER_CHANGE, SignalCategory.ACQUISITION_TARGET),
        "merger": (SignalType.OWNER_CHANGE, SignalCategory.ACQUISITION_TARGET),
        "conversion": (SignalType.OWNER_CHANGE, SignalCategory.EXPANSION_OPPORTUNITY),
        "reinstatement": (SignalType.CASH_SQUEEZE, SignalCategory.CASH_FLOW_STRESS),
    }

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        filing_types: Optional[list[str]] = None,
        days_back: int = 7,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan SOS filings for recent business registrations.

        Args:
            states: Target state codes
            filing_types: Filter by filing types (e.g., "formation", "amendment")
            days_back: Look back this many days
        """
        target_states = states or list(self.STATE_SOS_URLS.keys())[:5]

        self.logger.info(
            "Starting SOS filings scan",
            states=target_states,
            days_back=days_back,
        )

        for state in target_states:
            sos_url = self.STATE_SOS_URLS.get(state)
            if not sos_url:
                continue

            try:
                async for signal in self._scan_state_filings(state, sos_url, industries, filing_types, days_back):
                    yield signal

                await asyncio.sleep(2)

            except Exception as e:
                self.logger.error("Error scanning SOS filings", state=state, error=str(e))

    async def _scan_state_filings(
        self,
        state: str,
        sos_url: str,
        industries: Optional[list[str]],
        filing_types: Optional[list[str]],
        days_back: int,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan a specific state's SOS portal for recent filings.

        Note: This is a template - each state SOS has unique interfaces.
        Production use would require state-specific scrapers.
        """
        try:
            # Attempt to fetch recent filings page
            html = await self.fetch(sos_url)
            soup = self.parse_html(html)

            # Look for filing records
            # Structure varies significantly by state
            filings = soup.find_all(["tr", "div"], class_=re.compile(r"result|record|entity|filing"))

            cutoff_date = datetime.utcnow() - timedelta(days=days_back)

            for filing in filings[:50]:
                try:
                    filing_text = filing.get_text()

                    # Check filing type
                    signal_type = None
                    category = None

                    for ftype, (sig_type, cat) in self.VALUABLE_FILING_TYPES.items():
                        if ftype in filing_text.lower():
                            signal_type = sig_type
                            category = cat
                            break

                    # Filter by specified filing types
                    if filing_types:
                        if not any(ft.lower() in filing_text.lower() for ft in filing_types):
                            continue

                    if not signal_type:
                        continue

                    # Extract business name
                    name_elem = filing.find(["a", "span", "td"], class_=re.compile(r"name|entity|business"))
                    if name_elem:
                        business_name = name_elem.get_text(strip=True)
                    else:
                        # Try to extract from text
                        name_match = re.search(r"^([A-Z][A-Za-z\s&'.,]+(?:LLC|Inc|Corp|LP|LLP)?)", filing_text)
                        business_name = name_match.group(1).strip() if name_match else None

                    if not business_name or len(business_name) < 3:
                        continue

                    # Extract filing date
                    date_match = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", filing_text)
                    filing_date = None
                    if date_match:
                        for fmt in ["%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"]:
                            try:
                                filing_date = datetime.strptime(date_match.group(1), fmt)
                                break
                            except ValueError:
                                continue

                    # Skip old filings
                    if filing_date and filing_date < cutoff_date:
                        continue

                    # Filter by industry keywords if specified
                    if industries:
                        if not any(ind.lower() in business_name.lower() or ind.lower() in filing_text.lower() for ind in industries):
                            continue

                    # Extract entity type
                    entity_type = None
                    for etype in ["LLC", "Inc", "Corp", "LP", "LLP", "Corporation", "Company"]:
                        if etype.lower() in business_name.lower():
                            entity_type = etype
                            break

                    # Determine priority
                    priority = SignalPriority.MEDIUM
                    if "reinstatement" in filing_text.lower():
                        priority = SignalPriority.HIGH  # Was dissolved, now back
                    elif "formation" in filing_text.lower() or "new" in filing_text.lower():
                        priority = SignalPriority.LOW  # New businesses need time

                    raw_content = f"""
SOS Filing: {state}
Business: {business_name}
Entity Type: {entity_type or 'Unknown'}
Filing Date: {filing_date.strftime('%Y-%m-%d') if filing_date else 'Recent'}

Filing Details:
{filing_text[:500]}
"""

                    signal = RawSignal(
                        business_name=business_name,
                        business_state=state,
                        title=f"SOS Filing: {business_name}",
                        description=f"New {state} SOS filing detected",
                        raw_content=raw_content.strip(),
                        source_type=self.source_type,
                        source_url=sos_url,
                        source_date=filing_date or datetime.utcnow(),
                        suggested_signal_type=signal_type,
                        suggested_category=category,
                        suggested_priority=priority,
                        external_id=f"sos-{state}-{business_name.lower().replace(' ', '-')[:30]}",
                        sos_entity_id=filing.get("data-id") or filing.get("id"),
                        metadata={
                            "entity_type": entity_type,
                            "filing_date": filing_date.isoformat() if filing_date else None,
                            "state": state,
                        },
                    )

                    if await self.validate_signal(signal):
                        yield signal

                except Exception as e:
                    self.logger.warning("Error parsing SOS filing", error=str(e))
                    continue

        except Exception as e:
            self.logger.error("Error fetching SOS portal", state=state, error=str(e))
