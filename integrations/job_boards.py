"""
job_boards.py — job listing fetchers for the job-scout agent.

One fetcher per ATS (applicant tracking system) type. Each takes a company
config dict (see config/companies.py) and returns a normalized list of jobs:

    [{"job_id": str, "title": str, "url": str, "company": str, "source": str,
      "description": str}]

`description` is bounded plain text (see _html_to_text / _MAX_DESC_CHARS). The
JSON ATS fetchers (greenhouse/lever/ashby) populate it from the posting body;
the list-only sources (workday/phenom) and the HTML-scrape fallback have no full
body available and return "".

ATS types and their public endpoints:
  greenhouse  → boards-api.greenhouse.io JSON board API
  lever       → api.lever.co postings JSON API
  ashby       → api.ashbyhq.com posting-api JSON
  custom      → see below
  placeholder → inactive/unconfirmed — logged and skipped

The "custom" path (career portals with no first-party ATS) is a VENDOR-DETECTING
DISPATCHER. The big defense primes and similar sites run on recruiting platforms
(Workday, Phenom, Greenhouse-behind-a-vanity-domain, …) that render their job
lists in JavaScript — so a naive HTML scrape sees only nav chrome, never jobs
(verified live). Instead we map the site's host to its real JSON API in
_CUSTOM_VENDORS and call that. companies.py only knows ats="custom"; the
reverse-engineered endpoint details (Workday tenant/site, Greenhouse slug, …)
live HERE, which is where that integration detail belongs — so companies.py
never has to change. Hosts we haven't mapped fall back to the best-effort HTML
scrape (which safely returns [] for JS-rendered sites).

Error policy:
  - The ATS API fetchers (greenhouse/lever/ashby) raise on a hard failure
    (network error, non-2xx, unparseable body). The agent wraps each company in
    a try/except so one dead board logs to agent-logs and the run continues.
  - The custom dispatcher NEVER raises: a flaky portal or a vendor API change
    must not look like an outage. It logs and returns [].

SECURITY: job titles come from external boards and are forwarded to an LLM by
the agent. They are treated as untrusted data there — see job_scout.py.
"""

import re
import time
import html as _html
import hashlib
from typing import List, Dict, Optional
from urllib.parse import urlencode, urljoin, quote_plus, urlparse, unquote

import requests
from bs4 import BeautifulSoup

# Network timeout for every outbound request (seconds).
_TIMEOUT = 20

# Cap on the plain-text job description we keep per posting. Descriptions are
# forwarded to Claude (which must read the requirements to catch degree / years-
# of-experience hard rejects), so we bound the size to keep each evaluation call
# within budget. The required-qualifications section reliably lands well inside
# this window; an unbounded HTML body would blow up token cost.
_MAX_DESC_CHARS = 5000


def _html_to_text(raw: Optional[str]) -> str:
    """
    Flatten a job-description HTML blob to bounded plain text for Claude.

    Greenhouse returns its `content` as HTML-ENTITY-ENCODED HTML (e.g.
    "&lt;p&gt;"), so we unescape once before stripping tags; for already-decoded
    HTML (Lever/Ashby) the unescape is a harmless no-op. Whitespace is collapsed
    and the result is truncated to _MAX_DESC_CHARS. Returns "" for empty input.
    """
    if not raw:
        return ""
    text = BeautifulSoup(_html.unescape(raw), "html.parser").get_text(
        separator=" ", strip=True
    )
    return re.sub(r"\s+", " ", text).strip()[:_MAX_DESC_CHARS]

# Politeness pause between custom-portal HTML scrapes so we don't hammer a site
# (and look less like a bot). Only applied to the HTML-scrape fallback path.
_CUSTOM_SCRAPE_DELAY_S = 2

# Hard cap on jobs pulled from a single paginated vendor source. The agent's
# relevance filter narrows these down anyway; this just bounds cost/latency on
# huge boards (some primes list thousands of roles).
_VENDOR_MAX_JOBS = 200

# A real browser User-Agent. Career portals routinely 403 the python-requests
# default UA; this makes the scrape look like an ordinary browser visit.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ── Greenhouse ───────────────────────────────────────────────────────────────

