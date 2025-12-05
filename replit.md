# Industry Deep Scan Engine

## Overview

**Industry Deep Scan** is an AI-powered lead generation system designed for MCA (Merchant Cash Advance) brokers. The application automatically scans multiple data sources for business funding signals, uses LLM classification to identify high-intent prospects, and delivers actionable leads in real-time.

The system monitors 8+ data sources including local news, Yelp reviews, LinkedIn, BBB complaints, business listings, court records, equipment permits, and Secretary of State filings. It uses GPT-4/Claude to classify raw signals into actionable categories like cash flow stress, rapid growth, distress with high revenue, and expansion opportunities.

Key capabilities include:
- Multi-source web scraping with rate limiting and anti-detection measures
- LLM-powered signal classification and lead scoring
- Real-time notification system (Slack, email, webhooks)
- Web dashboard for lead management
- REST API for CRM integration
- Automated scheduling for continuous monitoring

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Framework
- **Backend Framework**: FastAPI for REST API and web dashboard
- **Async Runtime**: Built on asyncio for concurrent scraping and API calls
- **CLI Interface**: Typer for command-line management
- **Templating**: Jinja2 with Tailwind CSS for browser-based dashboard

**Rationale**: FastAPI provides automatic OpenAPI documentation, async support, and excellent performance. The async architecture allows parallel scraping of multiple sources without blocking.

### Database Layer
- **ORM**: SQLAlchemy with async support (AsyncAttrs, AsyncSession)
- **Database Engines**: Supports both PostgreSQL (via asyncpg) and SQLite (via aiosqlite)
- **Models**: Comprehensive schema including Business, Signal, ScanJob, ContactAttempt, Blacklist, and Industry tables
- **Repository Pattern**: Abstracted data access through BusinessRepository and SignalRepository

**Rationale**: SQLAlchemy async provides database-agnostic abstraction while maintaining high performance. PostgreSQL for production deployments, SQLite for development/testing. Repository pattern isolates data access logic from business logic.

### Web Scraping Architecture
- **Base Connector Pattern**: Abstract `BaseSource` class defines common scraping interface
- **Multiple Strategies**: 
  - Standard HTTP scraping with aiohttp
  - API-based sources (APISource) for services with official APIs
  - Playwright-based scraping (PlaywrightSource) for JavaScript-heavy sites
- **Anti-Detection**: User agent rotation, rate limiting, retry logic with exponential backoff
- **Source Types**: News, reviews (Yelp/Google), LinkedIn, BBB, business listings, court records, permits

**Rationale**: Plugin architecture allows easy addition of new sources. Multiple scraping strategies handle different site technologies. Anti-detection measures prevent blocking during automated scraping.

### LLM Classification System
- **Provider Support**: OpenAI (GPT-4) and Anthropic (Claude) with fallback capability
- **Classification Pipeline**: Raw signals → LLM analysis → structured classification results
- **Output Structure**: Validates signals, extracts funding indicators, assigns priority/category, generates recommended pitch
- **Caching**: Uses content hashing to avoid re-classifying identical signals
- **Rate Limiting**: Implements retry logic with exponential backoff for API limits

**Rationale**: LLM provides nuanced understanding of business context that rule-based systems cannot match. Dual provider support ensures reliability. Caching reduces API costs and improves performance.

### Lead Scoring Engine
- **Multi-Factor Scoring**: Combines signal strength, industry multipliers, revenue estimates, geographic factors
- **Signal Stacking**: Multiple signals for the same business increase score
- **Configurable Weights**: Category scores, industry multipliers, and thresholds defined in settings
- **Dynamic Prioritization**: Recalculates scores as new signals arrive

**Rationale**: Holistic scoring helps brokers focus on highest-value opportunities. Configurable weights allow tuning based on performance data.

### Contact Enrichment System
- **Website Scraping**: Automatically extracts phone, email, and address from business websites
- **Google Places API**: Optional integration for reliable contact data lookup (requires API key)
- **Multi-Page Analysis**: Checks homepage plus /contact and /about pages for contact info
- **Pattern Recognition**: Uses regex patterns to find phone numbers, emails, and addresses
- **Automatic Integration**: Enrichment runs automatically during scan pipeline when contact info is missing

