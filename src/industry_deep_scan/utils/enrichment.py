"""
Business Enrichment
===================

Utilities for enriching business data with additional information.
"""

import re
from typing import Optional

import structlog

from industry_deep_scan.models import Business

logger = structlog.get_logger()


class BusinessEnricher:
    """
    Enriches business records with additional data.

    Features:
    - Phone number normalization
    - Revenue estimation from indicators
    - Industry classification
    - Geographic enrichment
    """

    # Revenue estimation based on employee count (rough heuristic)
    REVENUE_PER_EMPLOYEE = {
        "restaurant": 80000,
        "construction": 150000,
        "trucking": 200000,
        "medical": 200000,
        "manufacturing": 180000,
        "retail": 100000,
        "auto repair": 120000,
        "landscaping": 90000,
        "hvac": 150000,
        "plumbing": 140000,
        "electrical": 130000,
        "default": 120000,
    }

    # Industry classification keywords
    INDUSTRY_KEYWORDS = {
        "construction": [
            "construction", "contractor", "builder", "roofing", "remodel",
            "renovation", "concrete", "excavation", "framing",
        ],
        "trucking": [
            "trucking", "freight", "hauling", "logistics", "transport",
            "shipping", "delivery", "carrier",
        ],
        "restaurant": [
            "restaurant", "cafe", "diner", "bistro", "grill", "kitchen",
            "eatery", "pizzeria", "taqueria", "sushi", "bbq",
        ],
        "medical": [
            "medical", "clinic", "doctor", "dentist", "dental", "chiropractic",
            "physical therapy", "urgent care", "pharmacy",
        ],
        "manufacturing": [
            "manufacturing", "factory", "production", "fabrication",
            "assembly", "machining", "processing",
        ],
        "auto_repair": [
            "auto repair", "mechanic", "automotive", "car service",
            "tire", "transmission", "brake", "body shop",
        ],
        "retail": [
            "retail", "store", "shop", "boutique", "mart", "outlet",
            "wholesal",
        ],
        "landscaping": [
            "landscaping", "lawn", "garden", "irrigation", "tree service",
            "grounds", "outdoor",
        ],
        "hvac": [
            "hvac", "heating", "cooling", "air conditioning", "furnace",
            "ventilation", "ductwork",
        ],
        "plumbing": [
            "plumbing", "plumber", "pipe", "drain", "sewer", "water heater",
        ],
        "electrical": [
            "electrical", "electrician", "wiring", "lighting", "power",
        ],
    }

    def normalize_phone(self, phone: Optional[str]) -> Optional[str]:
        """
        Normalize phone number to consistent format.

        Returns format: (XXX) XXX-XXXX
        """
        if not phone:
            return None

        # Extract digits
        digits = re.sub(r"\D", "", phone)

        # Handle country code
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]

        if len(digits) != 10:
            return phone  # Return original if can't normalize

        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

    def estimate_revenue(
        self,
        employee_count: Optional[int] = None,
        industry: Optional[str] = None,
        review_count: Optional[int] = None,
    ) -> Optional[float]:
        """
        Estimate annual revenue based on available indicators.

        This is a rough heuristic - actual revenue varies significantly.
        """
        if employee_count:
            # Use industry-specific revenue per employee
            industry_lower = (industry or "").lower()

            rev_per_emp = self.REVENUE_PER_EMPLOYEE.get("default")
            for ind, rate in self.REVENUE_PER_EMPLOYEE.items():
                if ind in industry_lower:
                    rev_per_emp = rate
                    break

            return employee_count * rev_per_emp

        elif review_count:
            # Very rough estimate based on review activity
            # More reviews = more customers = more revenue
            if review_count > 500:
                return 2000000  # $2M+
            elif review_count > 200:
                return 1000000  # $1M
            elif review_count > 100:
                return 500000  # $500K
            elif review_count > 50:
                return 300000  # $300K
            else:
                return 150000  # $150K

        return None

    def classify_industry(self, business_name: str, description: str = "") -> Optional[str]:
        """
        Classify industry based on business name and description.
        """
        text = f"{business_name} {description}".lower()

        for industry, keywords in self.INDUSTRY_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return industry.replace("_", " ").title()

        return None

    def enrich(self, business: Business) -> Business:
        """
        Enrich a business record with additional data.
        """
        # Normalize phone
        if business.phone:
            business.phone = self.normalize_phone(business.phone)

        # Classify industry if not set
        if not business.industry and business.name:
            business.industry = self.classify_industry(business.name)

        # Estimate revenue if not set
        if not business.annual_revenue_estimate:
            business.annual_revenue_estimate = self.estimate_revenue(
                employee_count=business.employee_count,
                industry=business.industry,
                review_count=business.yelp_review_count or business.google_review_count,
            )

            if business.annual_revenue_estimate:
                business.revenue_source = "estimated"

        return business


class GeocodeEnricher:
    """
    Geographic enrichment using geocoding.

    Adds lat/lon coordinates for mapping and distance calculations.
    """

    def __init__(self):
        self._geocoder = None

    def _get_geocoder(self):
        """Lazy initialize geocoder."""
        if self._geocoder is None:
            from geopy.geocoders import Nominatim

            self._geocoder = Nominatim(user_agent="industry-deep-scan")
        return self._geocoder

    def geocode(self, address: str, city: str, state: str) -> tuple[Optional[float], Optional[float]]:
        """
        Get coordinates for an address.

        Returns (latitude, longitude) or (None, None) if not found.
        """
        try:
            geocoder = self._get_geocoder()
            full_address = f"{address}, {city}, {state}" if address else f"{city}, {state}"

            location = geocoder.geocode(full_address)

            if location:
                return location.latitude, location.longitude

        except Exception as e:
            logger.warning("Geocoding failed", address=full_address, error=str(e))

        return None, None

    def enrich_coordinates(self, business: Business) -> Business:
        """Add coordinates to business if not present."""
        if business.latitude and business.longitude:
            return business

        if business.city and business.state:
            lat, lon = self.geocode(
                business.address or "",
                business.city,
                business.state,
            )

            business.latitude = lat
            business.longitude = lon

        return business