def _greenhouse_jobs(slug: str, company_name: str) -> List[Dict]:
    """
    Core Greenhouse fetch by board slug — shared by the greenhouse ATS fetcher
    and the custom dispatcher (some sites, e.g. C3.ai, are Greenhouse behind a
    vanity careers domain).

    NB: the public JSON lives on `boards-api.greenhouse.io/v1/boards/...`. The
    bare `boards.greenhouse.io/{slug}/jobs` URL is the HTML board and 404s for
    the JSON request — verified live against every slug in companies.py.
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    # The documented shape is a dict with a "jobs" key; tolerate a bare list too.
    jobs = data.get("jobs", []) if isinstance(data, dict) else data

    out: List[Dict] = []
    for j in jobs:
        job_id = j.get("id")
        title = (j.get("title") or "").strip()
        link = j.get("absolute_url")
        if job_id is None or not title or not link:
            continue
        out.append({
            "job_id": str(job_id),
            "title": title,
            "url": link,
            "company": company_name,
            "source": "greenhouse",
            # `?content=true` (set on the request URL) returns the full posting
            # body here; Claude needs it to catch degree / years-of-experience
            # requirements that never appear in the title.
            "description": _html_to_text(j.get("content")),
        })
    return out


def fetch_greenhouse(company: Dict) -> List[Dict]:
    """Greenhouse ATS fetcher. Raises on HTTP/parse failure."""
    return _greenhouse_jobs(company["slug"], company["name"])


# ── Lever ────────────────────────────────────────────────────────────────────

def fetch_lever(company: Dict) -> List[Dict]:
    """
    Lever postings API:
        GET https://api.lever.co/v0/postings/{slug}?mode=json

    The body is a JSON list of postings. Each carries `id`, `text` (the title)
    and `hostedUrl`. Raises on HTTP/parse failure.
    """
    slug = company["slug"]
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    postings = resp.json()
    if not isinstance(postings, list):
        postings = postings.get("postings", []) if isinstance(postings, dict) else []

    out: List[Dict] = []
    for j in postings:
        job_id = j.get("id")
        title = (j.get("text") or "").strip()
        link = j.get("hostedUrl")
        if not job_id or not title or not link:
            continue
        # Lever splits the posting: `descriptionPlain` is the intro prose, while
        # the REQUIREMENTS (the "X+ years", "MS required" bullets we hard-reject
        # on) live separately in `lists`. Stitch both together so Claude sees the
        # qualifications, not just the pitch.
        desc = j.get("descriptionPlain") or _html_to_text(j.get("description"))
        for lst in j.get("lists") or []:
            heading = (lst.get("text") or "").strip()
            bullets = _html_to_text(lst.get("content"))
            if heading or bullets:
                desc = f"{desc}\n{heading}: {bullets}".strip()
        out.append({
            "job_id": str(job_id),
            "title": title,
            "url": link,
            "company": company["name"],
            "source": "lever",
            "description": desc[:_MAX_DESC_CHARS],
        })
    return out


# ── Ashby ────────────────────────────────────────────────────────────────────

def fetch_ashby(company: Dict) -> List[Dict]:
    """
    Ashby public posting API:
        GET https://api.ashbyhq.com/posting-api/job-board/{slug}

    NB: the `jobs.ashbyhq.com/{slug}/json` URL serves HTML, not JSON (verified
    live) — the posting-api host is the real JSON board. The body is
    {"jobs": [...], "apiVersion": ...}; each posting carries `id`, `title`,
    `jobUrl`, `applyUrl` and an `isListed` flag. (We tolerate a `jobPostings`
    key too in case a board uses the older shape.) Raises on HTTP/parse failure.
    """
    slug = company["slug"]
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    postings = []
    if isinstance(data, dict):
        postings = data.get("jobs") or data.get("jobPostings") or []
    elif isinstance(data, list):
        postings = data

    out: List[Dict] = []
    for j in postings:
        # Skip postings Ashby marks as unlisted — they're not public openings.
        if j.get("isListed") is False:
            continue
        job_id = j.get("id")
        title = (j.get("title") or "").strip()
        link = j.get("jobUrl") or j.get("applyUrl")
        if not job_id or not title or not link:
            continue
        out.append({
            "job_id": str(job_id),
            "title": title,
            "url": link,
            "company": company["name"],
            "source": "ashby",
            # Ashby's posting-api carries the full body; prefer its plain-text
            # form, falling back to stripping the HTML variant.
            "description": (
                j.get("descriptionPlain")
                or _html_to_text(j.get("description") or j.get("descriptionHtml"))
            )[:_MAX_DESC_CHARS],
        })
    return out


# ── Vendor JSON APIs behind "custom" career portals ──────────────────────────

# Focused role terms we fan out over, one search per term, unioning the results.
# Several vendor surfaces choke on a single broad multi-term query: Workday's
# `searchText` ANDs its words, so the agent's full SEARCH_QUERY ("machine
# learning applied scientist AI engineer forward deployed") matches zero
# postings; the Phenom GST `?k=` HTML search and the Eightfold sitemap
# slug-match behave the same way. Each term here is loose enough to return a
# useful set on its own, and the agent's relevance filter narrows the union
# down afterward. Shared by fetch_workday, fetch_gst_html and
# fetch_eightfold_sitemap.
_ROLE_QUERY_TERMS = [
    "machine learning", "data scientist", "applied scientist",
    "ai engineer", "computer vision", "deep learning", "forward deployed",
]
# Cap per term (2 pages of 20) so a loose term like "ai engineer" (1000s of
# hits) can't blow up the run; the overall union is still capped at
# _VENDOR_MAX_JOBS.
_WORKDAY_PER_TERM_MAX = 40


def fetch_workday(company_name: str, cfg: Dict, search_query: str) -> List[Dict]:
    """
    Workday CXS search API:
        POST https://{host}/wday/cxs/{tenant}/{site}/jobs
        body: {"appliedFacets":{}, "limit":N, "offset":M, "searchText": "..."}

    Returns {"total": int, "jobPostings": [{title, externalPath, ...}]}. The
    public job URL is https://{host}/{site}{externalPath}.

    `search_query` is intentionally ignored — Workday ANDs search words, so we
    union per-term searches (see _ROLE_QUERY_TERMS) instead. Deduped by
    externalPath, capped at _VENDOR_MAX_JOBS. Raises on HTTP/parse failure
    (caught by fetch_custom).
    """
    host, tenant, site = cfg["host"], cfg["tenant"], cfg["site"]
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"

    by_id: Dict[str, Dict] = {}  # externalPath → job, dedupes across terms
    headers = {**_BROWSER_HEADERS, "Content-Type": "application/json",
               "Accept": "application/json"}

    for term in _ROLE_QUERY_TERMS:
        offset, page = 0, 20
        while offset < _WORKDAY_PER_TERM_MAX and len(by_id) < _VENDOR_MAX_JOBS:
            resp = requests.post(
                url, headers=headers,
                json={"appliedFacets": {}, "limit": page, "offset": offset,
                      "searchText": term},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            postings = data.get("jobPostings", [])
            if not postings:
                break

            for j in postings:
                title = (j.get("title") or "").strip()
                ext = j.get("externalPath")
                if not title or not ext or ext in by_id:
                    continue
                by_id[ext] = {
                    # externalPath is unique + stable per posting → a good job_id.
                    "job_id": ext,
                    "title": title,
                    "url": f"https://{host}/{site}{ext}",
                    "company": company_name,
                    "source": "workday",
                    # The CXS list endpoint returns no full body; left empty so
                    # the job schema stays uniform.
                    "description": "",
                }

            offset += page
            if offset >= data.get("total", 0):
                break
        if len(by_id) >= _VENDOR_MAX_JOBS:
            break

    return list(by_id.values())


def fetch_phenom(company_name: str, cfg: Dict, search_query: str) -> List[Dict]:
    """
    Phenom People search widget API:
        POST https://{host}/widgets  (ddoKey=refineSearch)

    Returns {"refineSearch": {"totalHits": int, "data": {"jobs": [...]}}}; each
    job carries `title`, `jobId`, `jobSeqNo`, `applyUrl`. The public job URL is
    https://{host}/{locale}/job/{jobSeqNo}. Paginated; capped at
    _VENDOR_MAX_JOBS. Raises on HTTP/parse failure (caught by fetch_custom).
    """
    host = cfg["host"]
    locale = cfg.get("locale", "us/en")
    url = f"https://{host}/widgets"

    out: List[Dict] = []
    frm, size = 0, 100
    while frm < _VENDOR_MAX_JOBS:
        resp = requests.post(
            url,
            headers={**_BROWSER_HEADERS, "Content-Type": "application/json",
                     "Accept": "application/json"},
            json={
                "lang": "en_us", "deviceType": "desktop", "country": "us",
                "pageName": "search-results", "ddoKey": "refineSearch",
                "sortBy": "", "subsearch": "", "from": frm, "jobs": True,
                "counts": True, "all_fields": [], "size": size,
                "keywords": search_query, "global": True,
                "selected_fields": {}, "locationData": {},
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        rs = resp.json().get("refineSearch", {})
        jobs = (rs.get("data") or {}).get("jobs", [])
        if not jobs:
            break

        for j in jobs:
            title = (j.get("title") or "").strip()
            seq = j.get("jobSeqNo")
            job_id = j.get("jobId") or seq
            if not title or not job_id:
                continue
            link = (
                f"https://{host}/{locale}/job/{seq}" if seq
                else j.get("applyUrl")
            )
            if not link:
                continue
            out.append({
                "job_id": str(job_id),
                "title": title,
                "url": link,
                "company": company_name,
                "source": "phenom",
                # The search widget returns only a teaser, not the full body.
                "description": _html_to_text(j.get("descriptionTeaser")),
            })

        total = rs.get("totalHits", 0)
        frm += size
        if frm >= total:
            break
    return out


# Pages to pull per role term from a Phenom GST HTML search (15 results/page).
# Bounds cost: 7 terms × 2 pages × 15 = up to ~210 candidates before the overall
# _VENDOR_MAX_JOBS cap and the agent's relevance filter trim the union.
_GST_PAGES_PER_TERM = 2


def fetch_gst_html(company_name: str, cfg: Dict, search_query: str) -> List[Dict]:
    """
    Phenom "GST"-theme career site (Lockheed Martin, L3Harris).

    Unlike the MITRE Phenom build, these sites SERVER-RENDER their search results
    into the page, and the `?k=` keyword + `?p=` page params are honored in the
    HTML (verified live) — so no widget API is needed. The widget `/widgets`
    endpoint is, in fact, 404 here. We fan out one search per role term (a single
    broad query over-narrows, same as Workday) and union the cards.

    The real, keyword-filtered hits live in `<section id="search-results-list">`;
    the page also carries a fixed "related jobs" widget of `data-job-id` anchors
    that ignores the query, so we scope to that section to avoid pulling its
    irrelevant cards into every term. Each result card is
    `<a data-job-id href="/.../job/...">` carrying the title in a `.job-title`
    span (Lockheed) or an `<h2>` (L3Harris); we try both. `search_query` is
    ignored in favour of _ROLE_QUERY_TERMS. Deduped by data-job-id, capped at
    _VENDOR_MAX_JOBS. Raises on HTTP failure (caught by fetch_custom).
    """
    host = cfg["host"]
    search_url = f"https://{host}{cfg['search_path']}"

    by_id: Dict[str, Dict] = {}  # data-job-id → job, dedupes across terms/pages
    for term in _ROLE_QUERY_TERMS:
        for page in range(1, _GST_PAGES_PER_TERM + 1):
            resp = requests.get(
                search_url, headers=_BROWSER_HEADERS,
                params={"k": term, "p": page}, timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Scope to the real results list; fall back to the whole page if the
            # container id ever changes (then dedup + role-relevance still apply).
            results = soup.select_one("#search-results-list") or soup
            cards = [a for a in results.select("a[data-job-id]")
                     if "/job/" in (a.get("href") or "")]
            if not cards:
                break  # no more pages for this term

            for a in cards:
                jid = a.get("data-job-id")
                node = a.select_one(".job-title") or a.find(["h2", "h3"])
                title = (node.get_text(strip=True) if node
                         else a.get("data-custom-label") or "").strip()
                if not jid or not title or jid in by_id:
                    continue
                by_id[jid] = {
                    "job_id": str(jid),
                    "title": title,
                    "url": urljoin(search_url, a["href"]),
                    "company": company_name,
                    "source": "phenom_gst",
                    # The listing card carries no full body; left empty so the
                    # job schema stays uniform with the other list-only sources.
                    "description": "",
                }
                if len(by_id) >= _VENDOR_MAX_JOBS:
                    return list(by_id.values())
            time.sleep(1)  # be polite between page fetches
    return list(by_id.values())


# Eightfold "PCSX" job URLs look like /careers/job/{numeric-id}-{title-location-slug}.
_EIGHTFOLD_JOB_RE = re.compile(r"/careers/job/(\d+)-([^/?#]+)")


def _deslugify(slug: str) -> str:
    """
    Turn a hyphenated URL slug into a human-readable, title-cased string. The
    sitemap slugs are percent-encoded (e.g. "%E2%80%93" for an en-dash), so we
    URL-decode first.
    """
    text = unquote(slug).replace("-", " ")
    return re.sub(r"\s+", " ", text).strip().title()


def fetch_eightfold_sitemap(company_name: str, cfg: Dict, search_query: str) -> List[Dict]:
    """
    Eightfold AI "PCSX" career site (CACI, Northrop Grumman).

    These are JavaScript SPAs whose position API (`/api/apply/v2/jobs`) is locked
    ("Not authorized for PCSX") and whose `/api/career_hub/search` requires a
    candidate login — so neither the JSON API nor a static HTML scrape yields
    jobs. The escape hatch is the PUBLIC job sitemap at
    `https://{host}/careers/sitemap.xml` (robots.txt allows it), which lists
    every posting as `/careers/job/{id}-{title-location-slug}`. We parse the id +
    slug straight out of the URL — no per-job fetch.

    The slug bakes the location onto the end of the title (e.g.
    "senior-software-engineer-secret-clearance-united-states-virginia"), so the
    derived title is a touch noisy, but the role keywords the agent filters on
    are all present. We keep only slugs matching a role term (_ROLE_QUERY_TERMS,
    hyphenated), dedupe by id, and cap at _VENDOR_MAX_JOBS. Raises on HTTP failure
    (caught by fetch_custom).
    """
    host = cfg["host"]
    resp = requests.get(f"https://{host}/careers/sitemap.xml",
                        headers=_BROWSER_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()

    locs = re.findall(r"<loc>([^<]+)</loc>", resp.text)
    # If we got a sitemap INDEX (no job URLs, just nested *.xml sitemaps), follow
    # one level down and gather their <loc>s instead.
    if not any(_EIGHTFOLD_JOB_RE.search(l) for l in locs):
        nested = [l for l in locs if l.lower().rstrip().endswith(".xml")]
        locs = []
        for sm in nested[:20]:
            r = requests.get(sm, headers=_BROWSER_HEADERS, timeout=_TIMEOUT)
            r.raise_for_status()
            locs.extend(re.findall(r"<loc>([^<]+)</loc>", r.text))

    hyphen_terms = [t.replace(" ", "-") for t in _ROLE_QUERY_TERMS]
    by_id: Dict[str, Dict] = {}
    for loc in locs:
        m = _EIGHTFOLD_JOB_RE.search(loc)
        if not m:
            continue
        jid, slug = m.group(1), m.group(2).lower()
        if jid in by_id or not any(t in slug for t in hyphen_terms):
            continue
        by_id[jid] = {
            "job_id": jid,
            "title": _deslugify(m.group(2)),
            "url": loc.split("?")[0],
            "company": company_name,
            "source": "eightfold_sitemap",
            # The sitemap gives no body; left empty for schema uniformity.
            "description": "",
        }
        if len(by_id) >= _VENDOR_MAX_JOBS:
            break
    return list(by_id.values())


# Map a custom site's HOST → the real recruiting-platform API behind it.
# Discovered empirically (see the live probes in the build history). Hosts not
# listed here fall back to the best-effort HTML scrape. Add an entry to light up
# a new site without touching config/companies.py.
_CUSTOM_VENDORS: Dict[str, Dict] = {
    # Workday CXS — tenant + site id taken from the *.myworkdayjobs.com URL.
    "careers.boozallen.com": {
        "vendor": "workday",
        "host": "bah.wd1.myworkdayjobs.com", "tenant": "bah", "site": "bah_jobs",
    },
    # Phenom People search widget.
    "careers.mitre.org": {
        "vendor": "phenom", "host": "careers.mitre.org", "locale": "us/en",
    },
    # Greenhouse behind a vanity careers domain.
    "c3.ai": {"vendor": "greenhouse", "slug": "c3iot"},
    # Phenom "GST" theme — server-rendered HTML search (?k= keyword, ?p= page).
    "www.lockheedmartinjobs.com": {
        "vendor": "gst_html", "host": "www.lockheedmartinjobs.com",
        "search_path": "/search-jobs",
    },
    "careers.l3harris.com": {
        "vendor": "gst_html", "host": "careers.l3harris.com",
        "search_path": "/en/search-jobs",
    },
    # Eightfold "PCSX" SPA — API locked, jobs recovered from the public sitemap.
    "searchcareers.caci.com": {
        "vendor": "eightfold_sitemap", "host": "searchcareers.caci.com",
    },
    "jobs.northropgrumman.com": {
        "vendor": "eightfold_sitemap", "host": "jobs.northropgrumman.com",
    },
}


def _dispatch_vendor(company_name: str, cfg: Dict, search_query: str) -> List[Dict]:
    """Route a resolved vendor config to its fetcher. May raise (caller catches)."""
    vendor = cfg["vendor"]
    if vendor == "workday":
        return fetch_workday(company_name, cfg, search_query)
    if vendor == "phenom":
        return fetch_phenom(company_name, cfg, search_query)
    if vendor == "gst_html":
        return fetch_gst_html(company_name, cfg, search_query)
    if vendor == "eightfold_sitemap":
        return fetch_eightfold_sitemap(company_name, cfg, search_query)
    if vendor == "greenhouse":
        return _greenhouse_jobs(cfg["slug"], company_name)
    raise ValueError(f"unknown custom vendor '{vendor}'")


# ── Custom HTML scraper (fallback for unmapped hosts) ────────────────────────

def _looks_like_job_link(text: str, href: str) -> bool:
    """
    Heuristic for whether an <a> is a job posting rather than nav/footer chrome.

    Only used by the HTML-scrape fallback. It's deliberately permissive — the
    agent's relevance filter is the real gate downstream; here we just want to
    avoid returning "Home", "Login", "Privacy Policy" etc. (Note: this fallback
    cannot recover jobs from JS-rendered portals — those need a vendor entry in
    _CUSTOM_VENDORS.)
    """
    text = (text or "").strip()
    if not href or len(text) < 4:
        return False

    words = text.split()
    if not (1 < len(words) <= 14):
        return False

    junk = {
        "home", "login", "sign in", "sign up", "search", "apply", "menu",
        "privacy policy", "terms", "cookie", "contact", "about", "back",
        "next", "previous", "all jobs", "view all", "learn more",
    }
    if text.lower() in junk:
        return False

    href_l = href.lower()
    if href_l.startswith(("mailto:", "tel:", "javascript:", "#")):
        return False

    job_url_hints = ("job", "career", "position", "opening", "requisition", "req")
    job_text_hints = (
        "engineer", "scientist", "developer", "analyst", "researcher",
        "manager", "lead", "intern", "ml", "ai", "data", "software",
    )
    if any(h in href_l for h in job_url_hints):
        return True
    if any(h in text.lower() for h in job_text_hints):
        return True
    return False


def _scrape_html_jobs(company: Dict, search_query: str) -> List[Dict]:
    """
    Best-effort HTML scrape for a custom portal with no mapped vendor API.

    Builds `search_url?<search_param>=<url-encoded query>`, fetches with a
    browser-like User-Agent, and pulls <a> tags that look like job postings.
    job_id is a hash of the absolute URL (no stable id on these pages). Sleeps
    `_CUSTOM_SCRAPE_DELAY_S` afterward to space out requests. NEVER raises.
    """
    name = company["name"]
    try:
        query_string = urlencode(
            {company["search_param"]: search_query}, quote_via=quote_plus
        )
        full_url = f"{company['search_url']}?{query_string}"

        resp = requests.get(full_url, headers=_BROWSER_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        out: List[Dict] = []
        seen_urls = set()
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"]
            if not _looks_like_job_link(text, href):
                continue

            abs_url = urljoin(full_url, href)
            if abs_url in seen_urls:
                continue
            seen_urls.add(abs_url)

            job_id = hashlib.sha1(abs_url.encode("utf-8")).hexdigest()[:16]
            out.append({
                "job_id": job_id,
                "title": text,
                "url": abs_url,
                "company": name,
                "source": "custom",
                # Scrape only sees the listing anchor text, never the body.
                "description": "",
            })

        print(f"[job_boards] HTML scrape '{name}': {len(out)} candidate link(s)")
        return out

    except Exception as e:
        print(f"[job_boards] HTML scrape failed for '{name}': {e}")
        return []
    finally:
        time.sleep(_CUSTOM_SCRAPE_DELAY_S)


def fetch_custom(company: Dict, search_query: str) -> List[Dict]:
    """
    Fetch a "custom" career portal. Resolves the site's host to a mapped vendor
    API (Workday/Phenom/Greenhouse) and calls it; if the host isn't mapped (or
    the vendor call fails), falls back to the best-effort HTML scrape. NEVER
    raises — logs and returns [] on any failure.
    """
    name = company["name"]
    host = urlparse(company.get("search_url", "")).netloc.lower()
    cfg = _CUSTOM_VENDORS.get(host)

    if cfg:
        try:
            jobs = _dispatch_vendor(name, cfg, search_query)
            print(f"[job_boards] {cfg['vendor']} '{name}': {len(jobs)} job(s)")
            return jobs
        except Exception as e:
            # Vendor API changed/blocked — log and fall back to HTML rather than
            # returning nothing, and never crash the run.
            print(f"[job_boards] {cfg['vendor']} fetch failed for '{name}': {e}")
            return _scrape_html_jobs(company, search_query)

    return _scrape_html_jobs(company, search_query)


# ── Placeholder ──────────────────────────────────────────────────────────────

def fetch_placeholder(company: Dict) -> List[Dict]:
    """
    A company we're tracking but can't fetch yet (no active roles, broken career
    site, pending URL confirmation). Log the name + note so it stays visible in
    the run logs, and return nothing.
    """
    note = company.get("note", "no note")
    print(f"[job_boards] placeholder '{company['name']}' — skipped ({note})")
    return []


# ── Dispatch ─────────────────────────────────────────────────────────────────

def fetch_company_jobs(company: Dict, search_query: str) -> List[Dict]:
    """
    Route a company config to the right fetcher by its `ats` field and return
    its normalized job list.

    `search_query` is used by the custom dispatcher (vendor APIs + HTML scrape).
    Unknown ATS values are logged and treated as empty. The ATS API fetchers may
    raise — the caller (the agent) catches per-company so one failure doesn't
    sink the run; the custom and placeholder paths never raise.
    """
    ats = company.get("ats")
    if ats == "greenhouse":
        return fetch_greenhouse(company)
    if ats == "lever":
        return fetch_lever(company)
    if ats == "ashby":
        return fetch_ashby(company)
    if ats == "custom":
        return fetch_custom(company, search_query)
    if ats == "placeholder":
        return fetch_placeholder(company)

    print(f"[job_boards] unknown ats '{ats}' for '{company.get('name')}' — skipping")
    return []
