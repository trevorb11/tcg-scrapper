"""
Text Processing Utilities
=========================

Functions for cleaning, extracting, and processing text data.
"""

import re
from typing import Optional
from urllib.parse import urlparse


def clean_text(text: str) -> str:
    """
    Clean text by removing extra whitespace and normalizing.
    """
    if not text:
        return ""

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Replace HTML entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")

    # Collapse whitespace
    text = " ".join(text.split())

    return text.strip()


def extract_phone_numbers(text: str) -> list[str]:
    """
    Extract phone numbers from text.

    Returns list of normalized phone numbers.
    """
    if not text:
        return []

    # Common phone patterns
    patterns = [
        r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",  # (XXX) XXX-XXXX or XXX-XXX-XXXX
        r"\d{3}[-.\s]\d{3}[-.\s]\d{4}",  # XXX-XXX-XXXX
        r"\d{10}",  # XXXXXXXXXX
        r"1[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}",  # 1-XXX-XXX-XXXX
    ]

    phones = []

    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            # Normalize to digits only
            digits = re.sub(r"\D", "", match)

            # Remove leading 1 if present
            if len(digits) == 11 and digits.startswith("1"):
                digits = digits[1:]

            if len(digits) == 10 and digits not in phones:
                phones.append(digits)

    return phones


def extract_emails(text: str) -> list[str]:
    """
    Extract email addresses from text.
    """
    if not text:
        return []

    # Email pattern
    pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

    emails = re.findall(pattern, text.lower())
    return list(set(emails))


def extract_urls(text: str) -> list[str]:
    """
    Extract URLs from text.
    """
    if not text:
        return []

    # URL pattern
    pattern = r"https?://[^\s<>\"')\]]+|www\.[^\s<>\"')\]]+"

    urls = re.findall(pattern, text)

    # Normalize
    normalized = []
    for url in urls:
        if not url.startswith("http"):
            url = "https://" + url
        # Remove trailing punctuation
        url = url.rstrip(".,;:!?")
        if url not in normalized:
            normalized.append(url)

    return normalized


def extract_money_amounts(text: str) -> list[tuple[float, str]]:
    """
    Extract monetary amounts from text.

    Returns list of (amount, original_string) tuples.
    """
    if not text:
        return []

    amounts = []

    # Patterns for different formats
    patterns = [
        r"\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(million|m|mil)?",  # $1,234.56 or $5M
        r"\$(\d+(?:\.\d+)?)\s*(billion|b|bil)?",  # $1.5 billion
        r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(?:dollars?|USD)",  # 1,234.56 dollars
    ]

    for pattern in patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            try:
                amount_str = match.group(1).replace(",", "")
                amount = float(amount_str)

                # Check for multiplier
                multiplier_str = match.group(2) if len(match.groups()) > 1 else None
                if multiplier_str:
                    multiplier_str = multiplier_str.lower()
                    if multiplier_str.startswith("b"):
                        amount *= 1_000_000_000
                    elif multiplier_str.startswith("m"):
                        amount *= 1_000_000

                amounts.append((amount, match.group(0)))
            except (ValueError, IndexError):
                continue

    return amounts


def extract_percentages(text: str) -> list[tuple[float, str]]:
    """
    Extract percentage values from text.

    Returns list of (value, original_string) tuples.
    """
    if not text:
        return []

    pattern = r"(\d+(?:\.\d+)?)\s*%"

    percentages = []
    matches = re.finditer(pattern, text)

    for match in matches:
        try:
            value = float(match.group(1))
            percentages.append((value, match.group(0)))
        except ValueError:
            continue

    return percentages


def extract_domain(url: str) -> Optional[str]:
    """
    Extract domain from URL.
    """
    if not url:
        return None

    try:
        if not url.startswith("http"):
            url = "https://" + url

        parsed = urlparse(url)
        domain = parsed.netloc

        # Remove www prefix
        if domain.startswith("www."):
            domain = domain[4:]

        return domain if domain else None

    except Exception:
        return None


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate text to max length, adding suffix if truncated.
    """
    if not text or len(text) <= max_length:
        return text or ""

    return text[: max_length - len(suffix)].rstrip() + suffix


def remove_html_tags(text: str) -> str:
    """
    Remove all HTML tags from text.
    """
    if not text:
        return ""

    return re.sub(r"<[^>]+>", "", text)


def extract_business_keywords(text: str) -> list[str]:
    """
    Extract business-relevant keywords from text.

    These are keywords that might indicate funding needs or business signals.
    """
    keywords = []

    # Growth indicators
    growth_terms = [
        "expansion", "expanding", "growth", "growing", "hiring",
        "new location", "opening soon", "grand opening", "franchise",
        "scaling", "increased demand",
    ]

    # Distress indicators
    distress_terms = [
        "closing", "shutdown", "layoff", "downsizing", "struggling",
        "bankruptcy", "foreclosure", "debt", "default", "lawsuit",
        "delinquent", "lien", "judgment",
    ]

    # Cash flow indicators
    cash_terms = [
        "cash flow", "working capital", "inventory", "equipment",
        "payroll", "financing", "loan", "credit line", "funding",
    ]

    text_lower = text.lower()

    for term in growth_terms:
        if term in text_lower:
            keywords.append(("growth", term))

    for term in distress_terms:
        if term in text_lower:
            keywords.append(("distress", term))

    for term in cash_terms:
        if term in text_lower:
            keywords.append(("cash_flow", term))

    return keywords


def parse_address_components(address: str) -> dict:
    """
    Parse address string into components.

    Returns dict with street, city, state, zip.
    """
    if not address:
        return {}

    result = {}

    # Try to extract zip code
    zip_match = re.search(r"(\d{5})(?:-\d{4})?$", address)
    if zip_match:
        result["zip"] = zip_match.group(1)
        address = address[: zip_match.start()].strip().rstrip(",")

    # Try to extract state (2 letter code)
    state_match = re.search(r",?\s*([A-Z]{2})\s*$", address, re.IGNORECASE)
    if state_match:
        result["state"] = state_match.group(1).upper()
        address = address[: state_match.start()].strip().rstrip(",")

    # Remaining could be city or street, city
    parts = address.split(",")
    if len(parts) >= 2:
        result["street"] = parts[0].strip()
        result["city"] = parts[-1].strip()
    elif len(parts) == 1:
        result["city"] = parts[0].strip()

    return result


def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two texts using word overlap.

    Returns a value between 0.0 and 1.0.
    """
    if not text1 or not text2:
        return 0.0

    # Tokenize
    words1 = set(re.findall(r"\w+", text1.lower()))
    words2 = set(re.findall(r"\w+", text2.lower()))

    if not words1 or not words2:
        return 0.0

    # Jaccard similarity
    intersection = words1.intersection(words2)
    union = words1.union(words2)

    return len(intersection) / len(union) if union else 0.0
