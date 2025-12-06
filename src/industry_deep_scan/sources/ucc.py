"""
UCC (Uniform Commercial Code) Filings Source
=============================================

Enhanced UCC filings scraper with state-specific scraping strategies.

UCC filings indicate:
- Existing secured financing (MCA, equipment loans, lines of credit)
- Asset-based lending relationships
- Potential for stacking (multiple funders)

State Scrapability Analysis:
- MOST SCRAPABLE: New York (5/5), Arizona (4/5)
- MODERATELY SCRAPABLE: Colorado (3/5), Montana (3/5), Wisconsin (3/5)
- DIFFICULT: California (2/5), Illinois (2/5), Florida (2/5), Georgia (1/5)
- NOT PUBLICLY SCRAPABLE: Delaware (1/5), Wyoming (1/5), Texas (2/5)
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import AsyncIterator, Optional
from urllib.parse import quote_plus, urlencode

import structlog

from industry_deep_scan.models import SignalCategory, SignalPriority, SignalType, SourceType
from industry_deep_scan.sources.base import BaseSource, PlaywrightSource, RawSignal

logger = structlog.get_logger()


class UCCScrapability(str, Enum):
    """State UCC website scrapability rating."""
    EXCELLENT = "excellent"       # 5/5 - Easy to scrape
    GOOD = "good"                 # 4/5 - Possible with proper headers
    MODERATE = "moderate"         # 3/5 - Requires JS rendering
    DIFFICULT = "difficult"       # 2/5 - WAF/bot protection
    NOT_AVAILABLE = "unavailable" # 1/5 - Login/fee required


class ScrapingMethod(str, Enum):
    """Scraping method for state UCC website."""
    SIMPLE_HTML = "simple_html"   # Simple HTTP GET/POST
    PLAYWRIGHT = "playwright"     # Requires JavaScript rendering
    API = "api"                   # Has API endpoint
    NOT_SUPPORTED = "not_supported"


@dataclass
class StateUCCConfig:
    """Configuration for a state's UCC filing system."""
    state_code: str
    state_name: str
    search_url: str
    scrapability: UCCScrapability
    method: ScrapingMethod
    notes: str
    requires_login: bool = False
    has_captcha: bool = False
    has_waf: bool = False
    fee_required: bool = False
    robots_blocked: bool = False


