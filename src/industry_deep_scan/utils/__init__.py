"""
Utility Modules
===============

Helper functions and utilities for the Industry Deep Scan engine.
"""

from industry_deep_scan.utils.logging import setup_logging
from industry_deep_scan.utils.enrichment import BusinessEnricher, GeocodeEnricher
from industry_deep_scan.utils.dedup import (
    normalize_business_name,
    normalize_phone,
    normalize_address,
    content_hash,
    fuzzy_match_score,
    is_duplicate_business,
    find_duplicates_in_list,
    merge_business_records,
)
from industry_deep_scan.utils.text import (
    clean_text,
    extract_phone_numbers,
    extract_emails,
    extract_urls,
    extract_money_amounts,
    extract_percentages,
    extract_domain,
    truncate_text,
    remove_html_tags,
    extract_business_keywords,
    parse_address_components,
    calculate_text_similarity,
)
from industry_deep_scan.utils.validation import (
    is_valid_phone,
    is_valid_email,
    is_valid_state,
    is_valid_zip,
    is_valid_url,
    is_valid_ein,
    is_valid_website_domain,
    validate_business_name,
    validate_lead_data,
    sanitize_for_storage,
    is_blacklisted_domain,
    calculate_data_quality_score,
)

__all__ = [
    # Logging
    "setup_logging",
    # Enrichment
    "BusinessEnricher",
    "GeocodeEnricher",
    # Deduplication
    "normalize_business_name",
    "normalize_phone",
    "normalize_address",
    "content_hash",
    "fuzzy_match_score",
    "is_duplicate_business",
    "find_duplicates_in_list",
    "merge_business_records",
    # Text processing
    "clean_text",
    "extract_phone_numbers",
    "extract_emails",
    "extract_urls",
    "extract_money_amounts",
    "extract_percentages",
    "extract_domain",
    "truncate_text",
    "remove_html_tags",
    "extract_business_keywords",
    "parse_address_components",
    "calculate_text_similarity",
    # Validation
    "is_valid_phone",
    "is_valid_email",
    "is_valid_state",
    "is_valid_zip",
    "is_valid_url",
    "is_valid_ein",
    "is_valid_website_domain",
    "validate_business_name",
    "validate_lead_data",
    "sanitize_for_storage",
    "is_blacklisted_domain",
    "calculate_data_quality_score",
]
