"""Offline checks for the M04 discovery probe: settings, plan, records, replay.

SerpApi is replaced by a fake client; the Cursor SDK is never called.
"""

import copy
import json
import tomllib
import uuid

import pytest

from scanger import discover
from scanger.config import REPO_ROOT
from scanger.localize import build_prompt as localize_prompt
from scanger.localize import validate_localization
from scanger.serpapi import AccountStatus, ProviderError, ProviderResponse

BASE = {
    "markets": ["de-de", "fr-fr"],
    "max_calls": 6,
    "site_targets": ["etsy.com"],
    "steps": [
        {"query": "precise", "route": "shopping"},
        {"query": "broad", "route": "organic", "with_modifiers": True},
        {"query": "broad", "route": "organic", "with_sites": True},
        {"query": "synonym", "route": "organic"},
    ],
    "modifiers": {"de": ["handgemacht", "Manufaktur"], "fr": ["fait main"]},
    "locales": {
        "de-de": {"language": "de", "country": "de", "google_domain": "google.de"},
        "de-at": {"language": "de", "country": "at", "google_domain": "google.at"},
        "fr-fr": {"language": "fr", "country": "fr", "google_domain": "google.fr", "location": "Paris, France"},
    },
    "platforms": {"etsy": {"kind": "marketplace", "labels": ["etsy"]}},
}
QUERIES = {
    "de": {"precise": "braune Steppjacke Kapuze", "synonym": "Pufferjacke braun", "broad": "Steppjacke braun"},
    "fr": {"precise": "doudoune marron capuche", "broad": "doudoune marron"},
}


def settings(**changes):
    data = copy.deepcopy(BASE)
    data.update(changes)
    return discover.parse_settings(data)


# --- settings ----------------------------------------------------------------


def test_repository_settings_file_is_valid():
    loaded = discover.load_settings(REPO_ROOT / "discovery.toml")
    assert loaded.max_calls <= discover.HARD_MAX_CALLS
    assert set(loaded.markets) <= set(loaded.locales)
    assert loaded.locales["en-gb"].country == "uk"  # SerpApi's code for the United Kingdom
    with open(REPO_ROOT / "discovery.toml", "rb") as handle:
        assert "site_targets" in tomllib.load(handle)  # top-level, not inside a table


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"max_call": 5}, "unknown key"),
        ({"max_calls": 500}, "max_calls"),
        ({"markets": ["de-de", "es-es"]}, "no \\[locales.es-es\\]"),
        ({"markets": ["de"]}, "markets has an invalid value"),
        ({"locales": {"de-de": {"country": "de", "google_domain": "google.de"}}}, "missing key"),
        ({"steps": [{"query": "precise", "route": "shopping", "with_sites": True}]}, "with_sites needs"),
        ({"steps": [{"query": "exact", "route": "organic"}]}, "query must be one of"),
        ({"steps": [{"query": "broad", "route": "images"}]}, "route must be one of"),
        ({"modifiers": {"de": ["site:etsy.com"]}}, "modifiers.de"),
        ({"modifiers": {"de": ['hand" OR "x']}}, "modifiers.de"),
        ({"site_targets": ["etsy.com -foo"]}, "site_targets"),
        ({"locales": {"de-de": {"language": "de", "country": "de", "google_domain": "evil.com"}}}, "google_domain"),
        ({"platforms": {"shopx": {"kind": "shop", "labels": ["x1"]}}}, "kind must be one of"),
        ({"platforms": {"Bad Name": {"kind": "retailer", "labels": ["x1"]}}}, "platforms.Bad Name"),
    ],
)
def test_invalid_settings_are_rejected(changes, message):
    with pytest.raises(discover.SettingsError, match=message):
        settings(**changes)


def test_overrides():
    s = discover.apply_overrides(settings(), ["fr"], 2, no_modifiers=True, no_sites=False)
    assert s.markets == ("fr-fr",) and s.languages == ("fr",) and s.max_calls == 2
    assert not any(step.with_modifiers for step in s.steps)
    # A defined but not enabled market can be chosen by id; a language picks its enabled markets.
    assert discover.apply_overrides(settings(), ["de-at", "de"], None, False, False).markets == ("de-at", "de-de")
    with pytest.raises(discover.SettingsError):
        discover.apply_overrides(settings(), ["es"], None, False, False)
    with pytest.raises(discover.SettingsError):
        discover.apply_overrides(settings(), None, discover.HARD_MAX_CALLS + 1, False, False)


# --- plan ----------------------------------------------------------------------


