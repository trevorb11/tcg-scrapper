"""
Base Source Connector
=====================

Abstract base class for all data source connectors.
Provides common functionality for scraping, rate limiting, and error handling.
"""

import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import aiohttp
import structlog
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from industry_deep_scan.config import get_settings
from industry_deep_scan.models import SignalCategory, SignalPriority, SignalType, SourceType

logger = structlog.get_logger()
settings = get_settings()


# User agent rotation pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


@dataclass
class RawSignal:
    """
    Raw signal data from a source before LLM processing.
    This is the intermediate format between scraping and database storage.
    """

    # Business identification
    business_name: str
    business_city: Optional[str] = None
    business_state: Optional[str] = None
    business_address: Optional[str] = None
    business_phone: Optional[str] = None
    business_website: Optional[str] = None

    # Signal content
    title: str = ""
    description: str = ""
    raw_content: str = ""  # Full scraped content for LLM analysis

    # Source info
    source_type: SourceType = SourceType.MANUAL
    source_url: Optional[str] = None
    source_date: Optional[datetime] = None

    # Optional pre-classification (can be overridden by LLM)
    suggested_signal_type: Optional[SignalType] = None
    suggested_category: Optional[SignalCategory] = None
    suggested_priority: Optional[SignalPriority] = None

    # External IDs for deduplication
    external_id: Optional[str] = None
    yelp_id: Optional[str] = None
    google_place_id: Optional[str] = None
    linkedin_id: Optional[str] = None
    bbb_id: Optional[str] = None

    # Additional business data
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    year_established: Optional[int] = None
    annual_revenue: Optional[float] = None

    # Review data
    rating: Optional[float] = None
    review_count: Optional[int] = None
    rating_change: Optional[float] = None  # Negative = declining

    # Metadata
    metadata: dict = field(default_factory=dict)