**Rationale**: MCA brokers need contact information to reach prospects. Website scraping provides free contact enrichment. Google Places API is available as an optional upgrade for higher reliability.

### Notification System
- **Multi-Channel**: Slack webhooks, SendGrid email, custom webhooks for CRM integration
- **Priority-Based**: Critical/high-priority leads trigger immediate notifications
- **Daily Digests**: Scheduled summary reports
- **Async Delivery**: Non-blocking notification dispatch

**Rationale**: Multiple channels ensure alerts reach team members. Webhooks enable integration with existing CRM/sales tools. Async design prevents notification delays from blocking core operations.

### Scheduling System
- **Scheduler**: APScheduler (AsyncIOScheduler) for automated scans
- **Configurable Intervals**: Different scan frequencies per source type
- **Cron Support**: Flexible scheduling with cron expressions
- **Graceful Shutdown**: Proper cleanup on application termination

**Rationale**: Automated scheduling enables continuous monitoring without manual intervention. Per-source intervals optimize resource usage and respect rate limits.

### Configuration Management
- **Settings Framework**: Pydantic Settings with environment variable support
- **Grouped Configuration**: Database, LLM, scraping, scoring, notifications, scheduler settings
- **Secret Handling**: SecretStr for sensitive values (API keys, passwords)
- **Environment-Based**: Development vs. production configurations

**Rationale**: Pydantic provides validation and type safety. Environment variables enable deployment flexibility. Grouped settings improve maintainability.

### Data Quality & Deduplication
- **Normalization**: Business name, phone, address normalization functions
- **Fuzzy Matching**: SequenceMatcher for detecting similar business records
- **Content Hashing**: SHA-256 hashing to detect duplicate signals
- **Validation**: Phone, email, URL, EIN, state code validation
- **Quality Scoring**: Multi-factor data quality assessment

**Rationale**: Deduplication prevents database bloat and duplicate notifications. Quality scoring helps prioritize clean, actionable leads.

## External Dependencies

### APIs and Services
- **OpenAI API**: GPT-4 for signal classification (primary LLM provider)
- **Anthropic API**: Claude as fallback LLM provider
- **Yelp Fusion API**: Business review data (5000 calls/day free tier)
- **SendGrid**: Transactional email delivery for notifications
- **Slack Webhooks**: Real-time team notifications

### Web Scraping Targets
- **News Sources**: Google News RSS, local news websites
- **Review Platforms**: Yelp, Google Reviews (via Playwright)
- **Business Data**: BizBuySell, BusinessBroker.net, LinkedIn (manual import)
- **Public Records**: BBB, court records, UCC filings, equipment permits, SOS filings
- **Note**: Many sources have varying ToS restrictions; designed for public data access only

### Python Packages
- **Web Framework**: FastAPI, Uvicorn
- **Async Runtime**: aiohttp, asyncio, asyncpg (PostgreSQL), aiosqlite (SQLite)
- **Database**: SQLAlchemy (async), Alembic (migrations)
- **Scraping**: BeautifulSoup4, Playwright, feedparser
- **LLM**: OpenAI SDK, Anthropic SDK
- **Utilities**: structlog (logging), tenacity (retry), Pydantic (validation)
- **CLI**: Typer, Rich (terminal formatting)
- **Scheduling**: APScheduler
- **Templating**: Jinja2

### Infrastructure
- **Database**: PostgreSQL (production) or SQLite (development)
- **Web Server**: Uvicorn ASGI server
- **Browser Automation**: Chromium (via Playwright) for JavaScript-rendered sites

### Third-Party Integrations (Optional)
- **CRM Systems**: Webhook-based integration with Salesforce, HubSpot, Zoho
- **Data Enrichment**: Support for Clay.com, PhantomBuster for enhanced data gathering
- **LinkedIn**: Sales Navigator CSV import (manual), potential API integration for partners