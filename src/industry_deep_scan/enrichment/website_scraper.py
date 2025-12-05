"""
Website Contact Scraper
=======================

Extracts contact information (phone, email, address) from business websites.
Uses BeautifulSoup + regex patterns to find contact details.
"""

import asyncio
import re
import urllib.request
from typing import Optional
from urllib.parse import urljoin, urlparse

import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger()


class WebsiteContactScraper:
    """Scrapes business websites for contact information."""
    
    EMAIL_PATTERN = re.compile(
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Z|a-z]{2,7}',
        re.IGNORECASE
    )
    
    PHONE_PATTERN = re.compile(
        r'(?:\+1[\s.-]?)?\(?([0-9]{3})\)?[\s.-]?([0-9]{3})[\s.-]?([0-9]{4})',
        re.IGNORECASE
    )
    
    ADDRESS_PATTERN = re.compile(
        r'\d+\s+[\w\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct|Circle|Cir|Highway|Hwy|Suite|Ste|Floor|Fl)\.?\s*(?:#?\d+)?(?:,\s*)?(?:[\w\s]+,\s*)?[A-Z]{2}\s+\d{5}(?:-\d{4})?',
        re.IGNORECASE
    )
    
    CONTACT_PAGE_PATTERNS = [
        '/contact', '/contact-us', '/contactus', '/contact.html',
        '/about', '/about-us', '/aboutus', '/about.html',
        '/reach-us', '/get-in-touch', '/connect'
    ]
    
    EXCLUDE_EMAILS = {
        'example.com', 'domain.com', 'email.com', 'yoursite.com',
        'sentry.io', 'wix.com', 'squarespace.com', 'wordpress.com',
        'facebook.com', 'twitter.com', 'instagram.com', 'linkedin.com'
    }

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.logger = logger.bind(service="WebsiteContactScraper")

    async def scrape_contact_info(self, url: str) -> dict:
        """
        Scrape contact information from a business website.
        
        Args:
            url: Business website URL
            
        Returns:
            Dict with phone, email, and address if found
        """
        result = {
            "phone": None,
            "email": None,
            "address": None,
            "source_url": url
        }
        
        if not url:
            return result
            
        try:
            normalized_url = self._normalize_url(url)
            
            html = await self._fetch_page(normalized_url)
            if not html:
                return result
            
            soup = BeautifulSoup(html, 'html.parser')
            
            self._extract_from_page(soup, result)
            
            if not result["phone"] or not result["email"]:
                contact_url = self._find_contact_page(soup, normalized_url)
                if contact_url and contact_url != normalized_url:
                    contact_html = await self._fetch_page(contact_url)
                    if contact_html:
                        contact_soup = BeautifulSoup(contact_html, 'html.parser')
                        self._extract_from_page(contact_soup, result)
            
            self.logger.info(
                "Contact extraction complete",
                url=url,
                found_phone=bool(result["phone"]),
                found_email=bool(result["email"]),
                found_address=bool(result["address"])
            )
            
        except Exception as e:
            self.logger.warning("Error scraping website", url=url, error=str(e))
            
        return result

    def _normalize_url(self, url: str) -> str:
        """Ensure URL has proper protocol."""
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url

    async def _fetch_page(self, url: str) -> Optional[str]:
        """Fetch webpage content."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5'
            }
            req = urllib.request.Request(url, headers=headers)
            
            def do_fetch():
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read().decode('utf-8', errors='ignore')
            
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, do_fetch)
            
        except Exception as e:
            self.logger.debug("Failed to fetch page", url=url, error=str(e))
            return None

    def _extract_from_page(self, soup: BeautifulSoup, result: dict):
        """Extract contact info from a parsed page."""
        text = soup.get_text(separator=' ', strip=True)
        
        if not result["email"]:
            result["email"] = self._extract_email(soup, text)
        
        if not result["phone"]:
            result["phone"] = self._extract_phone(soup, text)
        
        if not result["address"]:
            result["address"] = self._extract_address(text)

    def _extract_email(self, soup: BeautifulSoup, text: str) -> Optional[str]:
        """Extract email from page."""
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if href.startswith('mailto:'):
                email = href[7:].split('?')[0].strip()
                if self._is_valid_email(email):
                    return email
        
        emails = self.EMAIL_PATTERN.findall(text)
        for email in emails:
            if self._is_valid_email(email):
                return email
        
        return None

    def _is_valid_email(self, email: str) -> bool:
        """Check if email is likely a real business email."""
        if not email or '@' not in email:
            return False
        
        domain = email.split('@')[1].lower()
        
        for exclude in self.EXCLUDE_EMAILS:
            if exclude in domain:
                return False
        
        local = email.split('@')[0].lower()
        if local in ['noreply', 'no-reply', 'donotreply', 'test', 'example', 'info@example']:
            return False
        
        return True

    def _extract_phone(self, soup: BeautifulSoup, text: str) -> Optional[str]:
        """Extract phone number from page."""
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if href.startswith('tel:'):
                phone = href[4:].strip()
                phone = re.sub(r'[^\d]', '', phone)
                if len(phone) >= 10:
                    return self._format_phone(phone)
        
        matches = self.PHONE_PATTERN.findall(text)
        for match in matches:
            phone = ''.join(match)
            if self._is_valid_phone(phone):
                return self._format_phone(phone)
        
        return None

    def _is_valid_phone(self, phone: str) -> bool:
        """Check if phone number looks valid."""
        digits = re.sub(r'[^\d]', '', phone)
        if len(digits) < 10 or len(digits) > 11:
            return False
        
        if digits.startswith('1') and len(digits) == 11:
            digits = digits[1:]
        
        if digits.startswith(('000', '111', '555', '800', '888', '877', '866', '855', '844', '833')):
            return True
        
        return True

    def _format_phone(self, phone: str) -> str:
        """Format phone number consistently."""
        digits = re.sub(r'[^\d]', '', phone)
        if digits.startswith('1') and len(digits) == 11:
            digits = digits[1:]
        
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        
        return phone

    def _extract_address(self, text: str) -> Optional[str]:
        """Extract address from page text."""
        matches = self.ADDRESS_PATTERN.findall(text)
        if matches:
            return matches[0].strip()
        return None

    def _find_contact_page(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Find link to contact/about page."""
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            text = link.get_text().lower()
            
            if any(pattern in href for pattern in self.CONTACT_PAGE_PATTERNS):
                return urljoin(base, link.get('href'))
            
            if 'contact' in text or 'about' in text or 'reach' in text:
                return urljoin(base, link.get('href'))
        
        return None


async def enrich_with_website_contact(url: str) -> dict:
    """
    Convenience function to extract contact info from a website.
    
    Args:
        url: Business website URL
        
    Returns:
        Dict with phone, email, address
    """
    scraper = WebsiteContactScraper()
    return await scraper.scrape_contact_info(url)
