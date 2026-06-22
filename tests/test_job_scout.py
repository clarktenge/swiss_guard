# ─────────────────────────────────────────────────────────────────────────────
# test_job_scout — two parts:
#
#   1. OFFLINE unit checks (free, no network, no env, no side effects): exercise
#      the US-only filter, Claude-match parsing, message formatting, the board
#      fetchers (against fixture payloads with requests monkeypatched), the
#      custom dispatch/scrape, and the agent's seen_jobs diff (fake Supabase).
#      These run on import-and-assert, so `python test_job_scout.py` fails loudly
#      if any of that logic regresses.
#
#   2. ⚠️  LIVE smoke tests (opt-in): hit the real job boards, call Claude
#      (billed), and — via run() — write Supabase rows + post to #💼-job-scout.
#      Off by default. Scans every non-placeholder company in config/companies.py.
#
# Run:  python test_job_scout.py            # offline checks only
#       python test_job_scout.py preview    # offline + live boards + Claude, NO posting
#       python test_job_scout.py live       # offline + full run() (posts + writes)
# ─────────────────────────────────────────────────────────────────────────────
import sys

# Emoji-heavy output; force UTF-8 so the default Windows console doesn't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from agents.job_scout import (
    _passes_us_filter,
    _parse_matches,
    format_job_message,
    JobScoutAgent,
)
import integrations.job_boards as jb


# ── Part 1a: US-only location filter ────────────────────────────────────────

def test_passes_us_filter():
    # No / empty location → keep (don't discard on missing data).
    assert _passes_us_filter({"title": "ML Engineer"}) is True
    assert _passes_us_filter({"location": ""}) is True
    assert _passes_us_filter({"location": None}) is True

    # Explicit US signals.
    assert _passes_us_filter({"location": "San Francisco, CA, United States"}) is True
    assert _passes_us_filter({"location": "Remote - USA"}) is True
    assert _passes_us_filter({"location": "Reston, VA"}) is True          # state abbr
    assert _passes_us_filter({"location": "Austin, Texas"}) is True       # state name
    # Dict-shaped location is flattened.
    assert _passes_us_filter({"location": {"city": "Austin", "state": "TX",
                                           "country": "United States"}}) is True

    # Non-US → dropped.
    assert _passes_us_filter({"location": "London, United Kingdom"}) is False
    assert _passes_us_filter({"location": "Tel Aviv, Israel"}) is False
    print("✓ _passes_us_filter: keeps US + missing, drops non-US")


# ── Part 1b: Claude-match parsing + message formatting ──────────────────────

def test_parse_matches_valid():
    raw = ('[{"company":"Palantir","title":"Forward Deployed Engineer",'
           '"url":"https://x","reason":"Fits Clark."}]')
    out = _parse_matches(raw)
    assert len(out) == 1 and out[0]["company"] == "Palantir"
    print("✓ _parse_matches: clean JSON array")


def test_parse_matches_fenced_and_empty():
    assert _parse_matches('```json\n[]\n```') == []          # fenced empty list
    assert _parse_matches('[]') == []
    print("✓ _parse_matches: strips fence, handles empty list")


def test_parse_matches_garbage():
    assert _parse_matches("Sorry, nothing matched.") == []   # not JSON → []
    assert _parse_matches('{"not":"a list"}') == []          # not a list → []
    print("✓ _parse_matches: garbage / non-list → []")


def test_format_job_message():
    # Palantir is high-priority in companies.py → 🔴 tag leads the company line.
    msg = format_job_message("Palantir", "Forward Deployed Engineer",
                             "https://x/y", "Washington, DC",
                             "Aligns with Clark's FDE target.")
    assert msg == ("─────────────────────────────\n"
                   "🔴 **Palantir**\n"
                   "📋 Forward Deployed Engineer\n"
                   "📍 Washington, DC\n"
                   "🔗 https://x/y\n"
                   "💡 Aligns with Clark's FDE target.\n")

    # perfect_fit adds a ⭐ banner under the divider.
    perfect = format_job_message("Palantir", "Forward Deployed Engineer",
                                 "https://x/y", "📍 Multiple locations",
                                 "Aligns with Clark's FDE target.",
                                 perfect_fit=True)
    assert perfect.startswith("─────────────────────────────\n⭐ PERFECT FIT\n🔴 **Palantir**\n")
    print("✓ format_job_message: divider + priority tag + location + perfect-fit")


