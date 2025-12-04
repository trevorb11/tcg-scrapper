"""
Court Records & UCC Filings Source Connectors
==============================================

Monitor public records for financial distress signals:
- Tax liens (IRS/State)
- Mechanic's liens
- Judgment liens
- UCC filings (existing financing)

These are strong indicators of cash flow issues.
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


class CourtRecordsSource(BaseSource):
    """
    Public court records scraper for liens and judgments.

    Different states have different systems:
    - Some have unified online portals
    - Some require county-by-county searches
    - Some require paid access

    This implementation targets states with accessible online systems.
    """

    source_type = SourceType.COURT_RECORDS

    # States with accessible online court record systems
    STATE_COURT_SYSTEMS = {
        "CA": {
            "url": "https://www.courts.ca.gov/selfhelp-efiling.htm",
            "type": "redirect_to_county",
            "counties": {
                "Los Angeles": "https://www.lacourt.org/casesearch",
                "San Diego": "https://www.sdcourt.ca.gov/",
                "San Francisco": "https://www.sfsuperiorcourt.org/",
            },
        },
        "TX": {
            "url": "https://search.txcourts.gov/CaseSearch.aspx",
            "type": "statewide",
        },
        "FL": {
            "url": "https://www.flcourts.gov/",
            "type": "county_redirect",
        },
        "NY": {
            "url": "https://iapps.courts.state.ny.us/nyscef/CaseSearch",
            "type": "statewide",
        },
    }

    # Lien types and their signal mappings
    LIEN_TYPES = {
        "tax lien": (SignalType.TAX_LIEN, SignalPriority.HIGH),
        "federal tax lien": (SignalType.TAX_LIEN, SignalPriority.CRITICAL),
        "state tax lien": (SignalType.TAX_LIEN, SignalPriority.HIGH),
        "mechanic's lien": (SignalType.VENDOR_DISPUTE, SignalPriority.MEDIUM),
        "mechanics lien": (SignalType.VENDOR_DISPUTE, SignalPriority.MEDIUM),
        "judgment": (SignalType.JUDGMENT, SignalPriority.HIGH),
        "money judgment": (SignalType.JUDGMENT, SignalPriority.HIGH),
        "default judgment": (SignalType.JUDGMENT, SignalPriority.HIGH),
    }

    def _parse_lien_amount(self, text: str) -> Optional[float]:
        """Extract lien amount from text."""
        patterns = [
            r"\$\s*([\d,]+(?:\.\d{2})?)",
            r"amount[:\s]*([\d,]+(?:\.\d{2})?)",
            r"([\d,]+(?:\.\d{2})?)\s*(?:dollars?|USD)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1).replace(",", ""))

        return None

    def _classify_lien(self, text: str) -> tuple[Optional[SignalType], SignalPriority]:
        """Classify lien type from text."""
        text_lower = text.lower()

        for keyword, (signal_type, priority) in self.LIEN_TYPES.items():
            if keyword in text_lower:
                return signal_type, priority

        # Default for unclassified liens
        return SignalType.JUDGMENT, SignalPriority.MEDIUM

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        search_names: Optional[list[str]] = None,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan court records for liens and judgments.

        Note: This is a simplified implementation. Production use would require:
        1. State-specific scrapers
        2. Often paid API access (LexisNexis, CourtListener, etc.)
        3. Regular expression patterns for each court system

        Args:
            states: Target state codes
            cities: Target cities/counties
            industries: Not used (searches by business name)
            search_names: Specific business names to search (optional)
        """
        target_states = states or ["TX", "NY"]  # States with accessible systems

        self.logger.info(
            "Court records scan started",
            states=target_states,
            note="Production implementation requires state-specific scrapers or API access",
        )

        for state in target_states:
            court_system = self.STATE_COURT_SYSTEMS.get(state)

            if not court_system:
                self.logger.debug("No court system configured for state", state=state)
                continue

            if court_system["type"] == "statewide":
                # Example: Texas state court search
                if search_names:
                    for name in search_names:
                        async for signal in self._search_texas_courts(name, state):
                            yield signal
                else:
                    self.logger.info(
                        "Court record search requires business names. "
                        "Provide search_names parameter or integrate with enrichment pipeline."
                    )

    async def _search_texas_courts(self, business_name: str, state: str = "TX") -> AsyncIterator[RawSignal]:
        """
        Search Texas court records.

        This is a template - actual implementation depends on the court's
        search interface and terms of service.
        """
        # Texas Courts Case Search
        search_url = f"https://search.txcourts.gov/CaseSearch.aspx?q={quote_plus(business_name)}"

        try:
            html = await self.fetch(search_url)
            soup = self.parse_html(html)

            # Find case listings (structure varies by court system)
            cases = soup.find_all("tr", class_=re.compile(r"case|result"))

            for case in cases[:20]:
                try:
                    # Extract case details
                    case_text = case.get_text()

                    # Check if it's a lien/judgment case
                    signal_type, priority = self._classify_lien(case_text)
                    if not signal_type:
                        continue

                    # Extract case number
                    case_num_match = re.search(r"(?:case\s*#?|no\.?)\s*:?\s*([A-Z0-9-]+)", case_text, re.I)
                    case_number = case_num_match.group(1) if case_num_match else ""

                    # Extract amount
                    amount = self._parse_lien_amount(case_text)

                    # Extract date
                    date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", case_text)
                    filing_date = None
                    if date_match:
                        try:
                            filing_date = datetime.strptime(date_match.group(1), "%m/%d/%Y")
                        except ValueError:
                            try:
                                filing_date = datetime.strptime(date_match.group(1), "%m/%d/%y")
                            except ValueError:
                                pass

                    description = f"{signal_type.value.replace('_', ' ').title()}"
                    if amount:
                        description += f" - ${amount:,.2f}"
                    if case_number:
                        description += f" (Case #{case_number})"

                    raw_content = f"""
Court Record: {signal_type.value}
Business: {business_name}
State: {state}
Case Number: {case_number or 'Unknown'}
Amount: ${amount:,.2f if amount else 'Unknown'}
Filing Date: {filing_date.strftime('%Y-%m-%d') if filing_date else 'Unknown'}

Raw Record:
{case_text[:500]}
"""

                    signal = RawSignal(
                        business_name=business_name,
                        business_state=state,
                        title=f"{signal_type.value.title()}: {business_name}",
                        description=description,
                        raw_content=raw_content.strip(),
                        source_type=self.source_type,
                        source_url=search_url,
                        source_date=filing_date or datetime.utcnow(),
                        suggested_signal_type=signal_type,
                        suggested_category=SignalCategory.CASH_FLOW_STRESS,
                        suggested_priority=priority,
                        external_id=f"{state}-{case_number}" if case_number else None,
                        metadata={
                            "case_number": case_number,
                            "lien_amount": amount,
                            "filing_date": filing_date.isoformat() if filing_date else None,
                        },
                    )

                    if await self.validate_signal(signal):
                        yield signal

                except Exception as e:
                    self.logger.warning("Error parsing court record", error=str(e))
                    continue

        except Exception as e:
            self.logger.error("Error searching Texas courts", name=business_name, error=str(e))


