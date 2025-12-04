# 🔍 Industry Deep Scan Engine

**AI-Powered Lead Generation for MCA Brokers**

An automated system that scans multiple data sources for business funding signals, uses LLM classification to identify high-intent prospects, and delivers actionable leads in real-time.

---

## 🎯 What This Does

Traditional MCA lead generation relies on aged UCC lists and dead leads. **Industry Deep Scan** monitors live signals across:

| Source | Signal Types |
|--------|--------------|
| 📰 **Local News** | Expansion announcements, layoffs, contracts, distress signals |
| ⭐ **Yelp Reviews** | Quality decline (indicates cash flow issues) |
| 💼 **LinkedIn** | Hiring freezes, layoffs, new contracts, growth signals |
| 🏢 **BBB Complaints** | Service issues (understaffing, quality problems) |
| 🏷️ **Business Listings** | Businesses for sale (need bridge funding) |
| ⚖️ **Court Records** | Tax liens, judgments (cash flow stress) |
| 🏗️ **Permit Filings** | Equipment permits, expansion plans |
| 📋 **SOS Filings** | New registrations, entity changes |

The engine uses **GPT-4/Claude** to classify signals into actionable categories:
- 🚨 **Cash Flow Stress** - Need capital NOW
- 📈 **Rapid Growth** - Scaling, need working capital
- ⚠️ **Distress + High Revenue** - Best MCA candidates
- 🔧 **Expansion Opportunity** - Equipment, new locations

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/your-org/industry-deep-scan.git
cd industry-deep-scan

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -e ".[dev]"

# Install Playwright browsers (for JavaScript-heavy sites)
playwright install chromium
```

### 2. Configuration

```bash
# Copy example config
cp .env.example .env

# Edit with your API keys
nano .env
```

**Minimum required:**
- `LLM_OPENAI_API_KEY` - For signal classification
- `SOURCE_YELP_API_KEY` - For review monitoring (free tier: 5000/day)

### 3. Initialize Database

```bash
deepscan init
```

### 4. Run Your First Scan

```bash
# Quick scan of news sources in CA and TX
deepscan scan --source news --states CA,TX

# View hot leads
deepscan leads --hot

# Full scan of all sources
deepscan scan --source all
```

### 5. Start the API Server

```bash
deepscan serve --port 8000
```

Visit `http://localhost:8000/docs` for the API documentation.

---

## 📊 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Industry Deep Scan Engine                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │  News RSS    │   │  Yelp API    │   │  BBB Scraper │        │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘        │
│         │                  │                   │                │
│         └──────────────────┴───────────────────┘                │
│                            │                                     │
│                     ┌──────▼──────┐                              │
│                     │ Raw Signals │                              │
│                     └──────┬──────┘                              │
│                            │                                     │
│                     ┌──────▼──────┐                              │
│                     │ LLM Classifier │  ◄── GPT-4 / Claude      │
│                     └──────┬──────┘                              │
│                            │                                     │
│                     ┌──────▼──────┐                              │
│                     │ Lead Scorer │                              │
│                     └──────┬──────┘                              │
│                            │                                     │
│         ┌──────────────────┼──────────────────┐                 │
│         │                  │                  │                  │
│  ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐           │
│  │  Database   │   │  REST API   │   │ Notifications │          │
│  │ (SQLite/PG) │   │  (FastAPI)  │   │ (Slack/Email) │          │
│  └─────────────┘   └─────────────┘   └──────────────┘           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🖥️ CLI Commands

```bash
# Scanning
deepscan scan --source news --states CA,TX,FL
deepscan scan --source yelp --industries restaurant,construction
deepscan scan --source all --parallel

# Viewing Leads
deepscan leads --hot                    # High-priority leads
deepscan leads --state CA --min-score 7
deepscan leads --industry construction

# Exporting
deepscan export --format csv --min-score 6 -o leads.csv
deepscan export --format xlsx --status new

# Statistics
deepscan stats --days 7

# Server
deepscan serve --port 8000 --reload     # Development
deepscan scheduler                       # Automated scanning
```

---

## 🔌 API Endpoints

### Leads
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/leads` | List leads with filtering |
| GET | `/leads/hot` | High-priority leads for immediate outreach |
| GET | `/leads/{id}` | Detailed lead info with signals |
| PATCH | `/leads/{id}` | Update lead status |

### Signals
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/signals` | Recent signals |

### Scans
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/scans` | Trigger a scan |

### Analytics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/analytics/stats` | Signal & lead statistics |

