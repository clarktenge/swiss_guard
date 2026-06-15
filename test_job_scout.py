# ─────────────────────────────────────────────────────────────────────────────
# test_job_scout — two parts:
#
#   1. OFFLINE unit checks (free, no network, no env, no side effects): exercise
#      the relevance logic, Claude-output parsing, message formatting, the board
#      fetchers (against fixture payloads with requests monkeypatched), the
#      custom scraper's link heuristic, and the agent's seen_jobs diff (against a
#      fake Supabase). These run on import-and-assert, so `python test_job_scout.py`
#      fails loudly if any of that logic regresses.
#
#   2. ⚠️  LIVE smoke test (opt-in): hits the real job boards, calls Claude
#      (billed), and — via run() — writes Supabase rows + posts to #💼-job-scout.
#      Off by default.
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

from config.companies import RELEVANCE_KEYWORDS
from agents.job_scout import (
    is_relevant,
    filter_relevant_jobs,
    _parse_oneliners,
    format_job_message,
    JobScoutAgent,
)
import integrations.job_boards as jb


# ── Part 1a: relevance logic ────────────────────────────────────────────────

def test_relevance_target_roles_augment():
    """target_roles AUGMENT the global keywords — they never replace them."""
    onebrief_roles = ["outcome engineer", "forward deployed"]

    # Matches a target_role (not in the global list) → relevant.
    assert is_relevant("Outcome Engineer", onebrief_roles, RELEVANCE_KEYWORDS)
    assert is_relevant("Forward Deployed Engineer", onebrief_roles, RELEVANCE_KEYWORDS)

    # Matches the GLOBAL list even though it's not in target_roles → still
    # relevant. This is the suppression the augment fix prevents (previously a
    # narrow target_roles list hid every such role).
    assert is_relevant("Machine Learning Engineer", onebrief_roles, RELEVANCE_KEYWORDS)

    # Matches neither list → not relevant.
    assert not is_relevant("Marketing Manager", onebrief_roles, RELEVANCE_KEYWORDS)
    print("✓ relevance: target_roles augment global keywords (no suppression)")


def test_relevance_empty_falls_back_to_global():
    """A company with an EMPTY target_roles list uses the global keywords."""
    assert is_relevant("Senior Machine Learning Engineer", [], RELEVANCE_KEYWORDS)
    assert is_relevant("Computer Vision Researcher", [], RELEVANCE_KEYWORDS)
    assert is_relevant("Software Engineer, TS/SCI", [], RELEVANCE_KEYWORDS)

    # Genuinely irrelevant → dropped even on the broad global list.
    assert not is_relevant("Office Manager", [], RELEVANCE_KEYWORDS)
    assert not is_relevant("Recruiter", [], RELEVANCE_KEYWORDS)
    print("✓ relevance: empty target_roles falls back to global keywords")


def test_filter_relevant_jobs():
    jobs = [
        {"title": "Outcome Engineer", "company": "Onebrief"},
        {"title": "Office Manager", "company": "Onebrief"},
        {"title": "Forward Deployed Engineer", "company": "Onebrief"},
    ]
    kept = filter_relevant_jobs(jobs, ["outcome engineer", "forward deployed"], RELEVANCE_KEYWORDS)
    titles = {j["title"] for j in kept}
    assert titles == {"Outcome Engineer", "Forward Deployed Engineer"}
    print("✓ filter_relevant_jobs: keeps only matching titles")


# ── Part 1b: Claude-output parsing ──────────────────────────────────────────

def test_parse_oneliners_valid():
    raw = '[{"i": 0, "why": "Fits your CV background."}, {"i": 1, "why": "Clearance match."}]'
    parsed = _parse_oneliners(raw, 2)
    assert parsed == {0: "Fits your CV background.", 1: "Clearance match."}
    print("✓ parse_oneliners: clean JSON array")


def test_parse_oneliners_fenced_and_out_of_range():
    raw = '```json\n[{"i": 0, "why": "ok"}, {"i": 9, "why": "dropped"}]\n```'
    parsed = _parse_oneliners(raw, 1)
    assert parsed == {0: "ok"}  # fence stripped, out-of-range index dropped
    print("✓ parse_oneliners: strips code fence, drops out-of-range index")


def test_parse_oneliners_garbage():
    assert _parse_oneliners("Sorry, I can't do that.", 3) == {}
    assert _parse_oneliners("", 3) == {}
    print("✓ parse_oneliners: garbage / empty → {} (caller falls back)")