# State UCC system configurations based on research
STATE_UCC_CONFIGS: dict[str, StateUCCConfig] = {
    # === MOST SCRAPABLE ===
    "NY": StateUCCConfig(
        state_code="NY",
        state_name="New York",
        search_url="https://appext20.dos.ny.gov/pls/ucc_public/web_search.inhouse_search",
        scrapability=UCCScrapability.EXCELLENT,
        method=ScrapingMethod.SIMPLE_HTML,
        notes="Clean HTML forms, Oracle PL/SQL interface, no CAPTCHA, publicly accessible",
    ),
    "AZ": StateUCCConfig(
        state_code="AZ",
        state_name="Arizona",
        search_url="https://apps.azsos.gov/apps/ucc/search/",
        scrapability=UCCScrapability.GOOD,
        method=ScrapingMethod.SIMPLE_HTML,
        notes="Free public searches, simple form interface, needs proper headers",
    ),

    # === MODERATELY SCRAPABLE ===
    "CO": StateUCCConfig(
        state_code="CO",
        state_name="Colorado",
        search_url="https://www.sos.state.co.us/ucc/pages/search/standardSearch.xhtml",
        scrapability=UCCScrapability.MODERATE,
        method=ScrapingMethod.PLAYWRIGHT,
        notes="JSF-based, requires JavaScript, session tokens and AJAX",
    ),
    "MT": StateUCCConfig(
        state_code="MT",
        state_name="Montana",
        search_url="https://biz.sosmt.gov/search/ucc",
        scrapability=UCCScrapability.MODERATE,
        method=ScrapingMethod.PLAYWRIGHT,
        notes="Modern SPA (React/Angular/Vue), requires full JS execution",
    ),
    "WI": StateUCCConfig(
        state_code="WI",
        state_name="Wisconsin",
        search_url="https://wims.dfi.wi.gov/",
        scrapability=UCCScrapability.MODERATE,
        method=ScrapingMethod.PLAYWRIGHT,
        notes="Modern web app, requires free account creation",
        requires_login=True,
    ),
    "NC": StateUCCConfig(
        state_code="NC",
        state_name="North Carolina",
        search_url="https://www.sosnc.gov/online_services/search/ucc",
        scrapability=UCCScrapability.MODERATE,
        method=ScrapingMethod.SIMPLE_HTML,
        notes="State SOS portal with public search",
    ),
    "MI": StateUCCConfig(
        state_code="MI",
        state_name="Michigan",
        search_url="https://cofs.lara.state.mi.us/SearchApi/Search/Search",
        scrapability=UCCScrapability.MODERATE,
        method=ScrapingMethod.API,
        notes="Has API endpoint for searches",
    ),
    "OH": StateUCCConfig(
        state_code="OH",
        state_name="Ohio",
        search_url="https://www.ohiosos.gov/businesses/",
        scrapability=UCCScrapability.MODERATE,
        method=ScrapingMethod.SIMPLE_HTML,
        notes="State SOS portal",
    ),
    "PA": StateUCCConfig(
        state_code="PA",
        state_name="Pennsylvania",
        search_url="https://www.corporations.pa.gov/search/corpsearch",
        scrapability=UCCScrapability.MODERATE,
        method=ScrapingMethod.PLAYWRIGHT,
        notes="Modern interface, may require JS",
    ),
    "GA": StateUCCConfig(
        state_code="GA",
        state_name="Georgia",
        search_url="https://ecorp.sos.ga.gov/",
        scrapability=UCCScrapability.DIFFICULT,
        method=ScrapingMethod.PLAYWRIGHT,
        notes="Site stability issues, robots.txt fetch fails with 500 error",
    ),

    # === DIFFICULT TO SCRAPE ===
    "CA": StateUCCConfig(
        state_code="CA",
        state_name="California",
        search_url="https://bizfileonline.sos.ca.gov/search/ucc",
        scrapability=UCCScrapability.DIFFICULT,
        method=ScrapingMethod.PLAYWRIGHT,
        notes="Protected by Incapsula/Imperva WAF, advanced bot detection",
        has_waf=True,
    ),
    "IL": StateUCCConfig(
        state_code="IL",
        state_name="Illinois",
        search_url="https://apps.ilsos.gov/uccsearch/",
        scrapability=UCCScrapability.DIFFICULT,
        method=ScrapingMethod.SIMPLE_HTML,
        notes="Blocked by robots.txt",
        robots_blocked=True,
    ),
    "FL": StateUCCConfig(
        state_code="FL",
        state_name="Florida",
        search_url="https://floridaucc.com/search",
        scrapability=UCCScrapability.DIFFICULT,
        method=ScrapingMethod.PLAYWRIGHT,
        notes="Privatized system (FloridaUCC LLC), requires JavaScript (React/Vue SPA)",
    ),

    # === NOT PUBLICLY SCRAPABLE ===
    "DE": StateUCCConfig(
        state_code="DE",
        state_name="Delaware",
        search_url="",
        scrapability=UCCScrapability.NOT_AVAILABLE,
        method=ScrapingMethod.NOT_SUPPORTED,
        notes="No public search interface - must use authorized searchers, $50/search + $25 expedite",
        fee_required=True,
        requires_login=True,
    ),
    "WY": StateUCCConfig(
        state_code="WY",
        state_name="Wyoming",
        search_url="https://ucc.wyo.gov/Account/Login.aspx",
        scrapability=UCCScrapability.NOT_AVAILABLE,
        method=ScrapingMethod.NOT_SUPPORTED,
        notes="Requires login and $200 prepaid account deposit (PAD)",
        fee_required=True,
        requires_login=True,
    ),
    "TX": StateUCCConfig(
        state_code="TX",
        state_name="Texas",
        search_url="https://direct.sos.state.tx.us/",
        scrapability=UCCScrapability.NOT_AVAILABLE,
        method=ScrapingMethod.NOT_SUPPORTED,
        notes="SOSDirect portal requires account, $1.00 statutory fee per search",
        fee_required=True,
        requires_login=True,
    ),
}


