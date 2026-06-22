# config/companies.py
# Job-scout target companies for swiss_guard
#
# Candidate profile:
#   - UCSB Statistics & Data Science, ML Researcher at AFRL
#   - Focus: satellite imagery, synthetic-to-real data gap, agentic AI systems
#   - Active Secret clearance — a real differentiator for defense roles
#   - Target roles: Outcome Engineer, Forward Deployed Engineer,
#     Applied Scientist, ML Engineer, AI Engineer
#
# ATS types:
#   greenhouse  → JSON API via boards.greenhouse.io
#   lever       → JSON API via api.lever.co
#   ashby       → JSON API via jobs.ashbyhq.com
#   custom      → career portal with no first-party ATS. integrations/job_boards.py
#                 maps the site's host to the real recruiting platform behind it
#                 (Workday / Phenom / Eightfold sitemap / …) and falls back to a
#                 best-effort HTML scrape for unmapped hosts. search_url's host is
#                 what drives that routing — keep it accurate.
#   placeholder → Inactive or unconfirmed — logged and skipped

COMPANIES = [

    # ── Ashby ─────────────────────────────────────────────────────────────────
    {
        "name": "Onebrief",
        "ats": "ashby",
        "slug": "onebrief",
        "priority": "high",
        "target_roles": ["outcome engineer", "forward deployed"],
    },
    {
        "name": "Saronic",
        "ats": "ashby",
        "slug": "saronic",
        "priority": "high",
        "target_roles": [],  # monitor broadly
    },
    {
        "name": "OpenAI",
        "ats": "ashby",
        "slug": "openai",
        "priority": "medium",
        "target_roles": [],
    },
    {
        "name": "Applied Intuition",
        "ats": "ashby",
        "slug": "applied",
        "priority": "medium",
        "target_roles": [],
    },

    # ── Greenhouse ────────────────────────────────────────────────────────────
    {
        "name": "Anduril",
        "ats": "greenhouse",
        "slug": "andurilindustries",
        "priority": "high",
        "target_roles": ["machine learning", "forward deployed", "applied scientist",
                         "data scientist", "ml", "research engineer"],
    },
    {
        "name": "Vannevar Labs",
        "ats": "greenhouse",
        "slug": "vannevarlabs",
        "priority": "high",
        "target_roles": [],
    },
    {
        "name": "Skydio",
        "ats": "ashby",  # migrated off Greenhouse → Ashby board "skydio"
        "slug": "skydio",
        "priority": "high",
        "target_roles": [],
    },
    {
        "name": "Govini",
        "ats": "greenhouse",
        "slug": "govini",
        "priority": "high",
        "target_roles": [],
    },
    {
        "name": "Chaos Industries",
        "ats": "greenhouse",
        "slug": "chaosindustries",
        "priority": "high",
        "target_roles": [],
    },
    {
        "name": "Primer AI",
        "ats": "greenhouse",
        "slug": "primerai",
        "priority": "high",
        "target_roles": [],
    },
    {
        "name": "Synthetaic",
        "ats": "greenhouse",
        "slug": "synthetaic",
        "priority": "high",
        "target_roles": [],  # directly relevant — synthetic data + ISR
    },
    {
        "name": "Anthropic",
        "ats": "greenhouse",
        "slug": "anthropic",
        "priority": "medium",
        "target_roles": [],
    },
    {
        "name": "Scale AI",
        "ats": "greenhouse",
        "slug": "scaleai",
        "priority": "medium",
        "target_roles": [],
    },

    # ── Lever ─────────────────────────────────────────────────────────────────
    {
        "name": "Palantir",
        "ats": "lever",
        "slug": "palantir",
        "priority": "high",
        "target_roles": ["forward deployed", "applied scientist", "machine learning",
                         "data scientist", "ml", "research engineer"],
    },
    {
        "name": "Shield AI",
        "ats": "lever",
        "slug": "shieldai",
        "priority": "high",
        "target_roles": ["machine learning", "forward deployed", "applied scientist",
                         "data scientist", "ml", "research engineer"],
    },

    # ── Custom portals (HTML scraping via BeautifulSoup) ──────────────────────
    # Agent searches each URL with SEARCH_QUERY to filter relevant roles.
    # These sites change structure occasionally — if a site fails, it is
    # logged and skipped without crashing the agent.
    {
        "name": "Booz Allen Hamilton",
        "ats": "custom",
        "search_url": "https://careers.boozallen.com/jobs/search",
        "search_param": "q",
        "priority": "high",
        "target_roles": ["data scientist", "ml engineer", "applied scientist",
                         "machine learning"],
    },
    {
        "name": "MITRE",
        "ats": "custom",
        "search_url": "https://careers.mitre.org/us/en/search-results",
        "search_param": "keywords",
        "priority": "high",
        "target_roles": ["data scientist", "ml engineer", "applied scientist",
                         "machine learning"],
    },
    {
        "name": "CACI",
        "ats": "custom",
        "search_url": "https://searchcareers.caci.com/careers",
        "search_param": "q",
        "priority": "high",
        "target_roles": ["data scientist", "ml engineer", "applied scientist",
                         "machine learning"],
    },
    {
        "name": "Leidos",
        "ats": "custom",
        "search_url": "https://careers.leidos.com/pages/new-graduate-jobs",
        "search_param": "q",
        "priority": "high",
        "target_roles": ["data scientist", "ml engineer", "applied scientist",
                         "machine learning"],
    },
    {
        "name": "Northrop Grumman",
        "ats": "custom",
        "search_url": "https://jobs.northropgrumman.com/careers?domain=ngc.com&query=associate",
        "search_param": "q",
        "priority": "high",
        "target_roles": ["data scientist", "ml engineer", "applied scientist",
                         "machine learning"],
    },
    {
        "name": "Lockheed Martin",
        "ats": "custom",
        "search_url": "https://www.lockheedmartinjobs.com/search-jobs",
        "search_param": "q",
        "priority": "high",
        "target_roles": ["data scientist", "ml engineer", "applied scientist",
                         "machine learning"],
    },
    {
        "name": "SAIC",
        "ats": "custom",
        "search_url": "https://jobs.saic.com/pages/early-career",
        "search_param": "q",
        "priority": "medium",
        "target_roles": ["data scientist", "ml engineer", "applied scientist",
                         "machine learning"],
    },
    {
        "name": "L3Harris",
        "ats": "custom",
        "search_url": "https://careers.l3harris.com/en/search-jobs",
        "search_param": "q",
        "priority": "medium",
        "target_roles": ["data scientist", "ml engineer", "applied scientist",
                         "machine learning"],
    },
    {
        "name": "C3.ai",
        "ats": "custom",
        "search_url": "https://c3.ai/careers/",
        "search_param": "q",
        "priority": "medium",
        "target_roles": [],
    },

    # ── Placeholders ──────────────────────────────────────────────────────────
    {
        "name": "Rebellion Defense",
        "ats": "placeholder",
        "url": "https://rebelliondefense.com/careers",
        "priority": "high",
        "target_roles": ["applied scientist", "ml engineer", "data scientist"],
        "note": "No active roles as of June 2026 — check manually and reactivate",
    },
    {
        "name": "Maxar Intelligence",
        "ats": "placeholder",
        "url": "https://maxar.com/careers",
        "priority": "medium",
        "target_roles": [],
        "note": "Workday career site currently down — revisit when restored",
    },
    {
        "name": "Weights & Biases",
        "ats": "placeholder",
        "url": "https://coreweave.com/careers/weights-biases",
        "priority": "medium",
        "target_roles": [],
        "note": "Acquired by CoreWeave — verify correct career URL before activating",
    },
]

# ── Global relevance keywords ─────────────────────────────────────────────────
# Any job title or description matching one of these is surfaced.
# Covers both role types and domain terms relevant to this candidate's background.
RELEVANCE_KEYWORDS = [
    # Role types
    "machine learning",
    "data science",
    "applied scientist",
    "ml engineer",
    "ai engineer",
    "forward deployed",
    "outcome engineer",
    "research engineer",
    "data engineer",
    # Domain
    "artificial intelligence",
    "computer vision",
    "deep learning",
    "reinforcement learning",
    "nlp",
    "agentic",
    "autonomous",
    "geospatial",
    "synthetic data",
    "ISR",
    # Clearance-aware terms (candidate has active Secret). Use specific clearance
    # phrases — broad words like "cleared"/"mission" surfaced non-technical roles.
    "secret clearance",
    "ts/sci",
    "security clearance",
]

# ── Search query for custom portal scraping ───────────────────────────────────
# Appended to search_param when hitting custom career portals.
SEARCH_QUERY = "machine learning applied scientist AI engineer forward deployed"