class UCCFilingsSource(BaseSource):
    """
    UCC (Uniform Commercial Code) filings source.

    UCC filings indicate:
    - Existing secured financing (MCA, equipment loans, lines of credit)
    - Asset-based lending relationships
    - Potential for stacking (multiple funders)

    Many Secretary of State websites provide UCC search functionality.
    """

    source_type = SourceType.UCC_FILINGS

    # State SOS UCC search URLs
    STATE_UCC_SYSTEMS = {
        "CA": "https://businesssearch.sos.ca.gov/",
        "TX": "https://direct.sos.state.tx.us/",
        "FL": "https://search.sunbiz.org/",
        "NY": "https://www.dos.ny.gov/corps/",
        "IL": "https://www.ilsos.gov/uccsearch/",
        "PA": "https://www.corporations.pa.gov/search/corpsearch",
        "OH": "https://www.ohiosos.gov/businesses/",
        "GA": "https://ecorp.sos.ga.gov/",
        "NC": "https://www.sosnc.gov/online_services/search/ucc",
        "MI": "https://cofs.lara.state.mi.us/SearchApi/Search/Search",
    }

    # MCA/Financing keywords in secured party names
    FUNDING_INDICATORS = [
        "capital", "funding", "finance", "financial", "merchant",
        "advance", "lending", "credit", "asset", "factor",
        "cash", "solutions", "growth", "business", "commercial",
    ]

    def _is_mca_funder(self, secured_party: str) -> bool:
        """Check if secured party appears to be an MCA funder."""
        party_lower = secured_party.lower()
        return any(indicator in party_lower for indicator in self.FUNDING_INDICATORS)

    def _count_active_filings(self, filings: list) -> int:
        """Count active/non-terminated UCC filings."""
        active = 0
        for filing in filings:
            status = filing.get("status", "").lower()
            if "terminated" not in status and "released" not in status:
                active += 1
        return active

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        search_names: Optional[list[str]] = None,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan UCC filings for existing financing signals.

        Args:
            states: Target state codes
            search_names: Business names to search for
        """
        target_states = states or list(self.STATE_UCC_SYSTEMS.keys())[:5]

        if not search_names:
            self.logger.info(
                "UCC search requires business names. "
                "Integrate with lead pipeline for automated name searches."
            )
            return

        for state in target_states:
            ucc_url = self.STATE_UCC_SYSTEMS.get(state)
            if not ucc_url:
                continue

            for name in search_names:
                try:
                    async for signal in self._search_ucc_filings(name, state, ucc_url):
                        yield signal

                    await asyncio.sleep(1)

                except Exception as e:
                    self.logger.error(
                        "Error searching UCC filings",
                        state=state,
                        name=name,
                        error=str(e),
                    )

    async def _search_ucc_filings(
        self,
        business_name: str,
        state: str,
        base_url: str,
    ) -> AsyncIterator[RawSignal]:
        """
        Search for UCC filings for a specific business.

        Note: This is a template implementation. Each state has different
        search interfaces and would need specific handling.
        """
        search_url = f"{base_url}?debtor={quote_plus(business_name)}"

        try:
            html = await self.fetch(search_url)
            soup = self.parse_html(html)

            # Find UCC filing records (structure varies by state)
            filings = soup.find_all("tr", class_=re.compile(r"filing|record|result"))

            if not filings:
                return

            filing_count = 0
            mca_funder_count = 0
            secured_parties = []

            for filing in filings:
                try:
                    filing_text = filing.get_text()

                    # Check if active
                    if "terminated" in filing_text.lower():
                        continue

                    filing_count += 1

                    # Extract secured party
                    party_match = re.search(
                        r"secured\s*party[:\s]*([^,\n]+)",
                        filing_text,
                        re.I,
                    )
                    if party_match:
                        party = party_match.group(1).strip()
                        secured_parties.append(party)

                        if self._is_mca_funder(party):
                            mca_funder_count += 1

                except Exception:
                    continue

            # Determine signal based on findings
            if filing_count == 0:
                return  # No active filings

            # Multiple funders = stacking indicator
            priority = SignalPriority.MEDIUM
            signal_type = SignalType.UCC_FILING

            if mca_funder_count >= 2:
                priority = SignalPriority.HIGH  # Stacking detected
            elif filing_count >= 3:
                priority = SignalPriority.HIGH  # Multiple creditors

            description = f"{filing_count} active UCC filings"
            if mca_funder_count > 0:
                description += f" ({mca_funder_count} appear to be MCA/financing)"

            raw_content = f"""