# MCA/Financing company name indicators
MCA_FUNDERS = [
    # Major MCA companies
    "merchant cash", "advance", "funding", "capital",
    "finance", "financial", "lending", "lender",
    "factoring", "factor", "asset", "credit",
    "business", "commercial", "growth", "solutions",
    "cash flow", "working capital", "alternative",
    # Common MCA company names
    "ondeck", "bluevine", "kabbage", "fundbox",
    "paypal working capital", "square capital",
    "can capital", "rapid capital", "bizfi",
    "credibly", "fora financial", "national funding",
    "swift capital", "forward financing", "greenbox",
    "reliant funding", "yellowstone capital",
]


class UCCFilingsSource(PlaywrightSource):
    """
    Enhanced UCC filings source with state-specific scraping strategies.

    Supports multiple scraping methods:
    - Simple HTML scraping for clean interfaces (NY, AZ)
    - Playwright for JavaScript-heavy sites (CO, MT, WI, FL)
    - API calls where available (MI)
    """

    source_type = SourceType.UCC_FILINGS

    def __init__(self):
        super().__init__()
        self.configs = STATE_UCC_CONFIGS

    def get_scrapable_states(self) -> list[str]:
        """Get list of states that can be scraped."""
        return [
            code for code, config in self.configs.items()
            if config.method != ScrapingMethod.NOT_SUPPORTED
            and not config.requires_login
            and not config.fee_required
        ]

    def get_state_info(self, state: str) -> Optional[StateUCCConfig]:
        """Get configuration for a specific state."""
        return self.configs.get(state.upper())

    def _is_mca_funder(self, secured_party: str) -> bool:
        """Check if secured party appears to be an MCA funder."""
        party_lower = secured_party.lower()
        return any(indicator in party_lower for indicator in MCA_FUNDERS)

    def _extract_filing_number(self, text: str) -> Optional[str]:
        """Extract UCC filing number from text."""
        patterns = [
            r"(?:filing\s*(?:no|number|#)?[:\s]*)([A-Z0-9-]+)",
            r"(?:ucc\s*(?:no|number|#)?[:\s]*)([A-Z0-9-]+)",
            r"([0-9]{8,15})",  # Common numeric filing numbers
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_filing_date(self, text: str) -> Optional[datetime]:
        """Extract filing date from text."""
        patterns = [
            r"(\d{1,2}/\d{1,2}/\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{1,2}-\d{1,2}-\d{4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                date_str = match.group(1)
                for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"]:
                    try:
                        return datetime.strptime(date_str, fmt)
                    except ValueError:
                        continue
        return None

    def _extract_collateral_type(self, text: str) -> Optional[str]:
        """Extract collateral type description from text."""
        patterns = [
            r"collateral[:\s]*(.{10,100})",
            r"(?:all\s+)?(?:assets|inventory|equipment|accounts?\s+receivable|fixtures)",
        ]
        match = re.search(patterns[0], text, re.IGNORECASE)
        if match:
            return match.group(1).strip()[:100]

        # Check for common collateral types
        text_lower = text.lower()
        if "all assets" in text_lower:
            return "All Assets"
        if "accounts receivable" in text_lower:
            return "Accounts Receivable"
        if "inventory" in text_lower:
            return "Inventory"
        if "equipment" in text_lower:
            return "Equipment"
        return None

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
            search_names: Business names to search for (required)
        """
        # Default to most scrapable states
        target_states = states or self.get_scrapable_states()[:5]

        if not search_names:
            self.logger.info(
                "UCC search requires business names. "
                "Integrate with lead pipeline for automated name searches."
            )
            return

        for state in target_states:
            config = self.configs.get(state.upper())
            if not config:
                self.logger.debug("No UCC config for state", state=state)
                continue

            if config.method == ScrapingMethod.NOT_SUPPORTED:
                self.logger.debug(
                    "UCC scraping not supported for state",
                    state=state,
                    reason=config.notes,
                )
                continue

            if config.requires_login or config.fee_required:
                self.logger.debug(
                    "UCC scraping requires account/fee",
                    state=state,
                    requires_login=config.requires_login,
                    fee_required=config.fee_required,
                )
                continue

            for name in search_names:
                try:
                    async for signal in self._search_state_ucc(name, config):
                        yield signal

                    # Rate limiting between searches
                    await asyncio.sleep(1)

                except Exception as e:
                    self.logger.error(
                        "Error searching UCC filings",
                        state=state,
                        name=name,
                        error=str(e),
                    )

    async def _search_state_ucc(
        self,
        business_name: str,
        config: StateUCCConfig,
    ) -> AsyncIterator[RawSignal]:
        """Route to appropriate state-specific search method."""
        self.logger.debug(
            "Searching UCC filings",
            state=config.state_code,
            business=business_name,
            method=config.method.value,
        )

        if config.state_code == "NY":
            async for signal in self._search_new_york(business_name):
                yield signal
        elif config.state_code == "AZ":
            async for signal in self._search_arizona(business_name):
                yield signal
        elif config.state_code == "NC":
            async for signal in self._search_north_carolina(business_name):
                yield signal
        elif config.state_code == "MI":
            async for signal in self._search_michigan_api(business_name):
                yield signal
        elif config.method == ScrapingMethod.PLAYWRIGHT:
            async for signal in self._search_with_playwright(business_name, config):
                yield signal
        else:
            async for signal in self._search_generic(business_name, config):
                yield signal

    async def _search_new_york(self, business_name: str) -> AsyncIterator[RawSignal]:
        """
        Search New York UCC filings.

        New York has the cleanest, most scrapable UCC system:
        - Oracle PL/SQL-based interface
        - Simple POST parameters
        - Clean HTML tables in results
        - No CAPTCHA or login required
        """
        search_url = "https://appext20.dos.ny.gov/pls/ucc_public/web_search.inhouse_search"

        # New York uses POST with form data
        form_data = {
            "business_name": business_name,
            "last_name": "",
            "first_name": "",
            "filing_status": "A",  # Active filings only
            "file_type": "",
            "search_type": "business",
        }

        try:
            if self._session is None:
                await self.setup()

            headers = {
                **self.get_headers(),
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://appext20.dos.ny.gov/pls/ucc_public/web_search.main_frame",
            }

            await self.rate_limiter.acquire()

            async with self._session.post(
                search_url,
                data=form_data,
                headers=headers,
            ) as response:
                if response.status != 200:
                    self.logger.warning("NY UCC search failed", status=response.status)
                    return

                html = await response.text()

            soup = self.parse_html(html)

            # Find filing results table
            tables = soup.find_all("table")

            filings = []
            secured_parties = []

            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if not cells:
                        continue

                    row_text = row.get_text(separator=" ", strip=True)

                    # Skip header rows
                    if "filing" in row_text.lower() and "number" in row_text.lower():
                        continue

                    # Look for filing information
                    filing_num = self._extract_filing_number(row_text)
                    filing_date = self._extract_filing_date(row_text)

                    if filing_num:
                        filings.append({
                            "number": filing_num,
                            "date": filing_date,
                            "text": row_text[:500],
                        })

                    # Look for secured party names
                    if "secured" in row_text.lower() or "party" in row_text.lower():
                        # Extract party name from cells
                        for cell in cells:
                            cell_text = cell.get_text(strip=True)
                            if cell_text and len(cell_text) > 3:
                                secured_parties.append(cell_text)

            if not filings:
                return

            # Count MCA funders
            mca_count = sum(1 for party in secured_parties if self._is_mca_funder(party))

            # Generate signal
            async for signal in self._create_ucc_signal(
                business_name=business_name,
                state="NY",
                filings=filings,
                secured_parties=secured_parties,
                mca_count=mca_count,
                search_url=search_url,
            ):
                yield signal

        except Exception as e:
            self.logger.error("Error in NY UCC search", business=business_name, error=str(e))

    async def _search_arizona(self, business_name: str) -> AsyncIterator[RawSignal]:
        """
        Search Arizona UCC filings.

        Arizona requires proper headers to avoid 403 errors.
        """
        search_url = "https://apps.azsos.gov/apps/ucc/search/"

        try:
            # Arizona needs specific headers to avoid 403
            headers = {
                **self.get_headers(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Referer": "https://apps.azsos.gov/apps/ucc/",
                "Origin": "https://apps.azsos.gov",
            }

            # Build search URL with query params
            params = {
                "searchType": "debtorName",
                "name": business_name,
            }
            url = f"{search_url}?{urlencode(params)}"

            html = await self.fetch(url, headers=headers)
            soup = self.parse_html(html)

            # Parse Arizona-specific results
            results = soup.find_all("div", class_=re.compile(r"result|filing"))

            if not results:
                results = soup.find_all("tr", class_=re.compile(r"result|filing|data"))

            filings = []
            secured_parties = []

            for result in results:
                text = result.get_text(separator=" ", strip=True)

                filing_num = self._extract_filing_number(text)
                filing_date = self._extract_filing_date(text)

                if filing_num:
                    filings.append({
                        "number": filing_num,
                        "date": filing_date,
                        "text": text[:500],
                    })

                # Look for secured party
                party_match = re.search(r"secured\s*party[:\s]*([^\n,]+)", text, re.I)
                if party_match:
                    secured_parties.append(party_match.group(1).strip())

            if not filings:
                return

            mca_count = sum(1 for party in secured_parties if self._is_mca_funder(party))

            async for signal in self._create_ucc_signal(
                business_name=business_name,
                state="AZ",
                filings=filings,
                secured_parties=secured_parties,
                mca_count=mca_count,
                search_url=url,
            ):
                yield signal

        except Exception as e:
            self.logger.error("Error in AZ UCC search", business=business_name, error=str(e))

    async def _search_north_carolina(self, business_name: str) -> AsyncIterator[RawSignal]:
        """Search North Carolina UCC filings."""
        search_url = "https://www.sosnc.gov/online_services/search/ucc"

        try:
            params = {"searchValue": business_name, "searchType": "debtor"}
            url = f"{search_url}?{urlencode(params)}"

            html = await self.fetch(url)
            soup = self.parse_html(html)

            filings = []
            secured_parties = []

            # Parse NC results
            results = soup.find_all("tr", class_=re.compile(r"result|data"))

            for result in results:
                text = result.get_text(separator=" ", strip=True)
                filing_num = self._extract_filing_number(text)

                if filing_num:
                    filings.append({
                        "number": filing_num,
                        "date": self._extract_filing_date(text),
                        "text": text[:500],
                    })

            if not filings:
                return

            mca_count = sum(1 for party in secured_parties if self._is_mca_funder(party))

            async for signal in self._create_ucc_signal(
                business_name=business_name,
                state="NC",
                filings=filings,
                secured_parties=secured_parties,
                mca_count=mca_count,
                search_url=url,
            ):
                yield signal

        except Exception as e:
            self.logger.error("Error in NC UCC search", business=business_name, error=str(e))

    async def _search_michigan_api(self, business_name: str) -> AsyncIterator[RawSignal]:
        """Search Michigan UCC via API endpoint."""
        api_url = "https://cofs.lara.state.mi.us/SearchApi/Search/Search"

        try:
            params = {
                "searchType": "UCC",
                "searchValue": business_name,
            }

            data = await self.fetch_json(f"{api_url}?{urlencode(params)}")

            filings = []
            secured_parties = []

            results = data.get("results", []) or data.get("data", [])

            for result in results:
                filing_num = result.get("filingNumber") or result.get("filing_number")
                if filing_num:
                    filings.append({
                        "number": filing_num,
                        "date": result.get("filingDate"),
                        "text": str(result),
                    })

                party = result.get("securedParty") or result.get("secured_party")
                if party:
                    secured_parties.append(party)

            if not filings:
                return

            mca_count = sum(1 for party in secured_parties if self._is_mca_funder(party))

            async for signal in self._create_ucc_signal(
                business_name=business_name,
                state="MI",
                filings=filings,
                secured_parties=secured_parties,
                mca_count=mca_count,
                search_url=api_url,
            ):
                yield signal

        except Exception as e:
            self.logger.error("Error in MI UCC API search", business=business_name, error=str(e))

    async def _search_with_playwright(
        self,
        business_name: str,
        config: StateUCCConfig,
    ) -> AsyncIterator[RawSignal]:
        """
        Search using Playwright for JavaScript-heavy sites.

        Used for: Colorado, Montana, Florida, Pennsylvania, Georgia
        """
        if not self._browser:
            self.logger.warning(
                "Playwright not available for JS-heavy site",
                state=config.state_code,
            )
            return

        try:
            page = await self._context.new_page()

            try:
                # Navigate to search page
                await page.goto(config.search_url, wait_until="networkidle")

                # Wait for search form to load
                await asyncio.sleep(2)  # Allow JS to initialize

                # Find and fill search input
                search_selectors = [
                    'input[name*="debtor"]',
                    'input[name*="search"]',
                    'input[name*="name"]',
                    'input[type="text"]',
                    '#searchInput',
                    '.search-input',
                ]

                search_filled = False
                for selector in search_selectors:
                    try:
                        input_elem = await page.query_selector(selector)
                        if input_elem:
                            await input_elem.fill(business_name)
                            search_filled = True
                            break
                    except Exception:
                        continue

                if not search_filled:
                    self.logger.warning("Could not find search input", state=config.state_code)
                    return

                # Find and click search button
                search_buttons = [
                    'button[type="submit"]',
                    'input[type="submit"]',
                    'button:has-text("Search")',
                    '.search-button',
                    '#searchButton',
                ]

                for selector in search_buttons:
                    try:
                        button = await page.query_selector(selector)
                        if button:
                            await button.click()
                            break
                    except Exception:
                        continue

                # Wait for results
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2)  # Additional wait for dynamic content

                # Get page content
                html = await page.content()
                soup = self.parse_html(html)

                # Generic parsing for results
                filings = []
                secured_parties = []

                # Look for common result patterns
                result_containers = soup.find_all(
                    ["tr", "div", "li"],
                    class_=re.compile(r"result|filing|record|item", re.I),
                )

                for container in result_containers:
                    text = container.get_text(separator=" ", strip=True)

                    filing_num = self._extract_filing_number(text)
                    if filing_num:
                        filings.append({
                            "number": filing_num,
                            "date": self._extract_filing_date(text),
                            "text": text[:500],
                        })

                    party_match = re.search(r"secured\s*party[:\s]*([^\n,]+)", text, re.I)
                    if party_match:
                        secured_parties.append(party_match.group(1).strip())

                if filings:
                    mca_count = sum(1 for party in secured_parties if self._is_mca_funder(party))

                    async for signal in self._create_ucc_signal(
                        business_name=business_name,
                        state=config.state_code,
                        filings=filings,
                        secured_parties=secured_parties,
                        mca_count=mca_count,
                        search_url=config.search_url,
                    ):
                        yield signal

            finally:
                await page.close()

        except Exception as e:
            self.logger.error(
                "Error in Playwright UCC search",
                state=config.state_code,
                business=business_name,
                error=str(e),
            )

    async def _search_generic(
        self,
        business_name: str,
        config: StateUCCConfig,
    ) -> AsyncIterator[RawSignal]:
        """Generic search for simple HTML sites."""
        try:
            params = {"debtor": quote_plus(business_name)}
            url = f"{config.search_url}?{urlencode(params)}"

            html = await self.fetch(url)
            soup = self.parse_html(html)

            filings = []
            secured_parties = []

            # Generic table parsing
            for row in soup.find_all("tr"):
                text = row.get_text(separator=" ", strip=True)

                filing_num = self._extract_filing_number(text)
                if filing_num:
                    filings.append({
                        "number": filing_num,
                        "date": self._extract_filing_date(text),
                        "text": text[:500],
                    })

            if filings:
                mca_count = sum(1 for party in secured_parties if self._is_mca_funder(party))

                async for signal in self._create_ucc_signal(
                    business_name=business_name,
                    state=config.state_code,
                    filings=filings,
                    secured_parties=secured_parties,
                    mca_count=mca_count,
                    search_url=url,
                ):
                    yield signal

        except Exception as e:
            self.logger.error(
                "Error in generic UCC search",
                state=config.state_code,
                business=business_name,
                error=str(e),
            )

    async def _create_ucc_signal(
        self,
        business_name: str,
        state: str,
        filings: list[dict],
        secured_parties: list[str],
        mca_count: int,
        search_url: str,
    ) -> AsyncIterator[RawSignal]:
        """Create a RawSignal from UCC filing data."""
        filing_count = len(filings)

        if filing_count == 0:
            return

        # Determine priority based on findings
        priority = SignalPriority.MEDIUM

        if mca_count >= 2:
            priority = SignalPriority.HIGH  # Stacking detected
        elif filing_count >= 3:
            priority = SignalPriority.HIGH  # Multiple creditors

        # Build description
        description = f"{filing_count} active UCC filings"
        if mca_count > 0:
            description += f" ({mca_count} appear to be MCA/financing)"

        # Build analysis content
        filing_details = "\n".join([
            f"- Filing #{f['number']}" + (f" ({f['date'].strftime('%Y-%m-%d') if f.get('date') else 'N/A'})" if f.get('date') else "")
            for f in filings[:10]
        ])

        party_list = "\n".join([f"- {p}" for p in secured_parties[:10]]) if secured_parties else "No secured parties extracted"

        raw_content = f"""
UCC Filing Summary: {business_name}
State: {state}

Active Filings: {filing_count}
Likely MCA/Funders: {mca_count}

Filing Details:
{filing_details}

Secured Parties:
{party_list}

Analysis:
{'STACKING ALERT: Multiple MCA funders detected - HIGH PRIORITY' if mca_count >= 2 else ''}
{'Multiple creditors - may have existing payment obligations' if filing_count >= 3 else ''}
{'Single funder detected - evaluate position carefully' if mca_count == 1 else ''}
{'No MCA indicators - may be equipment/traditional financing' if mca_count == 0 else ''}
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
            suggested_signal_type=SignalType.UCC_FILING,
            suggested_category=(
                SignalCategory.CASH_FLOW_STRESS if mca_count > 0
                else SignalCategory.EXPANSION_OPPORTUNITY
            ),
            suggested_priority=priority,
            external_id=f"ucc-{state}-{business_name.lower().replace(' ', '-')}",
            metadata={
                "active_filings": filing_count,
                "mca_funder_count": mca_count,
                "secured_parties": secured_parties[:10],
                "stacking_detected": mca_count >= 2,
                "filing_numbers": [f["number"] for f in filings[:10]],
                "state_config": {
                    "scrapability": self.configs[state].scrapability.value if state in self.configs else "unknown",
                    "method": self.configs[state].method.value if state in self.configs else "unknown",
                },
            },
        )

        if await self.validate_signal(signal):
            yield signal


def get_supported_states() -> list[dict]:
    """Get list of all supported states with their configuration details."""
    return [
        {
            "state_code": config.state_code,
            "state_name": config.state_name,
            "scrapability": config.scrapability.value,
            "method": config.method.value,
            "requires_login": config.requires_login,
            "fee_required": config.fee_required,
            "notes": config.notes,
            "is_available": (
                config.method != ScrapingMethod.NOT_SUPPORTED
                and not config.requires_login
                and not config.fee_required
            ),
        }
        for config in STATE_UCC_CONFIGS.values()
    ]


def get_scrapable_states() -> list[str]:
    """Get list of state codes that can be freely scraped."""
    return [
        code for code, config in STATE_UCC_CONFIGS.items()
        if config.method != ScrapingMethod.NOT_SUPPORTED
        and not config.requires_login
        and not config.fee_required
    ]