def test_plan_interleaves_markets_and_cuts_at_budget():
    calls = discover.build_plan(settings(), QUERIES)
    summary = [(c.route, c.market, c.q, c.status) for c in calls]
    assert summary[:6] == [
        ("shopping", "de-de", "braune Steppjacke Kapuze", "planned"),
        ("shopping", "fr-fr", "doudoune marron capuche", "planned"),
        ("organic", "de-de", "Steppjacke braun handgemacht", "planned"),
        ("organic", "fr-fr", "doudoune marron fait main", "planned"),
        ("organic", "de-de", "Steppjacke braun Manufaktur", "planned"),
        ("organic", "de-de", "Steppjacke braun site:etsy.com", "planned"),
    ]
    assert [c.status for c in calls[6:]] == ["skipped_budget", "skipped_budget", "skipped_no_query"]
    assert sum(c.status == "planned" for c in calls) == 6


def test_plan_params_follow_the_locale():
    calls = discover.build_plan(settings(), QUERIES)
    assert calls[1].params == {
        "engine": "google_shopping", "q": "doudoune marron capuche", "gl": "fr", "hl": "fr",
        "google_domain": "google.fr", "location": "Paris, France",
    }
    assert "api_key" not in calls[1].params


def test_markets_of_one_language_share_its_queries():
    s = settings(markets=["de-de", "de-at"], steps=[{"query": "broad", "route": "shopping"}])
    calls = discover.build_plan(s, QUERIES)
    assert [(c.market, c.q, c.params["gl"], c.params["google_domain"]) for c in calls] == [
        ("de-de", "Steppjacke braun", "de", "google.de"),
        ("de-at", "Steppjacke braun", "at", "google.at"),
    ]
    assert s.countries("de") == ["de", "at"]


def test_identical_requests_are_planned_once():
    same = {"de": {"precise": "Steppjacke", "broad": "Steppjacke"}}
    s = settings(markets=["de-de"], steps=[{"query": "precise", "route": "organic"},
                                           {"query": "broad", "route": "organic"}])
    calls = discover.build_plan(s, same)
    assert [c.status for c in calls] == ["planned", "skipped_duplicate"]


# --- queries -------------------------------------------------------------------


def test_clean_queries_cleans_and_reports():
    queries, notes = discover.clean_queries(
        {"de": {"broad": " Steppjacke\x1b[2J  braun "}, "it": {"broad": "piumino"}}, ("de", "fr"))
    assert queries == {"de": {"broad": "Steppjacke [2J braun"}}
    assert notes and "it" in notes[0]
    with pytest.raises(discover.DiscoveryError, match="Unknown query kind"):
        discover.clean_queries({"de": {"exact": "x"}}, ("de",))
    with pytest.raises(discover.DiscoveryError, match="longer than"):
        discover.clean_queries({"de": {"broad": "x" * 500}}, ("de",))


def test_localization_reply_validation():
    reply = json.dumps({"de": {"precise": "a", "synonym": "b", "broad": "c"}})
    data, problems = validate_localization(reply, ["de"])
    assert problems == [] and data["de"]["broad"] == "c"
    data, problems = validate_localization(reply, ["de", "fr"])
    assert data is None and "Missing languages: ['fr']" in problems
    data, problems = validate_localization("```json\n{}\n```", ["de"])
    assert data is None and "not bare JSON" in problems[0]


def test_localization_prompt_sends_interpretation_but_not_uncertainties():
    interpretation = {"category": "puffer jacket", "observed": ["brown"], "requested_changes": [],
                      "must_have": [], "exclude": [], "uncertain": ["material"],
                      "queries": {"precise": "a", "synonym": "b", "broad": "c"}}
    prompt = localize_prompt(interpretation, {"de": ["de", "at"]})
    assert "puffer jacket" in prompt and "material" not in prompt
    assert '["de"]' in prompt and "German, for shops serving DE, AT" in prompt


# --- records and runs ------------------------------------------------------------