### Export
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/export/leads` | Export leads (JSON/CSV) |

**Authentication:** Include `X-API-Key` header with your API key.

---

## 📦 Data Sources Deep Dive

### News Sources
- **Google News RSS** - Free, scans for expansion, layoffs, contracts
- **Local Business Journals** - BizJournals network (40+ metro areas)

### Review Monitoring
- **Yelp Fusion API** - Rating decline detection, complaint keywords
- **Google Maps** - (Optional) Requires Playwright for JS rendering

### Business Intelligence
- **BBB** - Complaint volume, accreditation status
- **BizBuySell/BusinessBroker** - Businesses for sale

### Public Records
- **Court Records** - Tax liens, judgments (state-specific)
- **UCC Filings** - Existing financing (stacking detection)
- **Equipment Permits** - City permit portals
- **SOS Filings** - Entity registrations

---

## 🎯 Signal Classification

The LLM classifier analyzes each signal and returns:

```json
{
  "is_valid_signal": true,
  "confidence": 0.85,
  "signal_type": "cash_squeeze",
  "category": "cash_flow_stress",
  "priority": "high",
  "urgency_score": 8.5,
  "deal_potential_score": 7.0,
  "estimated_funding_need": "$75,000 - $150,000",
  "recommended_approach": "Lead with sympathy about review issues. Mention how quick capital can help them hire staff and recover ratings. Emphasize speed of funding.",
  "key_talking_points": [
    "Understaffing appears to be causing service issues",
    "Quick funding can help address immediate staffing needs",
    "Reviews mention wait times - more staff = better reviews"
  ]
}
```

---

## 📊 Lead Scoring

Leads are scored 0-10 based on:

| Factor | Weight |
|--------|--------|
| Signal category | Base score (5-9.5) |
| Industry | 1.0-1.3x multiplier |
| Revenue estimate | 0.7-1.2x multiplier |
| Signal recency | 0.7-1.3x multiplier |
| Multiple signals | +0.5-1.5 stacking bonus |
| LLM confidence | 0.5-1.0x modifier |

**Priority Mapping:**
- 9-10: 🚨 CRITICAL - Call immediately
- 7.5-9: ⚡ HIGH - Call within 24 hours
- 5.5-7.5: 📊 MEDIUM - Add to queue
- 3-5.5: ℹ️ LOW - Nurture list

---

## 🔔 Notifications

### Slack
- Instant alerts for critical/high priority leads
- Daily digest at configured time
- Rich formatting with business details

### Email (SendGrid)
- HTML-formatted lead alerts
- Daily digest summary
- Mobile-friendly design

### Webhook
- JSON payloads for CRM integration
- HMAC signature verification
- Adapters for HubSpot, Salesforce, Zoho

---

## 🏗️ Production Deployment

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install -e .
RUN playwright install chromium --with-deps

CMD ["deepscan", "serve", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose

```yaml
version: '3.8'
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - postgres
      - redis

  scheduler:
    build: .
    command: deepscan scheduler
    env_file: .env
    depends_on:
      - api

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: industry_deep_scan
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7

volumes:
  pgdata:
```

### Recommended Stack
- **Database:** PostgreSQL (for production scale)
- **Cache/Queue:** Redis (for Celery workers)
- **Reverse Proxy:** Nginx or Caddy
- **Process Manager:** systemd or Docker

---

## 💡 Best Practices

### 1. Rate Limiting
The system is configured conservatively. Adjust `SCRAPE_REQUESTS_PER_SECOND` based on your needs, but be respectful of source sites.

### 2. LLM Cost Control
- Default: $50/day limit
- Uses response caching to reduce repeated calls
- Rule-based fallback when limit exceeded

### 3. Data Quality
- Signals are deduplicated by content hash
- Business records merge by name + location
- Blacklist problematic businesses/domains

### 4. Compliance
- Respect robots.txt
- Don't store personal data beyond business contacts
- Follow Yelp, LinkedIn ToS for API usage

---

## 🛠️ Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/ tests/
ruff check src/ tests/

# Type checking
mypy src/
```

### Project Structure
```
industry-deep-scan/
├── src/industry_deep_scan/
│   ├── api/           # FastAPI routes
│   ├── classifiers/   # LLM & scoring
│   ├── notifications/ # Slack, email, webhook
│   ├── sources/       # Data source connectors
│   ├── utils/         # Helpers
│   ├── cli.py         # CLI commands
│   ├── config.py      # Settings
│   ├── database.py    # DB layer
│   ├── engine.py      # Main orchestrator
│   ├── models.py      # SQLAlchemy models
│   └── scheduler.py   # APScheduler jobs
├── tests/
├── data/              # SQLite database
├── .env               # Configuration
└── pyproject.toml     # Dependencies
```

---

## 📈 Roadmap

- [ ] LinkedIn Sales Navigator API integration
- [ ] Google Places API for reviews
- [ ] Automated outreach (email sequences)
- [ ] CRM native integrations (HubSpot, Salesforce)
- [ ] Dashboard UI (React/Next.js)
- [ ] Mobile app for sales reps
- [ ] ML model for deal probability

---

## 📄 License

Proprietary - TCG Brokerage

---

## 🤝 Support

- Issues: [GitHub Issues](https://github.com/your-org/industry-deep-scan/issues)
- Email: support@yourbrokerage.com

---

**Built to give your brokerage an edge. 🚀**