# ── Part 1c: board fetchers against fixture payloads (requests monkeypatched) ─

class _FakeResp:
    def __init__(self, json_data=None, text="", status=200):
        self._json = json_data
        self.text = text
        self.status_code = status

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_fetch_greenhouse(monkeypatch_get):
    monkeypatch_get(_FakeResp(json_data={
        "jobs": [
            # `content` arrives as entity-encoded HTML (Greenhouse's shape); the
            # fetcher must unescape + strip it to plain text for Claude.
            {"id": 111, "title": "ML Engineer", "absolute_url": "https://gh/111",
             "content": "&lt;p&gt;Requires &lt;b&gt;5+ years&lt;/b&gt; experience.&lt;/p&gt;"},
            {"id": 222, "title": "", "absolute_url": "https://gh/222"},  # dropped: no title
        ]
    }))
    out = jb.fetch_greenhouse({"name": "Anduril", "slug": "andurilindustries"})
    assert len(out) == 1
    assert out[0] == {
        "job_id": "111", "title": "ML Engineer", "url": "https://gh/111",
        "company": "Anduril", "source": "greenhouse",
        "description": "Requires 5+ years experience.",
    }
    print("✓ fetch_greenhouse: parses jobs, strips entity-encoded content, drops incomplete rows")


def test_fetch_lever(monkeypatch_get):
    monkeypatch_get(_FakeResp(json_data=[
        {"id": "abc", "text": "Forward Deployed Engineer", "hostedUrl": "https://lever/abc",
         "descriptionPlain": "Deploy alongside customers.",
         # The hard-reject-bearing requirements live in `lists`, not in
         # descriptionPlain — the fetcher must stitch them in.
         "lists": [{"text": "Requirements", "content": "<li>3+ years experience</li>"}]},
    ]))
    out = jb.fetch_lever({"name": "Palantir", "slug": "palantir"})
    assert out[0]["job_id"] == "abc"
    assert out[0]["title"] == "Forward Deployed Engineer"
    assert out[0]["source"] == "lever"
    assert "Deploy alongside customers." in out[0]["description"]
    assert "Requirements" in out[0]["description"] and "3+ years" in out[0]["description"]
    print("✓ fetch_lever: parses postings list, stitches requirement lists into description")


def test_fetch_ashby(monkeypatch_get):
    monkeypatch_get(_FakeResp(json_data={
        "jobs": [
            {"id": "j1", "title": "Outcome Engineer", "jobUrl": "https://ashby/j1",
             "isListed": True, "descriptionPlain": "Own outcomes. Master's degree required."},
            {"id": "j2", "title": "Hidden", "jobUrl": "https://ashby/j2", "isListed": False},  # dropped
        ]
    }))
    out = jb.fetch_ashby({"name": "Onebrief", "slug": "onebrief"})
    assert len(out) == 1
    assert out[0]["job_id"] == "j1"
    assert out[0]["url"] == "https://ashby/j1"
    assert out[0]["source"] == "ashby"
    assert out[0]["description"] == "Own outcomes. Master's degree required."
    print("✓ fetch_ashby: parses jobs list, skips unlisted, carries description")


# ── Part 1c-bis: vendor JSON fetchers behind custom portals ──────────────────

def test_fetch_workday(monkeypatch_post):
    monkeypatch_post(_FakeResp(json_data={
        "total": 1,
        "jobPostings": [
            {"title": "Machine Learning Engineer", "externalPath": "/job/McLean-VA/ML_R1"},
            {"title": "", "externalPath": "/job/x"},  # dropped: no title
        ],
    }))
    cfg = {"vendor": "workday", "host": "bah.wd1.myworkdayjobs.com",
           "tenant": "bah", "site": "bah_jobs"}
    out = jb.fetch_workday("Booz Allen", cfg, "ignored")
    assert len(out) == 1
    assert out[0]["job_id"] == "/job/McLean-VA/ML_R1"
    assert out[0]["url"] == "https://bah.wd1.myworkdayjobs.com/bah_jobs/job/McLean-VA/ML_R1"
    assert out[0]["source"] == "workday"
    print("✓ fetch_workday: parses jobPostings, builds URL, dedupes union")


