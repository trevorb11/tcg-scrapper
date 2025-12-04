"""
Utility Tests
=============

Tests for deduplication, text processing, and validation utilities.
"""

import pytest

from industry_deep_scan.utils.dedup import (
    normalize_business_name,
    normalize_phone,
    normalize_address,
    content_hash,
    fuzzy_match_score,
    is_duplicate_business,
    merge_business_records,
)
from industry_deep_scan.utils.text import (
    clean_text,
    extract_phone_numbers,
    extract_emails,
    extract_urls,
    extract_money_amounts,
    extract_domain,
    truncate_text,
    extract_business_keywords,
    parse_address_components,
)
from industry_deep_scan.utils.validation import (
    is_valid_phone,
    is_valid_email,
    is_valid_state,
    is_valid_zip,
    is_valid_url,
    is_valid_ein,
    validate_business_name,
    validate_lead_data,
    calculate_data_quality_score,
)


class TestDeduplication:
    """Tests for deduplication utilities."""

    def test_normalize_business_name_basic(self):
        """Test basic name normalization."""
        assert normalize_business_name("ABC Company LLC") == "abc company"
        assert normalize_business_name("Test Business, Inc.") == "test business"
        assert normalize_business_name("THE BEST CORP") == "best"

    def test_normalize_business_name_punctuation(self):
        """Test punctuation removal."""
        assert normalize_business_name("Joe's Diner") == "joes diner"
        assert normalize_business_name("A & B Services") == "a b services"

    def test_normalize_phone(self):
        """Test phone normalization."""
        assert normalize_phone("(555) 123-4567") == "5551234567"
        assert normalize_phone("1-555-123-4567") == "5551234567"
        assert normalize_phone("555.123.4567") == "5551234567"
        assert normalize_phone("123") is None  # Too short

    def test_normalize_address(self):
        """Test address normalization."""
        assert "st" in normalize_address("123 Main Street")
        assert "ave" in normalize_address("456 Oak Avenue")
        assert "n" in normalize_address("North First Road")

    def test_content_hash_consistent(self):
        """Test content hashing is consistent."""
        text = "This is a test"
        hash1 = content_hash(text)
        hash2 = content_hash(text)
        assert hash1 == hash2

    def test_content_hash_different(self):
        """Test different content produces different hashes."""
        hash1 = content_hash("Text one")
        hash2 = content_hash("Text two")
        assert hash1 != hash2

    def test_fuzzy_match_score_exact(self):
        """Test exact match produces 1.0."""
        score = fuzzy_match_score("test", "test")
        assert score == 1.0

    def test_fuzzy_match_score_partial(self):
        """Test partial matches produce reasonable scores."""
        score = fuzzy_match_score("testing", "test")
        assert 0.5 < score < 1.0

    def test_is_duplicate_business_exact_match(self):
        """Test exact duplicates are detected."""
        is_dup, confidence = is_duplicate_business(
            name1="ABC Company",
            name2="ABC Company",
            phone1="5551234567",
            phone2="5551234567",
        )
        assert is_dup is True
        assert confidence > 0.9

    def test_is_duplicate_business_similar_names(self):
        """Test similar names are detected."""
        is_dup, confidence = is_duplicate_business(
            name1="ABC Company LLC",
            name2="ABC Company Inc",
        )
        assert is_dup is True
        assert confidence > 0.85

    def test_is_duplicate_business_different(self):
        """Test different businesses are not marked as duplicates."""
        is_dup, _ = is_duplicate_business(
            name1="ABC Company",
            name2="XYZ Services",
            phone1="5551234567",
            phone2="5559876543",
        )
        assert is_dup is False

    def test_merge_business_records(self):
        """Test merging business records."""
        primary = {"name": "ABC Company", "phone": "555-123-4567"}
        secondary = {"name": "ABC Co", "phone": "555-987-6543", "email": "abc@example.com"}

        merged = merge_business_records(primary, secondary)

        assert merged["name"] == "ABC Company"  # Primary wins
        assert merged["phone"] == "555-123-4567"  # Primary wins
        assert merged["email"] == "abc@example.com"  # Filled from secondary