class RateLimiter:
    """Token bucket rate limiter for API/scraping calls."""

    def __init__(self, requests_per_second: float = 0.5):
        self.rate = requests_per_second
        self.tokens = 1.0
        self.last_update = asyncio.get_event_loop().time()
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait for rate limit token."""
        async with self.lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self.last_update
            self.tokens = min(1.0, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens < 1.0:
                wait_time = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
            else:
                self.tokens -= 1.0


class BaseSource(ABC):
    """
    Abstract base class for all data source connectors.

    Each source must implement:
    - source_type: The type of source (for tracking)
    - scan(): The main scanning method that yields raw signals
    """

    source_type: SourceType
    rate_limiter: RateLimiter

    def __init__(self):
        self.settings = get_settings()
        self.rate_limiter = RateLimiter(self.settings.scraping.requests_per_second)
        self._session: Optional[aiohttp.ClientSession] = None
        self.logger = logger.bind(source=self.__class__.__name__)

    async def __aenter__(self):
        """Async context manager entry."""
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.teardown()

    async def setup(self) -> None:
        """Initialize the source (create HTTP session, etc.)."""
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self.settings.scraping.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def teardown(self) -> None:
        """Cleanup resources."""
        if self._session:
            await self._session.close()
            self._session = None

    def get_user_agent(self) -> str:
        """Get a random user agent."""
        if self.settings.scraping.rotate_user_agents:
            return random.choice(USER_AGENTS)
        return USER_AGENTS[0]

    def get_headers(self) -> dict[str, str]:
        """Get request headers."""
        return {
            "User-Agent": self.get_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    @retry(
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def fetch(self, url: str, **kwargs) -> str:
        """
        Fetch a URL with rate limiting and retry logic.

        Args:
            url: URL to fetch
            **kwargs: Additional arguments for aiohttp request

        Returns:
            Response text
        """
        await self.rate_limiter.acquire()

        if self._session is None:
            await self.setup()

        headers = {**self.get_headers(), **kwargs.pop("headers", {})}

        self.logger.debug("Fetching URL", url=url)

        async with self._session.get(url, headers=headers, **kwargs) as response:
            response.raise_for_status()
            return await response.text()

    async def fetch_json(self, url: str, **kwargs) -> dict:
        """Fetch JSON from URL."""
        await self.rate_limiter.acquire()

        if self._session is None:
            await self.setup()

        headers = {
            **self.get_headers(),
            "Accept": "application/json",
            **kwargs.pop("headers", {}),
        }

        async with self._session.get(url, headers=headers, **kwargs) as response:
            response.raise_for_status()
            return await response.json()

    def parse_html(self, html: str) -> BeautifulSoup:
        """Parse HTML content."""
        return BeautifulSoup(html, "lxml")

    def extract_phone(self, text: str) -> Optional[str]:
        """Extract phone number from text."""
        import re

        # Common US phone patterns
        patterns = [
            r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
            r"\d{3}[-.\s]\d{3}[-.\s]\d{4}",
            r"\d{10}",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                # Normalize to digits only
                digits = re.sub(r"\D", "", match.group())
                if len(digits) == 10:
                    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        return None

    def extract_email(self, text: str) -> Optional[str]:
        """Extract email from text."""
        import re

        pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        match = re.search(pattern, text)
        return match.group() if match else None

    def clean_text(self, text: str) -> str:
        """Clean and normalize text."""
        import re

        if not text:
            return ""
        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text)
        # Remove special characters but keep basic punctuation
        text = re.sub(r"[^\w\s.,!?;:'\"-]", "", text)
        return text.strip()

    def parse_state(self, text: str) -> Optional[str]:
        """Extract US state code from text."""
        # State abbreviations
        states = {
            "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
            "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
            "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
            "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
            "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
            "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
            "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
            "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
            "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
            "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
            "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
            "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
            "wisconsin": "WI", "wyoming": "WY",
        }

        text_lower = text.lower()

        # Check for full state name
        for name, code in states.items():
            if name in text_lower:
                return code

        # Check for state code
        import re
        match = re.search(r"\b([A-Z]{2})\b", text)
        if match and match.group(1) in states.values():
            return match.group(1)

        return None

    @abstractmethod
    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan the source for signals.

        Args:
            states: List of state codes to target
            cities: List of city names to target
            industries: List of industries to target
            **kwargs: Source-specific parameters

        Yields:
            RawSignal objects for each detected signal
        """
        pass

    async def validate_signal(self, signal: RawSignal) -> bool:
        """
        Validate a raw signal before processing.
        Override in subclasses for source-specific validation.
        """
        # Must have a business name
        if not signal.business_name or len(signal.business_name) < 2:
            return False

        # Must have some content
        if not signal.raw_content and not signal.description:
            return False

        return True


class APISource(BaseSource):
    """Base class for sources that use official APIs."""

    api_key: Optional[str] = None
    api_base_url: str = ""

    async def api_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[dict] = None,
        data: Optional[dict] = None,
    ) -> dict:
        """Make an authenticated API request."""
        await self.rate_limiter.acquire()

        if self._session is None:
            await self.setup()

        url = f"{self.api_base_url.rstrip('/')}/{endpoint.lstrip('/')}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        async with self._session.request(
            method, url, headers=headers, params=params, json=data
        ) as response:
            response.raise_for_status()
            return await response.json()


class PlaywrightSource(BaseSource):
    """Base class for sources requiring JavaScript rendering."""

    def __init__(self):
        super().__init__()
        self._browser = None
        self._context = None

    async def setup(self) -> None:
        """Initialize Playwright browser."""
        await super().setup()

        if self.settings.scraping.use_playwright:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.settings.scraping.headless
            )
            self._context = await self._browser.new_context(
                user_agent=self.get_user_agent(),
                viewport={"width": 1920, "height": 1080},
            )

    async def teardown(self) -> None:
        """Close Playwright browser."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_playwright") and self._playwright:
            await self._playwright.stop()

        await super().teardown()

    async def fetch_with_js(self, url: str, wait_for: Optional[str] = None) -> str:
        """Fetch page with JavaScript rendering."""
        await self.rate_limiter.acquire()

        if not self._browser:
            raise RuntimeError("Playwright not initialized. Use 'async with' context manager.")

        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="networkidle")

            if wait_for:
                await page.wait_for_selector(wait_for, timeout=10000)

            return await page.content()
        finally:
            await page.close()