def test_fetch_phenom(monkeypatch_post):
    monkeypatch_post(_FakeResp(json_data={
        "refineSearch": {
            "totalHits": 1,
            "data": {"jobs": [
                {"title": "Geospatial Data Scientist", "jobId": "R9", "jobSeqNo": "SEQ9"},
            ]},
        }
    }))
    cfg = {"vendor": "phenom", "host": "careers.mitre.org", "locale": "us/en"}
    out = jb.fetch_phenom("MITRE", cfg, "machine learning")
    assert out[0]["job_id"] == "R9"
    assert out[0]["url"] == "https://careers.mitre.org/us/en/job/SEQ9"
    assert out[0]["source"] == "phenom"
    print("✓ fetch_phenom: parses refineSearch jobs, builds URL")


def test_fetch_custom_routes_to_vendor(monkeypatch_post, no_sleep):
    """A mapped host dispatches to its vendor API, not the HTML scraper."""
    monkeypatch_post(_FakeResp(json_data={
        "total": 1,
        "jobPostings": [{"title": "Data Scientist", "externalPath": "/job/DC/DS_R2"}],
    }))
    company = {"name": "Booz Allen Hamilton",
               "search_url": "https://careers.boozallen.com/jobs/search",
               "search_param": "q"}
    out = jb.fetch_custom(company, "anything")
    assert out and out[0]["source"] == "workday"
    print("✓ fetch_custom: routes a mapped host to its vendor API")


# ── Part 1d: custom HTML scraper (heuristic + parsing + never-raises) ────────

def test_looks_like_job_link():
    assert jb._looks_like_job_link("Machine Learning Engineer", "/jobs/123")
    assert jb._looks_like_job_link("Applied Scientist, ISR", "/careers/posting/9")
    assert not jb._looks_like_job_link("Home", "/")
    assert not jb._looks_like_job_link("Privacy Policy", "/privacy")
    assert not jb._looks_like_job_link("Login", "javascript:void(0)")
    assert not jb._looks_like_job_link("X", "/jobs/1")  # too short
    print("✓ _looks_like_job_link: accepts roles, rejects chrome")


def test_fetch_custom_parses_html(monkeypatch_get, no_sleep):
    html = """
    <html><body>
      <a href="/">Home</a>
      <a href="/jobs/100">Senior Machine Learning Engineer</a>
      <a href="/jobs/100">Senior Machine Learning Engineer</a>  <!-- dup url -->
      <a href="https://site.com/careers/200">Computer Vision Scientist</a>
      <a href="/privacy">Privacy Policy</a>
    </body></html>
    """
    monkeypatch_get(_FakeResp(text=html))
    # Host NOT in _CUSTOM_VENDORS → exercises the HTML-scrape fallback.
    company = {
        "name": "Example Corp",
        "search_url": "https://careers.example.com/search",
        "search_param": "keywords",
    }
    out = jb.fetch_custom(company, "machine learning")
    urls = {j["url"] for j in out}
    assert urls == {
        "https://careers.example.com/jobs/100",
        "https://site.com/careers/200",
    }
    assert all(j["source"] == "custom" and j["company"] == "Example Corp" for j in out)
    assert all(len(j["job_id"]) == 16 for j in out)
    print("✓ fetch_custom: HTML fallback parses links, dedupes, absolutizes, hashes ids")


def test_fetch_custom_never_raises(monkeypatch, no_sleep):
    def boom(*a, **k):
        raise ConnectionError("site down")
    monkeypatch.setattr(jb.requests, "get", boom)
    company = {"name": "Leidos", "search_url": "https://x/search", "search_param": "q"}
    assert jb.fetch_custom(company, "ml") == []  # logged + empty, no exception
    print("✓ fetch_custom: swallows failures and returns []")


# ── Part 1e: agent seen_jobs diff (fake Supabase, no env / no real client) ───

class _FakeQuery:
    def __init__(self, store):
        self.store = store

    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def in_(self, *a, **k): return self

    def execute(self):
        return type("R", (), {"data": self.store})()


class _FakeSupabase:
    """Minimal stand-in: seen_jobs already contains the given job_ids."""
    def __init__(self, existing):
        self.existing = existing
        self.upserted = []

    def table(self, name):
        outer = self

        class _T:
            def select(self, *a, **k):
                return _FakeQuery([{"job_id": jid} for jid in outer.existing])

            def upsert(self, rows, **k):
                outer.upserted.extend(rows)
                return type("E", (), {"execute": lambda s: None})()

        return _T()


