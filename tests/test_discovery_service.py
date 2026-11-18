"""Offline checks for web discovery in the app: plans, background runs, stop,
recovery after a restart, replay, the full log and saved responses, and the
/discovery API routes.

SerpApi is replaced by a fake client; the Cursor SDK and the database are never used.
"""

import json
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from scanger import api, deps, discover, discovery_api, discovery_service
from scanger.discover import DiscoveryError, RunNotFound
from scanger.discovery_service import RunConflict, RunOptions
from scanger.serpapi import AccountStatus, ProviderResponse

CONFIG = (
    'markets = ["de-de"]\nmax_calls = 3\n'
    '[[steps]]\nquery = "precise"\nroute = "organic"\n'
    '[[steps]]\nquery = "broad"\nroute = "organic"\n'
    '[[steps]]\nquery = "synonym"\nroute = "organic"\n'
    '[locales.de-de]\nlanguage = "de"\ncountry = "de"\ngoogle_domain = "google.de"\n'
    '[locales.fr-fr]\nlanguage = "fr"\ncountry = "fr"\ngoogle_domain = "google.fr"\n'
)
QUERIES = {"de": {"precise": "braune Steppjacke Kapuze", "synonym": "Pufferjacke braun", "broad": "Steppjacke braun"}}


def organic(*links):
    return {"organic_results": [{"position": i, "title": f"r{i}", "link": link}
                                for i, link in enumerate(links, start=1)]}


class FakeClient:
    """Answers from canned bodies; a search can be held until `release` is set."""

    def __init__(self, *bodies, hold_at: int | None = None, account=None):
        self.bodies = list(bodies)
        self.hold_at = hold_at
        self.holding = threading.Event()
        self.release = threading.Event()
        self.searches = 0
        self.account_status = account or AccountStatus("Free Plan", 250, 240, 0, 50)

    def __call__(self, api_key):
        assert api_key == "test-key"
        return self

    def account(self):
        return self.account_status

    def search(self, params):
        self.searches += 1
        if self.searches == self.hold_at:
            self.holding.set()
            assert self.release.wait(5)
        body = self.bodies.pop(0)
        if isinstance(body, Exception):
            raise body
        return ProviderResponse(200, body, f"sid{self.searches}", "Success", None, 0.1)


@pytest.fixture
def root(tmp_path, monkeypatch):
    config = tmp_path / "discovery.toml"
    config.write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr(discovery_service, "discovery_config_path", lambda: config)
    monkeypatch.setattr(discovery_service, "serpapi_api_key", lambda: "test-key")
    yield tmp_path / "data"
    assert wait_idle(), "a run thread was left running"


