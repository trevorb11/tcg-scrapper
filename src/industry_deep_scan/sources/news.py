"""
News Source Connectors
======================

Scan local and national news for business funding signals.
Triggers: expansions, layoffs, contracts, financial trouble, permits, etc.
"""

import asyncio
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional
from urllib.parse import quote_plus

import feedparser
import structlog

from industry_deep_scan.models import SignalCategory, SignalPriority, SignalType, SourceType
from industry_deep_scan.sources.base import BaseSource, RawSignal

logger = structlog.get_logger()


class GoogleNewsSource(BaseSource):
    """
    Scrape Google News RSS for business-related signals.
    Free, no API key required.
    """

    source_type = SourceType.NEWS

    # Keywords that indicate funding triggers
    TRIGGER_KEYWORDS = {
        # Cash flow / distress signals
        "layoffs": (SignalType.LAYOFFS, SignalCategory.DISTRESS_HIGH_REVENUE),
        "layoff": (SignalType.LAYOFFS, SignalCategory.DISTRESS_HIGH_REVENUE),
        "downsizing": (SignalType.LAYOFFS, SignalCategory.DISTRESS_HIGH_REVENUE),
        "workforce reduction": (SignalType.LAYOFFS, SignalCategory.DISTRESS_HIGH_REVENUE),
        "bankruptcy": (SignalType.CASH_SQUEEZE, SignalCategory.CASH_FLOW_STRESS),
        "financial trouble": (SignalType.CASH_SQUEEZE, SignalCategory.CASH_FLOW_STRESS),
        "cash crunch": (SignalType.CASH_SQUEEZE, SignalCategory.CASH_FLOW_STRESS),
        "struggling": (SignalType.CASH_SQUEEZE, SignalCategory.DISTRESS_HIGH_REVENUE),

        # Growth signals
        "expansion": (SignalType.EXPANSION, SignalCategory.RAPID_GROWTH),
        "expanding": (SignalType.EXPANSION, SignalCategory.RAPID_GROWTH),
        "new location": (SignalType.NEW_LOCATION, SignalCategory.EXPANSION_OPPORTUNITY),
        "grand opening": (SignalType.NEW_LOCATION, SignalCategory.EXPANSION_OPPORTUNITY),
        "hiring": (SignalType.HIRING_SURGE, SignalCategory.RAPID_GROWTH),
        "adding jobs": (SignalType.HIRING_SURGE, SignalCategory.RAPID_GROWTH),
        "new contract": (SignalType.NEW_CONTRACT, SignalCategory.RAPID_GROWTH),
        "awarded contract": (SignalType.NEW_CONTRACT, SignalCategory.RAPID_GROWTH),
        "wins contract": (SignalType.NEW_CONTRACT, SignalCategory.RAPID_GROWTH),

        # Equipment / investment
        "new equipment": (SignalType.EQUIPMENT_PURCHASE, SignalCategory.EXPANSION_OPPORTUNITY),
        "purchased equipment": (SignalType.EQUIPMENT_PURCHASE, SignalCategory.EXPANSION_OPPORTUNITY),
        "fleet expansion": (SignalType.EQUIPMENT_PURCHASE, SignalCategory.EXPANSION_OPPORTUNITY),

        # Acquisition / ownership change
        "acquisition": (SignalType.OWNER_CHANGE, SignalCategory.ACQUISITION_TARGET),
        "acquired": (SignalType.OWNER_CHANGE, SignalCategory.ACQUISITION_TARGET),
        "for sale": (SignalType.BUSINESS_FOR_SALE, SignalCategory.ACQUISITION_TARGET),
        "selling business": (SignalType.BUSINESS_FOR_SALE, SignalCategory.ACQUISITION_TARGET),
    }

    # Industry keywords for targeted searches
    INDUSTRY_KEYWORDS = {
        "construction": ["construction company", "contractor", "builder", "general contractor"],
        "trucking": ["trucking company", "freight", "logistics", "hauling", "transportation"],
        "restaurant": ["restaurant", "eatery", "dining", "food service", "catering"],
        "medical": ["medical practice", "clinic", "healthcare", "doctor's office", "dental"],
        "manufacturing": ["manufacturer", "manufacturing", "factory", "production"],
        "auto repair": ["auto repair", "mechanic", "auto body", "car service"],
        "retail": ["retail store", "shop", "boutique", "retail business"],
        "landscaping": ["landscaping", "lawn care", "grounds maintenance"],
        "hvac": ["hvac", "heating cooling", "air conditioning", "furnace"],
        "plumbing": ["plumber", "plumbing company", "drain", "pipe"],
        "electrical": ["electrician", "electrical contractor", "wiring"],
    }

    def _build_search_queries(
        self,
        states: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
    ) -> list[str]:
        """Build Google News search queries."""
        queries = []

        # Default high-value industries if none specified
        target_industries = industries or list(self.INDUSTRY_KEYWORDS.keys())

        # Default states if none specified
        target_states = states or self.settings.scraping.target_states[:10]

        for industry in target_industries:
            industry_terms = self.INDUSTRY_KEYWORDS.get(industry, [industry])

            for state in target_states:
                # Combine industry + state + trigger keywords
                for trigger in ["expansion", "hiring", "new contract", "layoffs", "struggling"]:
                    for term in industry_terms[:2]:  # Limit to avoid too many queries
                        query = f'"{term}" {state} {trigger}'
                        queries.append(query)

        return queries

    def _parse_rss_date(self, date_str: str) -> Optional[datetime]:
        """Parse RSS date formats."""
        try:
            import email.utils
            parsed = email.utils.parsedate_to_datetime(date_str)
            return parsed
        except Exception:
            return None

    def _detect_trigger(self, text: str) -> tuple[Optional[SignalType], Optional[SignalCategory]]:
        """Detect funding trigger in text."""
        text_lower = text.lower()

        for keyword, (signal_type, category) in self.TRIGGER_KEYWORDS.items():
            if keyword in text_lower:
                return signal_type, category

        return None, None

    def _extract_business_name(self, title: str, summary: str) -> Optional[str]:
        """Extract business name from news title/summary."""
        import re

        # Common patterns for business names in news
        patterns = [
            r"^([A-Z][A-Za-z\s&']+(?:Inc\.|LLC|Corp\.?|Company|Co\.))",
            r"([A-Z][A-Za-z\s&']+(?:Inc\.|LLC|Corp\.?|Company|Co\.?))\s+(?:announces|to|will|is|has)",
            r"at\s+([A-Z][A-Za-z\s&']+(?:Inc\.|LLC|Corp\.?|Company|Co\.?))",
        ]

        for pattern in patterns:
            match = re.search(pattern, title)
            if match:
                return match.group(1).strip()

            match = re.search(pattern, summary)
            if match:
                return match.group(1).strip()

        # Fallback: extract first capitalized phrase
        match = re.search(r"^([A-Z][A-Za-z\s]{2,30})", title)
        if match:
            name = match.group(1).strip()
            # Filter out common non-business starts
            stopwords = {"The", "This", "That", "These", "New", "Local", "Area", "City"}
            if name.split()[0] not in stopwords:
                return name

        return None

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        max_age_days: int = 7,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan Google News for business signals.

        Args:
            states: Target state codes (e.g., ["CA", "TX"])
            cities: Target cities (not used for Google News - too specific)
            industries: Target industries
            max_age_days: Only return news from this many days ago
        """
        queries = self._build_search_queries(states, industries)
        cutoff_date = datetime.utcnow() - timedelta(days=max_age_days)

        self.logger.info("Starting Google News scan", query_count=len(queries))

        for query in queries:
            try:
                # Google News RSS endpoint
                encoded_query = quote_plus(query)
                url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

                html = await self.fetch(url)
                feed = feedparser.parse(html)

                for entry in feed.entries:
                    try:
                        # Parse date
                        pub_date = self._parse_rss_date(entry.get("published", ""))
                        if pub_date and pub_date < cutoff_date:
                            continue

                        title = entry.get("title", "")
                        summary = entry.get("summary", "")
                        link = entry.get("link", "")

                        # Detect trigger
                        full_text = f"{title} {summary}"
                        signal_type, category = self._detect_trigger(full_text)

                        if not signal_type:
                            continue  # No funding trigger detected

                        # Extract business name
                        business_name = self._extract_business_name(title, summary)
                        if not business_name:
                            continue

                        # Extract state from query or content
                        state = None
                        for s in (states or self.settings.scraping.target_states):
                            if s in full_text.upper():
                                state = s
                                break

                        # Determine priority based on signal type
                        priority = SignalPriority.MEDIUM
                        if signal_type in [SignalType.LAYOFFS, SignalType.CASH_SQUEEZE]:
                            priority = SignalPriority.HIGH
                        elif signal_type in [SignalType.NEW_CONTRACT, SignalType.EXPANSION]:
                            priority = SignalPriority.HIGH

                        signal = RawSignal(
                            business_name=business_name,
                            business_state=state,
                            title=title,
                            description=summary,
                            raw_content=full_text,
                            source_type=self.source_type,
                            source_url=link,
                            source_date=pub_date,
                            suggested_signal_type=signal_type,
                            suggested_category=category,
                            suggested_priority=priority,
                            external_id=link,  # Use URL as dedup key
                        )

                        if await self.validate_signal(signal):
                            yield signal

                    except Exception as e:
                        self.logger.warning("Error processing news entry", error=str(e))
                        continue

                # Rate limit between queries
                await asyncio.sleep(1)

            except Exception as e:
                self.logger.error("Error fetching Google News", query=query, error=str(e))
                continue


class LocalNewsSource(BaseSource):
    """
    Scrape local news sites for hyper-local business signals.
    Targets regional business journals and local newspapers.
    """

    source_type = SourceType.NEWS

    # Local news source URLs by state
    LOCAL_NEWS_SOURCES = {
        "CA": [
            ("https://www.bizjournals.com/sanfrancisco/news", "SF Business Times"),
            ("https://www.bizjournals.com/losangeles/news", "LA Business Journal"),
            ("https://www.bizjournals.com/sandiego/news", "SD Business Journal"),
        ],
        "TX": [
            ("https://www.bizjournals.com/dallas/news", "Dallas Business Journal"),
            ("https://www.bizjournals.com/houston/news", "Houston Business Journal"),
            ("https://www.bizjournals.com/austin/news", "Austin Business Journal"),
        ],
        "FL": [
            ("https://www.bizjournals.com/southflorida/news", "South Florida BJ"),
            ("https://www.bizjournals.com/orlando/news", "Orlando Business Journal"),
            ("https://www.bizjournals.com/tampabay/news", "Tampa Bay BJ"),
        ],
        "NY": [
            ("https://www.bizjournals.com/newyork/news", "NY Business Journal"),
            ("https://www.bizjournals.com/albany/news", "Albany Business Review"),
            ("https://www.bizjournals.com/buffalo/news", "Buffalo Business First"),
        ],
        "IL": [
            ("https://www.bizjournals.com/chicago/news", "Chicago Business Journal"),
        ],
        "PA": [
            ("https://www.bizjournals.com/philadelphia/news", "Philadelphia BJ"),
            ("https://www.bizjournals.com/pittsburgh/news", "Pittsburgh BJ"),
        ],
        "OH": [
            ("https://www.bizjournals.com/cleveland/news", "Cleveland Business News"),
            ("https://www.bizjournals.com/columbus/news", "Columbus Business First"),
            ("https://www.bizjournals.com/cincinnati/news", "Cincinnati BJ"),
        ],
        "GA": [
            ("https://www.bizjournals.com/atlanta/news", "Atlanta Business Chronicle"),
        ],
        "NC": [
            ("https://www.bizjournals.com/charlotte/news", "Charlotte Business Journal"),
            ("https://www.bizjournals.com/triad/news", "Triad Business Journal"),
        ],
        "MI": [
            ("https://www.bizjournals.com/detroit/news", "Detroit Crain's"),
        ],
        "NJ": [
            ("https://www.bizjournals.com/newjersey/news", "NJ Biz"),
        ],
        "VA": [
            ("https://www.bizjournals.com/washington/news", "Washington Business Journal"),
        ],
        "WA": [
            ("https://www.bizjournals.com/seattle/news", "Puget Sound BJ"),
        ],
        "AZ": [
            ("https://www.bizjournals.com/phoenix/news", "Phoenix Business Journal"),
        ],
        "MA": [
            ("https://www.bizjournals.com/boston/news", "Boston Business Journal"),
        ],
        "TN": [
            ("https://www.bizjournals.com/nashville/news", "Nashville Business Journal"),
            ("https://www.bizjournals.com/memphis/news", "Memphis Business Journal"),
        ],
        "MO": [
            ("https://www.bizjournals.com/stlouis/news", "St. Louis Business Journal"),
            ("https://www.bizjournals.com/kansascity/news", "KC Business Journal"),
        ],
        "CO": [
            ("https://www.bizjournals.com/denver/news", "Denver Business Journal"),
        ],
        "IN": [
            ("https://www.bizjournals.com/indianapolis/news", "Indianapolis BJ"),
        ],
        "WI": [
            ("https://www.bizjournals.com/milwaukee/news", "Milwaukee BJ"),
        ],
    }

    # Trigger phrases for local news
    TRIGGER_PATTERNS = [
        # Growth
        (r"plans?\s+to\s+expand", SignalType.EXPANSION, SignalCategory.RAPID_GROWTH),
        (r"hiring\s+\d+", SignalType.HIRING_SURGE, SignalCategory.RAPID_GROWTH),
        (r"add(?:ing|s)?\s+\d+\s+jobs?", SignalType.HIRING_SURGE, SignalCategory.RAPID_GROWTH),
        (r"won?\s+(?:a\s+)?contract", SignalType.NEW_CONTRACT, SignalCategory.RAPID_GROWTH),
        (r"awarded\s+contract", SignalType.NEW_CONTRACT, SignalCategory.RAPID_GROWTH),
        (r"opens?\s+new\s+location", SignalType.NEW_LOCATION, SignalCategory.EXPANSION_OPPORTUNITY),
        (r"breaking\s+ground", SignalType.EXPANSION, SignalCategory.EXPANSION_OPPORTUNITY),

        # Distress
        (r"lay(?:ing)?\s+off", SignalType.LAYOFFS, SignalCategory.DISTRESS_HIGH_REVENUE),
        (r"cut(?:ting|s)?\s+\d+\s+jobs?", SignalType.LAYOFFS, SignalCategory.DISTRESS_HIGH_REVENUE),
        (r"workforce\s+reduction", SignalType.LAYOFFS, SignalCategory.DISTRESS_HIGH_REVENUE),
        (r"files?\s+(?:for\s+)?bankruptcy", SignalType.CASH_SQUEEZE, SignalCategory.CASH_FLOW_STRESS),
        (r"financial\s+difficul", SignalType.CASH_SQUEEZE, SignalCategory.CASH_FLOW_STRESS),
        (r"struggling\s+to", SignalType.CASH_SQUEEZE, SignalCategory.DISTRESS_HIGH_REVENUE),

        # Equipment
        (r"purchas(?:ed?|ing)\s+(?:new\s+)?equipment", SignalType.EQUIPMENT_PURCHASE, SignalCategory.EXPANSION_OPPORTUNITY),
        (r"fleet\s+of\s+\d+", SignalType.EQUIPMENT_PURCHASE, SignalCategory.EXPANSION_OPPORTUNITY),
    ]

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """Scan local business journals for signals."""
        import re

        target_states = states or list(self.LOCAL_NEWS_SOURCES.keys())

        for state in target_states:
            sources = self.LOCAL_NEWS_SOURCES.get(state, [])

            for url, source_name in sources:
                try:
                    self.logger.info("Scanning local news source", source=source_name, state=state)

                    # Note: BizJournals requires subscription for full access
                    # This will get headlines and snippets from the news page
                    html = await self.fetch(url)
                    soup = self.parse_html(html)

                    # Find article headlines and snippets
                    articles = soup.find_all("article") or soup.find_all("div", class_=re.compile(r"card|item|story"))

                    for article in articles[:20]:  # Limit per source
                        try:
                            # Extract headline
                            headline_elem = article.find(["h1", "h2", "h3", "a"])
                            if not headline_elem:
                                continue

                            headline = headline_elem.get_text(strip=True)

                            # Extract snippet/summary
                            snippet_elem = article.find(["p", "div"], class_=re.compile(r"summary|desc|snippet|teaser"))
                            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                            full_text = f"{headline} {snippet}"

                            # Check for triggers
                            signal_type = None
                            category = None

                            for pattern, sig_type, cat in self.TRIGGER_PATTERNS:
                                if re.search(pattern, full_text, re.IGNORECASE):
                                    signal_type = sig_type
                                    category = cat
                                    break

                            if not signal_type:
                                continue

                            # Extract link
                            link_elem = article.find("a", href=True)
                            link = ""
                            if link_elem:
                                href = link_elem["href"]
                                link = href if href.startswith("http") else f"https://www.bizjournals.com{href}"

                            # Try to extract business name
                            business_name = None
                            # Common pattern: "Company Name plans to..."
                            name_match = re.search(r"^([A-Z][A-Za-z\s&'.]+?)(?:\s+(?:plans?|to|is|has|will|won|opens?))", headline)
                            if name_match:
                                business_name = name_match.group(1).strip()

                            if not business_name:
                                # Use first capitalized words
                                name_match = re.search(r"^([A-Z][A-Za-z\s]{3,30})", headline)
                                if name_match:
                                    business_name = name_match.group(1).strip()

                            if not business_name:
                                continue

                            signal = RawSignal(
                                business_name=business_name,
                                business_state=state,
                                title=headline,
                                description=snippet,
                                raw_content=full_text,
                                source_type=self.source_type,
                                source_url=link,
                                source_date=datetime.utcnow(),  # Local news doesn't always have dates
                                suggested_signal_type=signal_type,
                                suggested_category=category,
                                suggested_priority=SignalPriority.MEDIUM,
                                external_id=link,
                                metadata={"source_name": source_name},
                            )

                            if await self.validate_signal(signal):
                                yield signal

                        except Exception as e:
                            self.logger.warning("Error parsing article", error=str(e))
                            continue

                except Exception as e:
                    self.logger.error("Error fetching local news", source=source_name, error=str(e))
                    continue
