"""
Deduplication Utilities
=======================

Functions for detecting and handling duplicate records.
Uses fuzzy matching and content hashing.
"""

import hashlib
import re
from difflib import SequenceMatcher
from typing import Optional

import structlog

logger = structlog.get_logger()


def normalize_business_name(name: str) -> str:
    """
    Normalize a business name for comparison.

    - Lowercase
    - Remove common suffixes (LLC, Inc, Corp, etc.)
    - Remove punctuation
    - Collapse whitespace
    """
    if not name:
        return ""

    # Lowercase
    normalized = name.lower()

    # Remove common business suffixes
    suffixes = [
        r"\b(llc|l\.l\.c\.?)\b",
        r"\b(inc|incorporated|inc\.)\b",
        r"\b(corp|corporation|corp\.)\b",
        r"\b(ltd|limited|ltd\.)\b",
        r"\b(co|company|co\.)\b",
        r"\b(pllc|p\.l\.l\.c\.?)\b",
        r"\b(lp|l\.p\.)\b",
        r"\bthe\b",
        r"\b&\b",
        r"\band\b",
    ]

    for suffix in suffixes:
        normalized = re.sub(suffix, "", normalized)

    # Remove punctuation
    normalized = re.sub(r"[^\w\s]", "", normalized)

    # Collapse whitespace
    normalized = " ".join(normalized.split())

    return normalized.strip()


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """
    Normalize phone number to digits only.
    """
    if not phone:
        return None

    # Extract digits
    digits = re.sub(r"\D", "", phone)

    # Handle country code
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) != 10:
        return None

    return digits


def normalize_address(address: str) -> str:
    """
    Normalize an address for comparison.
    """
    if not address:
        return ""

    normalized = address.lower()

    # Common abbreviations
    replacements = {
        r"\bstreet\b": "st",
        r"\bavenue\b": "ave",
        r"\bboulevard\b": "blvd",
        r"\bdrive\b": "dr",
        r"\broad\b": "rd",
        r"\blane\b": "ln",
        r"\bcourt\b": "ct",
        r"\bplace\b": "pl",
        r"\bsuite\b": "ste",
        r"\bapartment\b": "apt",
        r"\bnorth\b": "n",
        r"\bsouth\b": "s",
        r"\beast\b": "e",
        r"\bwest\b": "w",
        r"\bnorthwest\b": "nw",
        r"\bnortheast\b": "ne",
        r"\bsouthwest\b": "sw",
        r"\bsoutheast\b": "se",
    }

    for pattern, replacement in replacements.items():
        normalized = re.sub(pattern, replacement, normalized)

    # Remove punctuation
    normalized = re.sub(r"[^\w\s]", "", normalized)

    # Collapse whitespace
    normalized = " ".join(normalized.split())

    return normalized


def content_hash(text: str) -> str:
    """
    Generate a content hash for deduplication.
    """
    normalized = text.lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return hashlib.md5(normalized.encode()).hexdigest()


def fuzzy_match_score(str1: str, str2: str) -> float:
    """
    Calculate fuzzy match score between two strings.

    Returns a value between 0.0 and 1.0.
    """
    if not str1 or not str2:
        return 0.0

    return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()


def is_duplicate_business(
    name1: str,
    name2: str,
    phone1: Optional[str] = None,
    phone2: Optional[str] = None,
    address1: Optional[str] = None,
    address2: Optional[str] = None,
    city1: Optional[str] = None,
    city2: Optional[str] = None,
    threshold: float = 0.85,
) -> tuple[bool, float]:
    """
    Determine if two business records are duplicates.

    Returns (is_duplicate, confidence_score)

    The algorithm weighs multiple factors:
    - Business name similarity (primary)
    - Phone match (if available)
    - Address similarity (if available)
    - Same city
    """
    score = 0.0
    weights_used = 0.0

    # Name similarity (weight: 0.5)
    norm_name1 = normalize_business_name(name1)
    norm_name2 = normalize_business_name(name2)

    name_score = fuzzy_match_score(norm_name1, norm_name2)
    score += name_score * 0.5
    weights_used += 0.5

    # Phone match (weight: 0.3)
    if phone1 and phone2:
        norm_phone1 = normalize_phone(phone1)
        norm_phone2 = normalize_phone(phone2)

        if norm_phone1 and norm_phone2:
            phone_match = 1.0 if norm_phone1 == norm_phone2 else 0.0
            score += phone_match * 0.3
            weights_used += 0.3

    # Address similarity (weight: 0.15)
    if address1 and address2:
        norm_addr1 = normalize_address(address1)
        norm_addr2 = normalize_address(address2)

        addr_score = fuzzy_match_score(norm_addr1, norm_addr2)
        score += addr_score * 0.15
        weights_used += 0.15

    # City match (weight: 0.05)
    if city1 and city2:
        city_match = 1.0 if city1.lower() == city2.lower() else 0.0
        score += city_match * 0.05
        weights_used += 0.05

    # Normalize score by weights used
    if weights_used > 0:
        confidence = score / weights_used
    else:
        confidence = 0.0

    # Special case: exact phone match is a strong indicator
    if phone1 and phone2:
        if normalize_phone(phone1) == normalize_phone(phone2):
            confidence = max(confidence, 0.9)

    is_duplicate = confidence >= threshold

    return is_duplicate, confidence


def find_duplicates_in_list(
    businesses: list[dict],
    name_key: str = "name",
    phone_key: str = "phone",
    address_key: str = "address",
    city_key: str = "city",
    threshold: float = 0.85,
) -> list[tuple[int, int, float]]:
    """
    Find duplicate pairs in a list of business records.

    Returns list of (index1, index2, confidence_score) tuples.
    """
    duplicates = []

    for i in range(len(businesses)):
        for j in range(i + 1, len(businesses)):
            b1 = businesses[i]
            b2 = businesses[j]

            is_dup, confidence = is_duplicate_business(
                name1=b1.get(name_key, ""),
                name2=b2.get(name_key, ""),
                phone1=b1.get(phone_key),
                phone2=b2.get(phone_key),
                address1=b1.get(address_key),
                address2=b2.get(address_key),
                city1=b1.get(city_key),
                city2=b2.get(city_key),
                threshold=threshold,
            )

            if is_dup:
                duplicates.append((i, j, confidence))

    return duplicates


def merge_business_records(primary: dict, secondary: dict) -> dict:
    """
    Merge two business records, preferring non-empty values from primary.

    Fills in missing fields from secondary record.
    """
    merged = dict(primary)

    for key, value in secondary.items():
        if key not in merged or not merged[key]:
            merged[key] = value
        elif isinstance(value, list) and isinstance(merged[key], list):
            # Merge lists (e.g., signals)
            merged[key] = list(set(merged[key] + value))

    return merged
