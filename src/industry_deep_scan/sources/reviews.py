"""
Review Source Connectors
========================

Monitor Yelp and Google Reviews for quality changes.
A sudden drop in ratings often indicates cash flow problems (understaffing,
cutting corners, supply issues).
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional
from urllib.parse import quote_plus

import structlog

from industry_deep_scan.models import SignalCategory, SignalPriority, SignalType, SourceType
from industry_deep_scan.sources.base import APISource, PlaywrightSource, RawSignal

logger = structlog.get_logger()


class YelpSource(APISource):
    """
    Yelp Fusion API connector for business review monitoring.

    Requires Yelp Fusion API key (free tier: 5000 calls/day).
    Get key at: https://www.yelp.com/developers/v3/manage_app
    """

    source_type = SourceType.YELP
    api_base_url = "https://api.yelp.com/v3"

    # Industries to monitor (Yelp category aliases)
    INDUSTRY_CATEGORIES = {
        "restaurant": ["restaurants", "food", "bars", "cafes", "bakeries"],
        "auto_repair": ["autorepair", "auto", "autoglass", "tires", "oilchange"],
        "construction": ["contractors", "electricians", "plumbing", "roofing", "hvac"],
        "medical": ["doctors", "dentists", "health", "optometrists", "chiropractors"],
        "retail": ["shopping", "fashion", "jewelry", "giftshops"],
        "beauty": ["hair", "beautysvc", "nailsalons", "skincare"],
        "fitness": ["gyms", "fitness", "yoga", "martialarts"],
        "professional": ["accountants", "lawyers", "financialadvising", "realestate"],
    }

    # Rating change thresholds
    RATING_DROP_THRESHOLD = 0.3  # Drop of 0.3+ stars = potential distress
    REVIEW_COUNT_MIN = 10  # Minimum reviews for reliable signal

    def __init__(self):
        super().__init__()
        self.api_key = self.settings.sources.yelp_api_key.get_secret_value()

    async def api_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[dict] = None,
        data: Optional[dict] = None,
    ) -> dict:
        """Make Yelp API request with proper auth header."""
        await self.rate_limiter.acquire()

        if self._session is None:
            await self.setup()

        url = f"{self.api_base_url}/{endpoint.lstrip('/')}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        self.logger.debug("Yelp API request", endpoint=endpoint, params=params)

        async with self._session.get(url, headers=headers, params=params) as response:
            if response.status == 429:
                self.logger.warning("Yelp API rate limited, waiting...")
                await asyncio.sleep(60)
                return await self.api_request(endpoint, method, params, data)

            response.raise_for_status()
            return await response.json()

    async def search_businesses(
        self,
        location: str,
        categories: Optional[list[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Search Yelp for businesses."""
        params = {
            "location": location,
            "limit": min(limit, 50),  # Yelp max is 50
            "offset": offset,
            "sort_by": "review_count",  # Get established businesses first
        }

        if categories:
            params["categories"] = ",".join(categories)

        result = await self.api_request("businesses/search", params=params)
        return result.get("businesses", [])

    async def get_business_details(self, business_id: str) -> dict:
        """Get detailed business info including recent reviews."""
        return await self.api_request(f"businesses/{business_id}")

    async def get_reviews(self, business_id: str, limit: int = 3) -> list[dict]:
        """Get recent reviews for a business."""
        result = await self.api_request(f"businesses/{business_id}/reviews", params={"limit": limit})
        return result.get("reviews", [])

    def _analyze_reviews(self, reviews: list[dict]) -> tuple[float, list[str]]:
        """
        Analyze reviews for distress signals.

        Returns:
            Tuple of (average_recent_rating, list of negative keywords found)
        """
        if not reviews:
            return 0.0, []

        # Calculate average recent rating
        ratings = [r.get("rating", 0) for r in reviews]
        avg_rating = sum(ratings) / len(ratings)

        # Look for distress keywords in review text
        distress_keywords = [
            "declined", "worse", "not the same", "used to be better",
            "understaffed", "slow service", "wait", "closed early",
            "dirty", "never again", "avoid", "rude", "cold food",
            "poor quality", "disappointed", "overpriced", "ripoff",
        ]

        found_keywords = []
        for review in reviews:
            text = review.get("text", "").lower()
            for keyword in distress_keywords:
                if keyword in text and keyword not in found_keywords:
                    found_keywords.append(keyword)

        return avg_rating, found_keywords

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        min_rating_drop: float = 0.3,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan Yelp for businesses showing rating declines.

        Strategy:
        1. Search for businesses in target locations
        2. Check current rating vs historical (if available)
        3. Analyze recent reviews for distress keywords
        4. Flag businesses with quality decline signals
        """
        if not self.api_key:
            self.logger.warning("Yelp API key not configured, skipping Yelp scan")
            return

        # Build location list
        locations = []
        target_states = states or self.settings.scraping.target_states[:5]

        if cities:
            locations = cities
        else:
            # Use major cities in target states
            state_cities = {
                "CA": ["Los Angeles, CA", "San Francisco, CA", "San Diego, CA"],
                "TX": ["Houston, TX", "Dallas, TX", "Austin, TX"],
                "FL": ["Miami, FL", "Orlando, FL", "Tampa, FL"],
                "NY": ["New York, NY", "Buffalo, NY"],
                "IL": ["Chicago, IL"],
                "PA": ["Philadelphia, PA", "Pittsburgh, PA"],
                "OH": ["Columbus, OH", "Cleveland, OH", "Cincinnati, OH"],
                "GA": ["Atlanta, GA"],
                "NC": ["Charlotte, NC", "Raleigh, NC"],
                "MI": ["Detroit, MI"],
            }

            for state in target_states:
                locations.extend(state_cities.get(state, [f"{state}"]))

        # Build category list
        categories = []
        target_industries = industries or ["restaurant", "auto_repair", "construction"]
        for industry in target_industries:
            categories.extend(self.INDUSTRY_CATEGORIES.get(industry, [industry]))

        self.logger.info(
            "Starting Yelp scan",
            locations=len(locations),
            categories=categories,
        )

        for location in locations:
            try:
                businesses = await self.search_businesses(
                    location=location,
                    categories=categories[:5],  # Yelp limits category combinations
                    limit=50,
                )

                for biz in businesses:
                    try:
                        yelp_id = biz.get("id")
                        name = biz.get("name", "")
                        rating = biz.get("rating", 0)
                        review_count = biz.get("review_count", 0)

                        # Skip businesses with too few reviews
                        if review_count < self.REVIEW_COUNT_MIN:
                            continue

                        # Get recent reviews for analysis
                        reviews = await self.get_reviews(yelp_id, limit=3)
                        recent_avg, distress_keywords = self._analyze_reviews(reviews)

                        # Determine if this is a distress signal
                        is_distress = False
                        signal_strength = 0.0

                        # Rating decline (comparing recent reviews to overall)
                        if recent_avg > 0 and (rating - recent_avg) > min_rating_drop:
                            is_distress = True
                            signal_strength = min(10, (rating - recent_avg) * 10)

                        # Distress keywords in reviews
                        if len(distress_keywords) >= 2:
                            is_distress = True
                            signal_strength = max(signal_strength, len(distress_keywords) * 2)

                        # Low overall rating with decent volume
                        if rating <= 2.5 and review_count >= 20:
                            is_distress = True
                            signal_strength = max(signal_strength, 6)

                        if not is_distress:
                            continue

                        # Extract location info
                        location_data = biz.get("location", {})
                        address_parts = location_data.get("display_address", [])
                        address = ", ".join(address_parts) if address_parts else None

                        # Build description
                        description = f"Yelp rating: {rating}/5 ({review_count} reviews). "
                        if recent_avg > 0:
                            description += f"Recent reviews avg: {recent_avg:.1f}/5. "
                        if distress_keywords:
                            description += f"Warning keywords: {', '.join(distress_keywords[:5])}. "

                        # Build raw content with review excerpts
                        raw_content = f"Business: {name}\n"
                        raw_content += f"Rating: {rating}/5 based on {review_count} reviews\n"
                        raw_content += f"Recent average: {recent_avg:.1f}/5\n\n"
                        raw_content += "Recent Review Excerpts:\n"
                        for review in reviews:
                            raw_content += f"- ({review.get('rating')}/5) {review.get('text', '')[:200]}...\n"

                        # Determine priority
                        priority = SignalPriority.LOW
                        if signal_strength >= 7:
                            priority = SignalPriority.HIGH
                        elif signal_strength >= 5:
                            priority = SignalPriority.MEDIUM

                        signal = RawSignal(
                            business_name=name,
                            business_city=location_data.get("city"),
                            business_state=location_data.get("state"),
                            business_address=address,
                            business_phone=biz.get("phone"),
                            title=f"Review Decline Detected: {name}",
                            description=description,
                            raw_content=raw_content,
                            source_type=self.source_type,
                            source_url=biz.get("url"),
                            source_date=datetime.utcnow(),
                            suggested_signal_type=SignalType.REVIEW_DECLINE,
                            suggested_category=SignalCategory.CASH_FLOW_STRESS,
                            suggested_priority=priority,
                            external_id=yelp_id,
                            yelp_id=yelp_id,
                            industry=", ".join(biz.get("categories", [{}])[0].get("title", "").split()),
                            rating=rating,
                            review_count=review_count,
                            rating_change=recent_avg - rating if recent_avg else None,
                            metadata={
                                "yelp_categories": [c.get("alias") for c in biz.get("categories", [])],
                                "distress_keywords": distress_keywords,
                                "signal_strength": signal_strength,
                            },
                        )

                        if await self.validate_signal(signal):
                            yield signal

                    except Exception as e:
                        self.logger.warning(
                            "Error processing Yelp business",
                            business=biz.get("name"),
                            error=str(e),
                        )
                        continue

                # Rate limit between locations
                await asyncio.sleep(2)

            except Exception as e:
                self.logger.error("Error scanning Yelp location", location=location, error=str(e))
                continue


class GoogleReviewsSource(PlaywrightSource):
    """
    Google Maps/Reviews scraper for review monitoring.

    Uses Playwright for JavaScript rendering since Google Maps is heavily dynamic.
    This is a complementary source to Yelp.
    """

    source_type = SourceType.GOOGLE_REVIEWS

    async def scan(
        self,
        states: Optional[list[str]] = None,
        cities: Optional[list[str]] = None,
        industries: Optional[list[str]] = None,
        **kwargs,
    ) -> AsyncIterator[RawSignal]:
        """
        Scan Google Maps for business reviews.

        Note: Google has strict scraping policies. This is designed for
        light usage. Consider using the official Places API for production.
        """
        if not self.settings.scraping.use_playwright:
            self.logger.info("Playwright disabled, skipping Google Reviews scan")
            return

        target_states = states or self.settings.scraping.target_states[:3]
        target_industries = industries or ["restaurant", "contractor", "auto repair"]

        for state in target_states:
            for industry in target_industries:
                query = f"{industry} in {state}"
                search_url = f"https://www.google.com/maps/search/{quote_plus(query)}"

                try:
                    self.logger.info("Scanning Google Maps", query=query)

                    html = await self.fetch_with_js(search_url, wait_for='div[role="feed"]')
                    soup = self.parse_html(html)

                    # Find business listings
                    # Note: Google Maps DOM structure changes frequently
                    listings = soup.find_all("div", class_=re.compile(r"Nv2PK|fontBodyMedium"))

                    for listing in listings[:20]:  # Limit per search
                        try:
                            # Extract business info
                            name_elem = listing.find("div", class_=re.compile(r"fontHeadlineSmall|qBF1Pd"))
                            if not name_elem:
                                continue

                            name = name_elem.get_text(strip=True)

                            # Extract rating
                            rating_elem = listing.find("span", class_=re.compile(r"ZkP5Je|MW4etd"))
                            rating = 0.0
                            if rating_elem:
                                try:
                                    rating = float(rating_elem.get_text(strip=True))
                                except ValueError:
                                    pass

                            # Extract review count
                            review_elem = listing.find("span", class_=re.compile(r"UY7F9|e4rVHe"))
                            review_count = 0
                            if review_elem:
                                text = review_elem.get_text(strip=True)
                                match = re.search(r"\(?([\d,]+)\)?", text)
                                if match:
                                    review_count = int(match.group(1).replace(",", ""))

                            # Only flag low-rated businesses
                            if rating >= 3.5 or review_count < 10:
                                continue

                            # Extract address
                            address_elem = listing.find("div", class_=re.compile(r"W4Efsd"))
                            address = address_elem.get_text(strip=True) if address_elem else None

                            signal = RawSignal(
                                business_name=name,
                                business_state=state,
                                business_address=address,
                                title=f"Low Google Rating: {name} ({rating}/5)",
                                description=f"Google rating {rating}/5 with {review_count} reviews",
                                raw_content=f"Business: {name}\nRating: {rating}/5\nReviews: {review_count}\nAddress: {address}",
                                source_type=self.source_type,
                                source_url=search_url,
                                source_date=datetime.utcnow(),
                                suggested_signal_type=SignalType.REVIEW_DECLINE,
                                suggested_category=SignalCategory.CASH_FLOW_STRESS,
                                suggested_priority=SignalPriority.MEDIUM,
                                rating=rating,
                                review_count=review_count,
                                industry=industry,
                            )

                            if await self.validate_signal(signal):
                                yield signal

                        except Exception as e:
                            self.logger.warning("Error parsing Google listing", error=str(e))
                            continue

                    await asyncio.sleep(5)  # Be very conservative with Google

                except Exception as e:
                    self.logger.error("Error scanning Google Maps", query=query, error=str(e))
                    continue
