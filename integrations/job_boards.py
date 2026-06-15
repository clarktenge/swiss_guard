"""
job_boards.py — job listing fetchers for the job-scout agent.

One fetcher per ATS (applicant tracking system) type. Each takes a company
config dict (see config/companies.py) and returns a normalized list of jobs:

    [{"job_id": str, "title": str, "url": str, "company": str, "source": str}]

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

import time
import hashlib
from typing import List, Dict, Optional
from urllib.parse import urlencode, urljoin, quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

# Network timeout for every outbound request (seconds).
_TIMEOUT = 20

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
        out.append({
            "job_id": str(job_id),
            "title": title,
            "url": link,
            "company": company["name"],
            "source": "lever",
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
        })
    return out


# ── Vendor JSON APIs behind "custom" career portals ──────────────────────────

# Workday's `searchText` ANDs its words, so the agent's full multi-term
# SEARCH_QUERY ("machine learning applied scientist AI engineer forward
# deployed") matches zero postings. We instead run one search per focused role
# term and union the results — each term is loose enough to return a useful set,
# and the agent's relevance filter narrows the union down afterward.
_WORKDAY_QUERY_TERMS = [
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
    union per-term searches (see _WORKDAY_QUERY_TERMS) instead. Deduped by
    externalPath, capped at _VENDOR_MAX_JOBS. Raises on HTTP/parse failure
    (caught by fetch_custom).
    """
    host, tenant, site = cfg["host"], cfg["tenant"], cfg["site"]
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"

    by_id: Dict[str, Dict] = {}  # externalPath → job, dedupes across terms
    headers = {**_BROWSER_HEADERS, "Content-Type": "application/json",
               "Accept": "application/json"}

    for term in _WORKDAY_QUERY_TERMS:
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
            })

        total = rs.get("totalHits", 0)
        frm += size
        if frm >= total:
            break
    return out


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
}


def _dispatch_vendor(company_name: str, cfg: Dict, search_query: str) -> List[Dict]:
    """Route a resolved vendor config to its fetcher. May raise (caller catches)."""
    vendor = cfg["vendor"]
    if vendor == "workday":
        return fetch_workday(company_name, cfg, search_query)
    if vendor == "phenom":
        return fetch_phenom(company_name, cfg, search_query)
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
