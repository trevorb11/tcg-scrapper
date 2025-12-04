"""
Validation Utilities
====================

Functions for validating business data and input.
"""

import re
from typing import Optional


# Valid US state codes
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "VI", "GU", "AS", "MP",
}


def is_valid_phone(phone: str) -> bool:
    """
    Validate a US phone number.
    """
    if not phone:
        return False

    # Extract digits
    digits = re.sub(r"\D", "", phone)

    # Handle country code
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    if len(digits) != 10:
        return False

    # Check area code (first digit can't be 0 or 1)
    if digits[0] in "01":
        return False

    # Check exchange (4th digit can't be 0 or 1)
    if digits[3] in "01":
        return False

    return True


def is_valid_email(email: str) -> bool:
    """
    Validate an email address.
    """
    if not email:
        return False

    # Basic email pattern
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def is_valid_state(state: str) -> bool:
    """
    Validate a US state code.
    """
    if not state:
        return False

    return state.upper() in US_STATES


def is_valid_zip(zip_code: str) -> bool:
    """
    Validate a US zip code.
    """
    if not zip_code:
        return False

    # 5 digits or 5+4 format
    pattern = r"^\d{5}(-\d{4})?$"
    return bool(re.match(pattern, zip_code))


def is_valid_url(url: str) -> bool:
    """
    Validate a URL.
    """
    if not url:
        return False

    # Basic URL pattern
    pattern = r"^https?://[^\s<>\"']+$"
    return bool(re.match(pattern, url, re.IGNORECASE))


def is_valid_ein(ein: str) -> bool:
    """
    Validate an Employer Identification Number (EIN).

    Format: XX-XXXXXXX
    """
    if not ein:
        return False

    # Remove hyphens
    digits = re.sub(r"[-\s]", "", ein)

    if len(digits) != 9:
        return False

    if not digits.isdigit():
        return False

    # First two digits must be a valid prefix (01-06, 10-16, 20-27, etc.)
    prefix = int(digits[:2])
    valid_prefixes = list(range(1, 7)) + list(range(10, 17)) + list(range(20, 28)) + \
                     list(range(30, 40)) + list(range(40, 49)) + list(range(50, 60)) + \
                     list(range(60, 69)) + list(range(70, 78)) + list(range(80, 89)) + \
                     list(range(90, 100))

    return prefix in valid_prefixes


def is_valid_website_domain(domain: str) -> bool:
    """
    Validate a website domain.
    """
    if not domain:
        return False

    # Remove protocol if present
    if "://" in domain:
        domain = domain.split("://")[1]

    # Remove path if present
    domain = domain.split("/")[0]

    # Remove www prefix
    if domain.startswith("www."):
        domain = domain[4:]

    # Basic domain pattern
    pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z]{2,})+$"
    return bool(re.match(pattern, domain))


def validate_business_name(name: str) -> tuple[bool, Optional[str]]:
    """
    Validate a business name.

    Returns (is_valid, error_message)
    """
    if not name:
        return False, "Business name is required"

    if len(name) < 2:
        return False, "Business name is too short"

    if len(name) > 200:
        return False, "Business name is too long"

    # Check for invalid characters
    if re.search(r"[<>{}[\]\\]", name):
        return False, "Business name contains invalid characters"

    # Check for suspicious patterns
    if re.search(r"(test|example|sample|xxx|000|fake)", name, re.IGNORECASE):
        return False, "Business name appears to be a test value"

    return True, None


def validate_lead_data(data: dict) -> tuple[bool, list[str]]:
    """
    Validate lead data for completeness and correctness.

    Returns (is_valid, list_of_errors)
    """
    errors = []

    # Required fields
    if not data.get("name"):
        errors.append("Business name is required")
    else:
        is_valid, error = validate_business_name(data["name"])
        if not is_valid:
            errors.append(error)

    # Validate phone if provided
    if data.get("phone"):
        if not is_valid_phone(data["phone"]):
            errors.append("Invalid phone number format")

    # Validate email if provided
    if data.get("email"):
        if not is_valid_email(data["email"]):
            errors.append("Invalid email format")

    # Validate state if provided
    if data.get("state"):
        if not is_valid_state(data["state"]):
            errors.append("Invalid state code")

    # Validate zip if provided
    if data.get("zip"):
        if not is_valid_zip(data["zip"]):
            errors.append("Invalid zip code format")

    # Validate website if provided
    if data.get("website"):
        if not is_valid_url(data["website"]) and not is_valid_website_domain(data["website"]):
            errors.append("Invalid website URL")

    return len(errors) == 0, errors


def sanitize_for_storage(text: str) -> str:
    """
    Sanitize text for safe storage.

    Removes potentially dangerous characters while preserving content.
    """
    if not text:
        return ""

    # Remove null bytes
    text = text.replace("\x00", "")

    # Remove other control characters except newlines and tabs
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Limit length
    if len(text) > 10000:
        text = text[:10000]

    return text


def is_blacklisted_domain(domain: str, blacklist: list[str]) -> bool:
    """
    Check if a domain is in the blacklist.

    Handles both exact matches and wildcard patterns.
    """
    if not domain or not blacklist:
        return False

    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[4:]

    for pattern in blacklist:
        pattern = pattern.lower()

        if pattern.startswith("*."):
            # Wildcard match - check if domain ends with pattern suffix
            suffix = pattern[2:]
            if domain == suffix or domain.endswith("." + suffix):
                return True
        else:
            # Exact match
            if domain == pattern:
                return True

    return False


def calculate_data_quality_score(data: dict) -> float:
    """
    Calculate a data quality score for a lead record.

    Returns a score from 0.0 to 1.0.
    """
    total_fields = 0
    valid_fields = 0

    # Required fields
    required_fields = ["name"]
    for field in required_fields:
        total_fields += 1
        if data.get(field):
            valid_fields += 1

    # Contact info (at least one should be present)
    contact_fields = ["phone", "email"]
    has_contact = False
    for field in contact_fields:
        total_fields += 0.5
        if data.get(field):
            # Validate the field
            if field == "phone" and is_valid_phone(data[field]):
                valid_fields += 0.5
                has_contact = True
            elif field == "email" and is_valid_email(data[field]):
                valid_fields += 0.5
                has_contact = True

    # Location info
    location_fields = ["city", "state", "zip", "address"]
    for field in location_fields:
        total_fields += 0.25
        value = data.get(field)
        if value:
            if field == "state" and is_valid_state(value):
                valid_fields += 0.25
            elif field == "zip" and is_valid_zip(value):
                valid_fields += 0.25
            elif field in ["city", "address"] and len(value) > 1:
                valid_fields += 0.25

    # Additional valuable fields
    bonus_fields = ["website", "industry", "employee_count", "annual_revenue"]
    for field in bonus_fields:
        total_fields += 0.25
        if data.get(field):
            valid_fields += 0.25

    if total_fields == 0:
        return 0.0

    return min(valid_fields / total_fields, 1.0)