def _bare_agent(fake_supabase):
    """Build a JobScoutAgent without running __init__ (no env / clients needed)."""
    agent = JobScoutAgent.__new__(JobScoutAgent)
    agent.supabase = fake_supabase
    agent.companies = []
    agent.post = False
    return agent


def test_find_new_jobs():
    fake = _FakeSupabase(existing={"A"})
    agent = _bare_agent(fake)
    jobs = [
        {"job_id": "A", "company": "Acme", "title": "Old", "url": "u", "source": "greenhouse"},
        {"job_id": "B", "company": "Acme", "title": "New", "url": "u2", "source": "greenhouse"},
    ]
    new = agent._find_new_jobs("Acme", jobs)
    assert [j["job_id"] for j in new] == ["B"]
    print("✓ _find_new_jobs: returns only unseen job_ids")


def test_record_seen_writes_before_judgment():
    fake = _FakeSupabase(existing=set())
    agent = _bare_agent(fake)
    jobs = [
        {"job_id": "B", "company": "Acme", "title": "ML Engineer", "url": "u2", "source": "greenhouse"},
    ]
    agent._record_seen(jobs)
    assert len(fake.upserted) == 1
    assert fake.upserted[0]["job_id"] == "B"
    assert fake.upserted[0]["source"] == "greenhouse"
    print("✓ _record_seen: persists new jobs to seen_jobs (pre-judgment)")


# ── Tiny monkeypatch shim (so this runs without pytest installed) ────────────

class _Monkeypatch:
    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, value):
        old = getattr(obj, name)
        self._undo.append((obj, name, old))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo.clear()


def run_offline_checks():
    # Pure helpers — no patching needed.
    test_passes_us_filter()
    test_parse_matches_valid()
    test_parse_matches_fenced_and_empty()
    test_parse_matches_garbage()
    test_format_job_message()
    test_looks_like_job_link()
    test_find_new_jobs()
    test_record_seen_writes_before_judgment()

    # Fetcher tests need requests.get / requests.post / time.sleep patched.
    mp = _Monkeypatch()
    try:
        def monkeypatch_get(resp):
            mp.setattr(jb.requests, "get", lambda *a, **k: resp)

        def monkeypatch_post(resp):
            mp.setattr(jb.requests, "post", lambda *a, **k: resp)

        no_sleep = mp.setattr(jb.time, "sleep", lambda *a, **k: None)

        test_fetch_greenhouse(monkeypatch_get)
        test_fetch_lever(monkeypatch_get)
        test_fetch_ashby(monkeypatch_get)
        test_fetch_workday(monkeypatch_post)
        test_fetch_phenom(monkeypatch_post)
        test_fetch_custom_routes_to_vendor(monkeypatch_post, no_sleep)
        test_fetch_custom_parses_html(monkeypatch_get, no_sleep)
        test_fetch_custom_never_raises(mp, no_sleep)
    finally:
        mp.undo()

    print("\nAll offline checks passed ✅")


# ── Part 2: live smoke tests (opt-in) ───────────────────────────────────────

def run_preview():
    """Live boards + Claude, but NO Discord posting and NO run() side effects."""
    print("\n⚠️  Previewing job-scout (live boards + Claude, post=False)…\n")
    agent = JobScoutAgent(post=False)
    result = agent.execute()
    print("\n" + "=" * 60)
    print(result.content)
    print(f"matched={result.metadata['matched']} of {result.metadata['new_jobs']} new jobs")


def run_live():
    """Full pipeline: live boards + Claude + Discord post + Supabase logging."""
    print("\n⚠️  Running LIVE job-scout (boards + Claude + Discord + Supabase)…\n")
    agent = JobScoutAgent()  # post=True; scans all non-placeholder companies
    result = agent.run()
    if result is None:
        print("run() returned no result")
        return

    print("\n--- messages posted to #💼-job-scout (one per match) ---")
    matches = result.metadata.get("matches", [])
    if matches:
        for m in matches:
            print(format_job_message(m["company"], m["title"], m["url"], m["reason"]))
            print()
    else:
        print("(none)")
    print("--- final summary message ---")
    print(result.content)


if __name__ == "__main__":
    run_offline_checks()
    args = sys.argv[1:]
    if "preview" in args:
        run_preview()
    if "live" in args:
        run_live()