def test_format_job_message():
    job = {"company": "Anduril", "title": "Applied Scientist", "url": "https://x/y"}
    msg = format_job_message(job, "Synthetic-to-real overlap.", high_priority=True)
    assert "Anduril" in msg and "Applied Scientist" in msg
    assert "https://x/y" in msg
    assert "Synthetic-to-real overlap." in msg
    assert msg.startswith("⭐")  # high priority gets a star
    assert not format_job_message(job, "x", high_priority=False).startswith("⭐")
    print("✓ format_job_message: layout + high-priority star")


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
            {"id": 111, "title": "ML Engineer", "absolute_url": "https://gh/111"},
            {"id": 222, "title": "", "absolute_url": "https://gh/222"},  # dropped: no title
        ]
    }))
    out = jb.fetch_greenhouse({"name": "Anduril", "slug": "andurilindustries"})
    assert len(out) == 1
    assert out[0] == {
        "job_id": "111", "title": "ML Engineer", "url": "https://gh/111",
        "company": "Anduril", "source": "greenhouse",
    }
    print("✓ fetch_greenhouse: parses jobs, drops incomplete rows")


def test_fetch_lever(monkeypatch_get):
    monkeypatch_get(_FakeResp(json_data=[
        {"id": "abc", "text": "Forward Deployed Engineer", "hostedUrl": "https://lever/abc"},
    ]))
    out = jb.fetch_lever({"name": "Palantir", "slug": "palantir"})
    assert out[0]["job_id"] == "abc"
    assert out[0]["title"] == "Forward Deployed Engineer"
    assert out[0]["source"] == "lever"
    print("✓ fetch_lever: parses postings list")


def test_fetch_ashby(monkeypatch_get):
    monkeypatch_get(_FakeResp(json_data={
        "jobs": [
            {"id": "j1", "title": "Outcome Engineer", "jobUrl": "https://ashby/j1", "isListed": True},
            {"id": "j2", "title": "Hidden", "jobUrl": "https://ashby/j2", "isListed": False},  # dropped
        ]
    }))
    out = jb.fetch_ashby({"name": "Onebrief", "slug": "onebrief"})
    assert len(out) == 1
    assert out[0]["job_id"] == "j1"
    assert out[0]["url"] == "https://ashby/j1"
    assert out[0]["source"] == "ashby"
    print("✓ fetch_ashby: parses jobs list, skips unlisted")


# ── Part 1c-bis: vendor JSON fetchers behind custom portals ──────────────────

def test_fetch_workday(monkeypatch_post):
    # First call (term 1) returns a posting; subsequent term calls return the
    # same one (deduped by externalPath) so the union has exactly one job.
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
    # Booz Allen's host is in _CUSTOM_VENDORS → Workday.
    company = {"name": "Booz Allen Hamilton",
               "search_url": "https://careers.boozallen.com/jobs/search",
               "search_param": "q"}
    out = jb.fetch_custom(company, "anything")
    assert out and out[0]["source"] == "workday"
    print("✓ fetch_custom: routes a mapped host to its vendor API")


# ── Part 1d: custom scraper (heuristic + parsing + never-raises) ─────────────

def test_looks_like_job_link():
    assert jb._looks_like_job_link("Machine Learning Engineer", "/jobs/123")
    assert jb._looks_like_job_link("Applied Scientist, ISR", "/careers/posting/9")
    # Chrome / nav links rejected.
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
    # Two distinct job links; the duplicate URL and the chrome links are dropped.
    assert urls == {
        "https://careers.example.com/jobs/100",
        "https://site.com/careers/200",
    }
    assert all(j["source"] == "custom" and j["company"] == "Example Corp" for j in out)
    # job_id is a stable hash of the URL.
    assert all(len(j["job_id"]) == 16 for j in out)
    print("✓ fetch_custom: parses links, dedupes, absolutizes URLs, hashes ids")


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
    """Minimal stand-in: seen_jobs already contains job_id 'A' for 'Acme'."""
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


def test_record_seen_writes_before_filtering():
    fake = _FakeSupabase(existing=set())
    agent = _bare_agent(fake)
    jobs = [
        {"job_id": "B", "company": "Acme", "title": "ML Engineer", "url": "u2", "source": "greenhouse"},
    ]
    agent._record_seen(jobs)
    assert len(fake.upserted) == 1
    assert fake.upserted[0]["job_id"] == "B"
    assert fake.upserted[0]["source"] == "greenhouse"
    print("✓ _record_seen: persists new jobs to seen_jobs")


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
    test_relevance_target_roles_augment()
    test_relevance_empty_falls_back_to_global()
    test_filter_relevant_jobs()
    test_parse_oneliners_valid()
    test_parse_oneliners_fenced_and_out_of_range()
    test_parse_oneliners_garbage()
    test_format_job_message()
    test_looks_like_job_link()
    test_find_new_jobs()
    test_record_seen_writes_before_filtering()

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
    print(f"\nmetadata new_relevant_count={result.metadata['new_relevant_count']}")


def run_live():
    """Full pipeline: live boards + Claude + Discord post + Supabase logging."""
    print("\n⚠️  Running LIVE job-scout (boards + Claude + Discord + Supabase)…\n")
    agent = JobScoutAgent()  # post=True
    result = agent.run()
    print(result.content)


if __name__ == "__main__":
    run_offline_checks()
    args = sys.argv[1:]
    if "preview" in args:
        run_preview()
    if "live" in args:
        run_live()
