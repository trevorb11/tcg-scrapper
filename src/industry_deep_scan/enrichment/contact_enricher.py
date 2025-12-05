"""
Contact Enricher Service
========================

Orchestrates contact information enrichment from multiple sources:
1. Website scraping (primary - free, no API key)
2. Google Places API (optional - requires API key)
3. Existing source data (BBB, listings already have some contact info)
"""

import asyncio
import os
import re
import urllib.request
import urllib.parse
import json
from typing import Optional

import structlog

from industry_deep_scan.enrichment.website_scraper import WebsiteContactScraper

logger = structlog.get_logger()


class ContactEnricher:
    """
    Enriches business leads with contact information.
    
    Uses a tiered approach:
    1. Try Google Places API if available (most reliable)
    2. Scrape business website for contact info
    3. Fall back to any data already in the signal
    """
    
    def __init__(self):
        self.logger = logger.bind(service="ContactEnricher")
        self.website_scraper = WebsiteContactScraper(timeout=8)
        self.google_api_key = os.environ.get("GOOGLE_PLACES_API_KEY")
        
        if self.google_api_key:
            self.logger.info("Google Places API enabled")
        else:
            self.logger.info("Google Places API not configured - using website scraping only")

    async def enrich(
        self,
        business_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None,
        website: Optional[str] = None,
        existing_phone: Optional[str] = None,
        existing_email: Optional[str] = None,
        existing_address: Optional[str] = None
    ) -> dict:
        """
        Enrich a business lead with contact information.
        
        Args:
            business_name: Name of the business
            city: City location (helps with Places lookup)
            state: State location
            website: Business website URL if known
            existing_*: Any contact info already available
            
        Returns:
            Dict with phone, email, address, website, and enrichment source
        """
        result = {
            "phone": existing_phone,
            "email": existing_email,
            "address": existing_address,
            "website": website,
            "enrichment_source": None
        }
        
        if self.google_api_key and business_name:
            places_data = await self._lookup_google_places(business_name, city, state)
            if places_data:
                if places_data.get("phone") and not result["phone"]:
                    result["phone"] = places_data["phone"]
                if places_data.get("address") and not result["address"]:
                    result["address"] = places_data["address"]
                if places_data.get("website") and not result["website"]:
                    result["website"] = places_data["website"]
                result["enrichment_source"] = "google_places"
        
        if result["website"] and (not result["phone"] or not result["email"]):
            website_data = await self.website_scraper.scrape_contact_info(result["website"])
            if website_data:
                if website_data.get("phone") and not result["phone"]:
                    result["phone"] = website_data["phone"]
                if website_data.get("email") and not result["email"]:
                    result["email"] = website_data["email"]
                if website_data.get("address") and not result["address"]:
                    result["address"] = website_data["address"]
                if not result["enrichment_source"]:
                    result["enrichment_source"] = "website_scrape"
        
        self.logger.info(
            "Enrichment complete",
            business=business_name,
            has_phone=bool(result["phone"]),
            has_email=bool(result["email"]),
            has_address=bool(result["address"]),
            source=result["enrichment_source"]
        )
        
        return result

    async def _lookup_google_places(
        self,
        business_name: str,
        city: Optional[str] = None,
        state: Optional[str] = None
    ) -> Optional[dict]:
        """
        Look up business in Google Places API.
        
        Args:
            business_name: Business name to search
            city: City for location context
            state: State for location context
            
        Returns:
            Dict with phone, address, website if found
        """
        if not self.google_api_key:
            return None
            
        try:
            query_parts = [business_name]
            if city:
                query_parts.append(city)
            if state:
                query_parts.append(state)
            
            query = " ".join(query_parts)
            encoded_query = urllib.parse.quote(query)
            
            search_url = f"https://maps.googleapis.com/maps/api/place/findplacefromtext/json?input={encoded_query}&inputtype=textquery&fields=place_id,name,formatted_address&key={self.google_api_key}"
            
            def do_search():
                req = urllib.request.Request(search_url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read().decode())
            
            loop = asyncio.get_event_loop()
            search_result = await loop.run_in_executor(None, do_search)
            
            if search_result.get("status") != "OK" or not search_result.get("candidates"):
                return None
            
            place_id = search_result["candidates"][0]["place_id"]
            
            details_url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=formatted_phone_number,formatted_address,website&key={self.google_api_key}"
            
            def do_details():
                req = urllib.request.Request(details_url)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read().decode())
            
            details_result = await loop.run_in_executor(None, do_details)
            
            if details_result.get("status") != "OK":
                return None
            
            place = details_result.get("result", {})
            
            return {
                "phone": place.get("formatted_phone_number"),
                "address": place.get("formatted_address"),
                "website": place.get("website")
            }
            
        except Exception as e:
            self.logger.warning("Google Places lookup failed", error=str(e))
            return None

    async def enrich_from_article(
        self,
        article_title: str,
        article_text: str,
        article_url: Optional[str] = None
    ) -> dict:
        """
        Extract business info from a news article and enrich with contact data.
        
        This tries to identify the main business mentioned and find its contact info.
        
        Args:
            article_title: Article headline
            article_text: Article body text
            article_url: URL of the article (for reference)
            
        Returns:
            Dict with business_name, phone, email, address, website
        """
        business_name = self._extract_business_from_text(article_title, article_text)
        city, state = self._extract_location_from_text(article_text)
        
        if not business_name:
            return {"business_name": None, "phone": None, "email": None, "address": None, "website": None}
        
        contact_info = await self.enrich(
            business_name=business_name,
            city=city,
            state=state
        )
        
        return {
            "business_name": business_name,
            "city": city,
            "state": state,
            **contact_info
        }

    def _extract_business_from_text(self, title: str, text: str) -> Optional[str]:
        """
        Extract likely business name from article text.
        
        Looks for patterns like:
        - "Company Name announced..."
        - "...says Company Name CEO..."
        - Company names followed by Inc, LLC, Corp, etc.
        """
        company_suffixes = r'(?:Inc\.?|LLC|Corp\.?|Corporation|Company|Co\.?|Ltd\.?|LP|LLP|Group|Holdings|Enterprises?)'
        pattern = rf'\b([A-Z][A-Za-z0-9\s&\'-]+?)\s+{company_suffixes}\b'
        
        matches = re.findall(pattern, title + " " + text[:500])
        if matches:
            return (matches[0] + " " + re.search(company_suffixes, title + " " + text[:500]).group()).strip()
        
        words = title.split()
        for i, word in enumerate(words):
            if word[0].isupper() and i + 1 < len(words):
                potential = []
                for w in words[i:]:
                    if w[0].isupper() or w.lower() in ['and', '&', 'the', 'of']:
                        potential.append(w)
                    else:
                        break
                if len(potential) >= 2:
                    name = ' '.join(potential)
                    if len(name) >= 5 and len(name) <= 50:
                        return name
        
        return None

    def _extract_location_from_text(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Extract city and state from article text."""
        states = {
            'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR',
            'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE',
            'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI', 'Idaho': 'ID',
            'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS',
            'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
            'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS',
            'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV',
            'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY',
            'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK',
            'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
            'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT',
            'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV',
            'Wisconsin': 'WI', 'Wyoming': 'WY'
        }
        
        pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?),?\s+(' + '|'.join(states.keys()) + r'|' + '|'.join(states.values()) + r')\b'
        match = re.search(pattern, text)
        
        if match:
            city = match.group(1)
            state = match.group(2)
            if len(state) > 2:
                state = states.get(state, state)
            return city, state
        
        return None, None