class FakeClient:
    """Stands in for SerpApiClient; answers from canned bodies, records params."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.params = []

    def account(self):
        return AccountStatus("Free Plan", 250, 240, 0, 50)

    def search(self, params):
        self.params.append(params)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return ProviderResponse(200, outcome, "sid", "Success", None, 0.1)


def organic(*links):
    return {"organic_results": [{"position": i, "title": f"r{i}", "link": link}
                                for i, link in enumerate(links, start=1)]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "data"
    config = tmp_path / "discovery.toml"
    config.write_text(
        'markets = ["de-de"]\nmax_calls = 3\n'
        '[[steps]]\nquery = "precise"\nroute = "organic"\n'
        '[[steps]]\nquery = "broad"\nroute = "organic"\n'
        '[[steps]]\nquery = "synonym"\nroute = "organic"\n'
        '[locales.de-de]\nlanguage = "de"\ncountry = "de"\ngoogle_domain = "google.de"\n',
        encoding="utf-8",
    )
    queries = tmp_path / "queries.json"
    queries.write_text(json.dumps({"de": QUERIES["de"]}), encoding="utf-8")
    monkeypatch.setattr(discover, "data_root", lambda: root)
    monkeypatch.setattr(discover, "serpapi_api_key", lambda: "test-key")
    return root, config, queries


def only_record(root):
    (directory,) = (root / "discovery").iterdir()
    return json.loads((directory / "record.json").read_text()), directory


def test_plan_only_sends_nothing(env, monkeypatch):
    root, config, queries = env
    monkeypatch.setattr(discover, "SerpApiClient", lambda key: pytest.fail("SerpApi was contacted"))
    assert discover.main(["--queries", str(queries), "--config", str(config), "--plan-only"]) == 0
    record, directory = only_record(root)
    assert record["status"] == "planned"
    assert json.loads((directory / "queries.json").read_text()) == {"de": QUERIES["de"]}


def test_full_run_saves_raw_leads_and_replays_offline(env, monkeypatch, capsys):
    root, config, queries = env
    fake = FakeClient(organic("https://a.de/p/1", "https://b.de/p/1"),
                      organic("https://a.de/p/1?utm_source=x"),
                      {"organic_results": []})
    monkeypatch.setattr(discover, "SerpApiClient", lambda key: fake)
    assert discover.main(["--queries", str(queries), "--config", str(config), "--yes"]) == 0

    record, directory = only_record(root)
    assert record["status"] == "completed"
    assert [c["status"] for c in record["calls"]] == ["ok", "ok", "empty"]
    assert [p["q"] for p in fake.params] == [QUERIES["de"][k] for k in ("precise", "broad", "synonym")]
    assert record["account_before"]["searches_left"] == 240
    assert [lead["url"] for lead in record["leads"]] == ["https://a.de/p/1", "https://b.de/p/1"]
    assert record["summary"]["duplicates_merged"] == 1
    assert sorted(p.name for p in (directory / "raw").iterdir()) == [
        "01-organic-de-de.json", "02-organic-de-de.json", "03-organic-de-de.json"]
    assert "test-key" not in (directory / "record.json").read_text()

    monkeypatch.setattr(discover, "SerpApiClient", lambda key: pytest.fail("replay used the network"))
    capsys.readouterr()
    assert discover.main(["--replay", directory.name[:8], "--config", str(config)]) == 0
    out = capsys.readouterr().out
    assert "no searches are spent" in out and "https://b.de/p/1" in out


def test_fatal_provider_error_stops_the_run_and_keeps_partial_results(env, monkeypatch):
    root, config, queries = env
    fake = FakeClient(organic("https://a.de/p/1"),
                      ProviderError("quota", "SerpApi limit reached (429)", 429, fatal=True))
    monkeypatch.setattr(discover, "SerpApiClient", lambda key: fake)
    assert discover.main(["--queries", str(queries), "--config", str(config), "--yes"]) == 0

    record, _ = only_record(root)
    assert record["status"] == "partial"
    assert [c["status"] for c in record["calls"]] == ["ok", "failed", "not_run"]
    assert len(fake.params) == 2
    assert len(record["leads"]) == 1


def test_plan_larger_than_remaining_quota_is_refused(env, monkeypatch):
    root, config, queries = env
    fake = FakeClient()
    fake.account = lambda: AccountStatus("Free Plan", 250, 2, 0, 50)
    monkeypatch.setattr(discover, "SerpApiClient", lambda key: fake)
    assert discover.main(["--queries", str(queries), "--config", str(config), "--yes"]) == 1
    assert fake.params == []


def test_from_record_reuses_queries(env, monkeypatch):
    root, config, queries = env
    assert discover.main(["--queries", str(queries), "--config", str(config), "--plan-only"]) == 0
    first, directory = only_record(root)
    assert discover.main(["--from-record", directory.name[:6], "--config", str(config), "--plan-only"]) == 0
    records = [json.loads((d / "record.json").read_text()) for d in (root / "discovery").iterdir()]
    second = next(r for r in records if r["id"] != first["id"])
    assert second["queries"] == first["queries"]
    assert second["source"] == {"kind": "record", "user_text": None, "from_record": first["id"]}


@pytest.mark.parametrize("ref", ["../..", "zz", "abc/def", "123"])
def test_record_references_are_validated(tmp_path, ref):
    (tmp_path / "discovery").mkdir()
    with pytest.raises(discover.DiscoveryError):
        discover.find_record(tmp_path, ref)


def test_record_prefix_must_be_unique(tmp_path):
    first = "abcd0000-0000-4000-8000-000000000001"
    for name in (first, "abcd0000-0000-4000-8000-000000000002"):
        (tmp_path / "discovery" / name).mkdir(parents=True)
    with pytest.raises(discover.DiscoveryError, match="matches 2 runs"):
        discover.find_record(tmp_path, "abcd")
    assert str(discover.find_record(tmp_path, first)) == first


def test_raw_file_names_from_a_record_are_validated(tmp_path):
    with pytest.raises(discover.DiscoveryError):
        discover.record_path(tmp_path, uuid.uuid4(), "../../../.env")