UCC Filing Summary: {business_name}
State: {state}

Active Filings: {filing_count}
Likely MCA/Funders: {mca_funder_count}

Secured Parties:
{chr(10).join(f'- {p}' for p in secured_parties[:10])}

Analysis:
{'STACKING ALERT: Multiple MCA funders detected' if mca_funder_count >= 2 else ''}
{'Multiple creditors - may have existing payment obligations' if filing_count >= 3 else ''}
"""

            signal = RawSignal(
                business_name=business_name,
                business_state=state,
                title=f"UCC Filings: {business_name} ({filing_count} active)",
                description=description,
                raw_content=raw_content.strip(),
                source_type=self.source_type,
                source_url=search_url,
                source_date=datetime.utcnow(),
                suggested_signal_type=signal_type,
                suggested_category=SignalCategory.CASH_FLOW_STRESS if mca_funder_count > 0 else SignalCategory.EXPANSION_OPPORTUNITY,
                suggested_priority=priority,
                external_id=f"ucc-{state}-{business_name.lower().replace(' ', '-')}",
                metadata={
                    "active_filings": filing_count,
                    "mca_funder_count": mca_funder_count,
                    "secured_parties": secured_parties[:10],
                    "stacking_detected": mca_funder_count >= 2,
                },
            )

            if await self.validate_signal(signal):
                yield signal

        except Exception as e:
            self.logger.error(
                "Error in UCC search",
                business=business_name,
                state=state,
                error=str(e),
            )