class TestTextProcessing:
    """Tests for text processing utilities."""

    def test_clean_text_html(self):
        """Test HTML tag removal."""
        text = "<p>Hello <b>World</b></p>"
        cleaned = clean_text(text)
        assert "<" not in cleaned
        assert "Hello" in cleaned
        assert "World" in cleaned

    def test_clean_text_entities(self):
        """Test HTML entity replacement."""
        text = "A &amp; B &lt; C"
        cleaned = clean_text(text)
        assert "&" in cleaned
        assert "<" in cleaned

    def test_extract_phone_numbers(self):
        """Test phone number extraction."""
        text = "Call us at (555) 123-4567 or 555.987.6543"
        phones = extract_phone_numbers(text)
        assert len(phones) == 2
        assert "5551234567" in phones

    def test_extract_emails(self):
        """Test email extraction."""
        text = "Contact us at info@example.com or sales@test.org"
        emails = extract_emails(text)
        assert len(emails) == 2
        assert "info@example.com" in emails

    def test_extract_urls(self):
        """Test URL extraction."""
        text = "Visit https://example.com or www.test.org"
        urls = extract_urls(text)
        assert len(urls) == 2

    def test_extract_money_amounts(self):
        """Test money extraction."""
        text = "Revenue of $1,500,000 or $2.5 million"
        amounts = extract_money_amounts(text)
        assert len(amounts) >= 1

    def test_extract_domain(self):
        """Test domain extraction."""
        assert extract_domain("https://www.example.com/page") == "example.com"
        assert extract_domain("http://test.org") == "test.org"

    def test_truncate_text(self):
        """Test text truncation."""
        text = "This is a long text that needs truncation"
        truncated = truncate_text(text, 20)
        assert len(truncated) == 20
        assert truncated.endswith("...")

    def test_extract_business_keywords(self):
        """Test business keyword extraction."""
        text = "Company is expanding rapidly and hiring new employees"
        keywords = extract_business_keywords(text)
        categories = [k[0] for k in keywords]
        assert "growth" in categories

    def test_parse_address_components(self):
        """Test address parsing."""
        address = "123 Main St, Los Angeles, CA 90001"
        parts = parse_address_components(address)
        assert parts.get("zip") == "90001"
        assert parts.get("state") == "CA"


class TestValidation:
    """Tests for validation utilities."""

    def test_is_valid_phone(self):
        """Test phone validation."""
        assert is_valid_phone("(555) 123-4567") is True
        assert is_valid_phone("555-123-4567") is True
        assert is_valid_phone("123") is False
        assert is_valid_phone("(055) 123-4567") is False  # Invalid area code

    def test_is_valid_email(self):
        """Test email validation."""
        assert is_valid_email("test@example.com") is True
        assert is_valid_email("user.name@domain.org") is True
        assert is_valid_email("invalid") is False
        assert is_valid_email("@example.com") is False

    def test_is_valid_state(self):
        """Test state validation."""
        assert is_valid_state("CA") is True
        assert is_valid_state("TX") is True
        assert is_valid_state("XX") is False
        assert is_valid_state("") is False

    def test_is_valid_zip(self):
        """Test zip validation."""
        assert is_valid_zip("90210") is True
        assert is_valid_zip("90210-1234") is True
        assert is_valid_zip("9021") is False
        assert is_valid_zip("ABCDE") is False

    def test_is_valid_url(self):
        """Test URL validation."""
        assert is_valid_url("https://example.com") is True
        assert is_valid_url("http://test.org/page") is True
        assert is_valid_url("example.com") is False  # Missing protocol

    def test_is_valid_ein(self):
        """Test EIN validation."""
        assert is_valid_ein("12-3456789") is True
        assert is_valid_ein("123456789") is True
        assert is_valid_ein("00-0000000") is False  # Invalid prefix
        assert is_valid_ein("123") is False  # Too short

    def test_validate_business_name(self):
        """Test business name validation."""
        is_valid, _ = validate_business_name("ABC Company")
        assert is_valid is True

        is_valid, error = validate_business_name("")
        assert is_valid is False
        assert "required" in error.lower()

        is_valid, error = validate_business_name("Test Company")
        assert is_valid is False  # "Test" flagged as suspicious

    def test_validate_lead_data(self):
        """Test lead data validation."""
        # Valid data
        is_valid, errors = validate_lead_data({
            "name": "ABC Company",
            "phone": "555-123-4567",
            "email": "info@abc.com",
            "state": "CA",
        })
        assert is_valid is True
        assert len(errors) == 0

        # Invalid data
        is_valid, errors = validate_lead_data({
            "name": "",
            "phone": "123",
            "email": "invalid",
        })
        assert is_valid is False
        assert len(errors) > 0

    def test_calculate_data_quality_score(self):
        """Test data quality scoring."""
        # High quality record
        score = calculate_data_quality_score({
            "name": "ABC Company",
            "phone": "555-123-4567",
            "email": "info@abc.com",
            "city": "Los Angeles",
            "state": "CA",
            "zip": "90001",
            "website": "https://abc.com",
            "industry": "Construction",
        })
        assert score > 0.8

        # Low quality record
        score = calculate_data_quality_score({
            "name": "ABC",
        })
        assert score < 0.5