def wait_idle(timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    while discovery_service._active:
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def plan(root, queries=QUERIES, **options):
    settings = discovery_service.load_settings(RunOptions(**options) if options else None)
    run, _ = discovery_service.plan_from_queries(root, settings, queries)
    return run


def test_plan_from_queries_saves_a_plan_and_notes_ignored_languages(root):
    settings = discovery_service.load_settings()
    run, notes = discovery_service.plan_from_queries(root, settings, {**QUERIES, "it": {"precise": "giacca"}})
    assert run["status"] == "planned" and run["active"] is False
    assert [c["status"] for c in run["calls"]] == ["planned"] * 3
    assert notes == ["Ignored queries for it (not in the selected languages)."]
    saved = json.loads(discover.record_path(root, uuid.UUID(run["id"]), "queries.json").read_text())
    assert saved == QUERIES


def test_options_choose_markets_and_budget(root):
    run = discovery_service.get_run(root, plan(root, {"fr": {"precise": "doudoune marron"}},
                                               markets=["fr-fr"], max_calls=1)["id"])
    assert run["settings"]["markets"] == ["fr-fr"] and run["settings"]["max_calls"] == 1
    assert [c["q"] for c in run["calls"] if c["status"] == "planned"] == ["doudoune marron"]


def test_plan_needs_a_query_for_a_selected_language(root):
    settings = discovery_service.load_settings()
    with pytest.raises(DiscoveryError, match="at least one query"):
        discovery_service.plan_from_queries(root, settings, {"de": {"precise": "  "}})


def test_reused_queries_keep_their_origin(root):
    first = plan(root)
    settings = discovery_service.load_settings()
    run, _ = discovery_service.plan_from_queries(root, settings, QUERIES, from_record=first["id"])
    assert run["source"]["from_record"] == first["id"]


def test_run_saves_progress_and_finishes_in_the_background(root):
    run = plan(root)
    fake = FakeClient(organic("https://a.de/p/1"), organic("https://b.de/p/1", "https://a.de/p/1"),
                      {"organic_results": []}, hold_at=2)
    started = discovery_service.start_run(root, run["id"], fake)
    assert started["status"] == "running" and started["active"] is True
    assert started["account_before"]["searches_left"] == 240

    assert fake.holding.wait(5)
    during = discovery_service.get_run(root, run["id"])
    assert [c["status"] for c in during["calls"]] == ["ok", "planned", "planned"]
    assert [lead["url"] for lead in during["leads"]] == ["https://a.de/p/1"]
    fake.release.set()

    assert wait_idle()
    done = discovery_service.get_run(root, run["id"])
    assert done["status"] == "completed" and done["active"] is False
    assert [lead["url"] for lead in done["leads"]] == ["https://a.de/p/1", "https://b.de/p/1"]
    assert done["finished_at"]
    (item,) = discovery_service.list_runs(root)
    assert (item["status"], item["calls_done"], item["calls_planned"], item["leads"]) == ("completed", 3, 3, 2)
    assert "test-key" not in json.dumps(done)


def test_one_run_at_a_time_and_only_planned_runs_start(root):
    first, second = plan(root), plan(root)
    fake = FakeClient(organic("https://a.de/p/1"), organic(), organic(), hold_at=1)
    discovery_service.start_run(root, first["id"], fake)
    with pytest.raises(RunConflict, match="still running"):
        discovery_service.start_run(root, second["id"], FakeClient())
    fake.release.set()
    assert wait_idle()
    with pytest.raises(RunConflict, match="Only planned runs"):
        discovery_service.start_run(root, first["id"], FakeClient())
    assert discovery_service._active == {}
    assert discovery_service.get_run(root, second["id"])["status"] == "planned"


def test_stop_finishes_the_current_search_and_sends_no_more(root):
    run = plan(root)
    fake = FakeClient(organic("https://a.de/p/1"), organic("https://b.de/p/1"), organic(), hold_at=1)
    discovery_service.start_run(root, run["id"], fake)
    assert fake.holding.wait(5)
    discovery_service.cancel_run(root, run["id"])
    fake.release.set()
    assert wait_idle()
    done = discovery_service.get_run(root, run["id"])
    assert done["status"] == "cancelled" and fake.searches == 1
    assert [c["status"] for c in done["calls"]] == ["ok", "not_run", "not_run"]
    assert [lead["url"] for lead in done["leads"]] == ["https://a.de/p/1"]
    with pytest.raises(RunConflict, match="not running"):
        discovery_service.cancel_run(root, run["id"])


def test_quota_or_missing_key_refuses_before_any_search(root, monkeypatch):
    run = plan(root)
    short = FakeClient(account=AccountStatus("Free Plan", 250, 2, 0, 50))
    with pytest.raises(DiscoveryError, match="needs 3 searches but only 2 are left this month"):
        discovery_service.start_run(root, run["id"], short)
    monkeypatch.setattr(discovery_service, "serpapi_api_key", lambda: None)
    with pytest.raises(DiscoveryError, match="SERPAPI_API_KEY is not set"):
        discovery_service.start_run(root, run["id"], FakeClient())
    assert short.searches == 0 and discovery_service._active == {}
    assert discovery_service.get_run(root, run["id"])["status"] == "planned"


def test_unexpected_error_fails_the_run_and_frees_the_slot(root):
    run = plan(root)
    discovery_service.start_run(root, run["id"], FakeClient(organic("https://a.de/p/1"), RuntimeError("boom")))
    assert wait_idle()
    done = discovery_service.get_run(root, run["id"])
    assert done["status"] == "failed" and done["error"] == "RuntimeError: boom"
    assert [c["status"] for c in done["calls"]] == ["ok", "not_run", "not_run"]


def test_runs_left_running_by_a_stopped_app_are_finished_with_saved_results(root):
    run = plan(root)
    record = discover.load_record(root, uuid.UUID(run["id"]))
    calls = discover.calls_from_json(record)
    body = organic("https://a.de/p/1")
    discover.write_json(discover.record_path(root, uuid.UUID(run["id"]), "raw/01-organic-de-de.json"), body)
    calls[0].status, calls[0].raw_file, calls[0].result_count = "ok", "raw/01-organic-de-de.json", 1
    record["status"] = "running"
    discover.save_record(root, record, calls)

    assert discovery_service.reconcile_interrupted(root) == 1
    done = discovery_service.get_run(root, run["id"])
    assert done["status"] == "partial" and done["interrupted"] is True
    assert [c["note"] for c in done["calls"][1:]] == [discovery_service.INTERRUPTED_NOTE] * 2
    assert [lead["url"] for lead in done["leads"]] == ["https://a.de/p/1"]
    assert discovery_service.reconcile_interrupted(root) == 0


def test_replay_log_and_raw_responses_read_the_saved_run(root):
    run = plan(root)
    discovery_service.start_run(root, run["id"], FakeClient(
        organic(*(f"https://shop{i}.de/p/1" for i in range(30))), organic("https://b.de/p/1"), organic()))
    assert wait_idle()

    again = discovery_service.replay(root, run["id"])
    saved = discovery_service.get_run(root, run["id"])
    assert [lead["key"] for lead in again["leads"]] == [lead["key"] for lead in saved["leads"]]

    log = discovery_service.run_log(root, run["id"])
    assert f"Run {run['id']}: completed" in log
    assert all(lead["url"] in log for lead in saved["leads"])
    assert "braune Steppjacke Kapuze" in log and "test-key" not in log
    assert "replayed" in discovery_service.run_log(root, run["id"], replayed=True)

    assert discovery_service.raw_response(root, run["id"], 2) == organic("https://b.de/p/1")
    with pytest.raises(RunNotFound):
        discovery_service.raw_response(root, run["id"], 9)


def test_replay_needs_saved_responses(root):
    run = plan(root)
    with pytest.raises(DiscoveryError, match="no saved responses"):
        discovery_service.replay(root, run["id"])
    with pytest.raises(RunNotFound):
        discovery_service.get_run(root, uuid.uuid4())


def test_settings_info_lists_markets_and_what_is_configured(root, monkeypatch):
    monkeypatch.setattr(discovery_service, "cursor_api_key", lambda: None)
    info = discovery_service.settings_info()
    assert [(m["id"], m["enabled"]) for m in info["markets"]] == [("de-de", True), ("fr-fr", False)]
    assert (info["default_markets"], info["max_calls"]) == (["de-de"], 3)
    assert info["serpapi_configured"] is True and info["cursor_configured"] is False


# --- API routes ---------------------------------------------------------------------


@pytest.fixture
def client(root):
    fake = FakeClient(organic("https://a.de/p/1"), organic("https://b.de/p/1"), organic())

    def no_db():
        yield None

    api.app.dependency_overrides.update({
        deps.get_db: no_db,
        deps.get_data_root: lambda: root,
        discovery_api.get_client_factory: lambda: fake,
    })
    try:
        yield TestClient(api.app)
    finally:
        api.app.dependency_overrides.clear()


def test_api_plans_runs_and_reads_a_run(client):
    assert client.get("/discovery/settings").json()["default_markets"] == ["de-de"]
    assert client.get("/discovery/account").json()["searches_left"] == 240

    response = client.post("/discovery/runs", json={"source": "queries", "queries": QUERIES, "max_calls": 2})
    assert response.status_code == 201
    run = response.json()["run"]
    assert run["status"] == "planned" and run["settings"]["max_calls"] == 2
    assert [item["id"] for item in client.get("/discovery/runs").json()] == [run["id"]]

    assert client.post(f"/discovery/runs/{run['id']}/start").json()["status"] == "running"
    assert wait_idle()
    done = client.get(f"/discovery/runs/{run['id']}").json()
    assert done["status"] == "completed" and len(done["leads"]) == 2
    assert len(client.get(f"/discovery/runs/{run['id']}/replay").json()["leads"]) == 2
    assert "https://b.de/p/1" in client.get(f"/discovery/runs/{run['id']}/log").json()["text"]
    assert client.get(f"/discovery/runs/{run['id']}/raw/1").json() == organic("https://a.de/p/1")


@pytest.mark.parametrize("method, path, body, status, detail", [
    ("get", "/discovery/runs/{missing}", None, 404, "No saved discovery run"),
    ("get", "/discovery/runs/not-a-uuid", None, 422, None),
    ("post", "/discovery/runs/{planned}/cancel", None, 409, "not running"),
    ("get", "/discovery/runs/{planned}/raw/1", None, 404, "no saved response"),
    ("post", "/discovery/runs", {"source": "image"}, 422, "Upload a reference image first."),
    ("post", "/discovery/runs", {"source": "queries", "queries": {}}, 422, "at least one query"),
    ("post", "/discovery/runs", {"source": "queries", "queries": QUERIES, "max_calls": 0}, 422, None),
    ("post", "/discovery/runs", {"source": "queries", "queries": QUERIES, "markets": ["xx-yy"]}, 422,
     "Unknown market"),
])
def test_api_errors(client, method, path, body, status, detail):
    planned = client.post("/discovery/runs", json={"source": "queries", "queries": QUERIES}).json()["run"]
    url = path.format(missing=uuid.uuid4(), planned=planned["id"])
    response = client.request(method.upper(), url, json=body)
    assert response.status_code == status
    if detail:
        assert detail in response.json()["detail"]
