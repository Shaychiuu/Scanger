"""Offline checks for the web discovery pages: HTML escaping, links and
thumbnails, filters and sorting, empty states, and the form helpers."""

import json

import pytest

from scanger import discovery_ui, discovery_view as view


def lead(**fields):
    base = {
        "call_index": 1, "route": "organic", "market": "de-de", "language": "de", "country": "de",
        "query_kind": "precise", "query": "braune Steppjacke", "position": 1, "title": "Steppjacke",
        "url": "https://shop.de/p/1", "url_kind": "page", "google_url": None, "key": "shop.de/p/1",
        "host": "www.shop.de", "site": "shop.de", "idn_host": False, "merchant": "Shop", "source_key": "shop",
        "platform": None, "platform_kind": None, "page_hint": None, "price": None, "price_value": None,
        "rating": None, "reviews": None, "delivery": None, "thumbnail": None, "snippet": None,
        "old_price": None, "condition": None, "extensions": [], "rank": 1, "over_soft_cap": False,
        "also_found": [],
    }
    return {**base, **fields}


def run(status="completed", leads=(), **fields):
    calls = [{"index": 1, "route": "organic", "market": "de-de", "query_kind": "precise", "q": "braune Steppjacke",
              "modifier": None, "site": None, "status": "ok", "result_count": 1, "duration_s": 0.5,
              "raw_file": "raw/01-organic-de-de.json", "note": None}]
    base = {"id": "3fa2c0de-0000-4000-8000-000000000000", "created_at": "2026-10-26T19:54:04+00:00",
            "status": status, "active": False, "source": {"kind": "queries"}, "settings": {"markets": ["de-de"]},
            "queries": {"de": {"precise": "braune Steppjacke"}}, "calls": calls, "leads": list(leads),
            "summary": None, "interpretation": None}
    return {**base, **fields}


# --- escaping and links -----------------------------------------------------------


def test_text_from_results_is_escaped_and_unsafe_links_dropped():
    evil = lead(title='<img src=x onerror="alert(1)">', merchant='"><script>alert(1)</script>',
                url="javascript:alert(1)", snippet="<b>bold</b>", extensions=["<i>SALE</i>"],
                thumbnail="https://evil.example/pixel.png", query='"><svg onload=alert(1)>')
    html = view.results_html(run(leads=[evil]), [evil], [evil])
    assert "<img src=x" not in html and "<script>" not in html and "<svg" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "javascript:" not in html and "evil.example" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html and "&lt;i&gt;SALE&lt;/i&gt;" in html


def test_links_open_safely_and_provider_thumbnails_load_without_referrer():
    item = lead(google_url="https://www.google.de/search?ibp=oshop&prds=catalogid:1&q=a b",
                thumbnail="https://encrypted-tbn0.gstatic.com/images?q=tbn:1", page_hint="product_like")
    html = view.results_html(run(leads=[item]), [item], [item])
    assert 'href="https://shop.de/p/1"' in html and "Open product page" in html
    assert "Google product page" in html and "catalogid:1&amp;q=a b" in html
    assert html.count('rel="noopener noreferrer nofollow"') == html.count("<a ")
    assert '<img src="https://encrypted-tbn0.gstatic.com/images?q=tbn:1"' in html
    assert 'referrerpolicy="no-referrer"' in html
    assert "<img" not in view.results_html(run(leads=[item]), [item], [item], thumbnails=False)


@pytest.mark.parametrize("url, link, thumbnail", [
    ("https://serpapi.com/images/url/abc", True, True),
    ("https://encrypted-tbn1.gstatic.com/x", True, True),
    ("http://serpapi.com/images/url/abc", True, False),
    ("https://serpapi.com.evil.example/x", True, False),
    ("https://shop.de/p.png", True, False),
    ("javascript:alert(1)", False, False),
    ("data:image/png;base64,AAAA", False, False),
    ("//shop.de/p", False, False),
    (None, False, False),
])
def test_safe_link_and_thumbnail(url, link, thumbnail):
    assert (view.safe_link(url) is not None) == link
    assert (view.safe_thumbnail(url) is not None) == thumbnail


def test_interpretation_from_the_model_is_escaped():
    record = run(interpretation={"status": "ok", "model": "m", "prompt_version": "v1", "duration_s": 1.0,
                                 "data": {"category": "<b>jacket</b>", "observed": ["<script>x</script>"],
                                          "requested_changes": ["fluffy hood"], "exclude": ["fur"]}})
    html = view.intent_html(record)
    assert "<script>" not in html and "&lt;b&gt;jacket&lt;/b&gt;" in html
    assert "fluffy hood" in html and "fur" in html


# --- what a lead shows ----------------------------------------------------------------


def test_card_shows_details_and_how_the_lead_was_found():
    item = lead(route="shopping", url=None, url_kind="google_product_page",
                google_url="https://www.google.de/search?ibp=oshop", price="38,00 €", old_price="59,00 €",
                rating=4.4, reviews=1312, delivery="Kostenlose Lieferung", condition="gebraucht",
                extensions=["SALE"], platform="vinted", platform_kind="second_hand", idn_host=True,
                also_found=[{"call_index": 3, "position": 2}])
    html = view.results_html(run(leads=[item]), [item], [item])
    for text in ("38,00 €*", "<s", "59,00 €", "★ 4.4 (1,312)", "Delivery: Kostenlose Lieferung",
                 "condition: gebraucht", "SALE", "second-hand", "no shop link", "check the domain spelling",
                 "Found by search 1: Shopping · de-de · precise query <q>braune Steppjacke</q> · result #1",
                 "also in search 3 #2", view.UNVERIFIED):
        assert text in html, text


def test_sources_over_the_cap_come_after_a_divider_only_in_rank_order():
    items = [lead(rank=1), lead(rank=2, key="b", over_soft_cap=True)]
    assert "over the soft cap" in view.results_html(run(leads=items), items, items)
    assert "over the soft cap" not in view.results_html(run(leads=items), items, items, sort="price_up")


@pytest.mark.parametrize("status, leads, shown, message", [
    ("running", [], [], "Searching"),
    ("completed", [], [], "This does not mean nothing exists"),
    ("completed", [lead()], [], "No leads match these filters."),
])
def test_empty_states(status, leads, shown, message):
    assert message in view.results_html(run(status, leads), leads, shown)


def test_a_planned_run_shows_its_plan_instead_of_leads():
    record = run("planned")
    record["calls"][0].update(status="planned", raw_file=None)
    record["calls"].append({**record["calls"][0], "index": 2, "status": "skipped_budget", "note": "over max_calls"})
    html = view.results_html(record, [], [])
    assert "The plan: 1 search" in html and "1 more not sent" in html
    assert "not sent: over the budget" in html


# --- filters ---------------------------------------------------------------------------


ITEMS = [
    lead(rank=1, key="a", title="Steppjacke braun", merchant="Zalando", price_value=89.0, page_hint="product_like"),
    lead(rank=2, key="b", route="shopping", url=None, merchant="Vinted", platform_kind="second_hand",
         price_value=38.0, market="de-at"),
    lead(rank=3, key="c", title="Jacken", merchant="Otto", page_hint="category_like", snippet="flauschige Kapuze"),
]


@pytest.mark.parametrize("f, keys", [
    (view.LeadFilter(), ["a", "b", "c"]),
    (view.LeadFilter(text="KAPUZE"), ["c"]),
    (view.LeadFilter(text="steppjacke zalando"), ["a"]),
    (view.LeadFilter(route="shopping"), ["b"]),
    (view.LeadFilter(market="de-at"), ["b"]),
    (view.LeadFilter(kind="unclassified"), ["a", "c"]),
    (view.LeadFilter(no_listings=True), ["a", "b"]),
    (view.LeadFilter(shop_link=True), ["a", "c"]),
    (view.LeadFilter(sort="price_up"), ["b", "a", "c"]),
    (view.LeadFilter(sort="price_down"), ["a", "b", "c"]),
    (view.LeadFilter(sort="source"), ["c", "b", "a"]),
])
def test_filters_and_sorting(f, keys):
    assert [item["key"] for item in view.filter_leads(ITEMS, f)] == keys


def test_filter_choices_count_leads():
    choices = view.filter_choices(run(settings={"markets": ["de-de", "de-at"]}), ITEMS)
    assert choices["route"] == [("All (3)", "all"), ("Shopping (1)", "shopping"), ("Web (2)", "organic")]
    assert choices["market"] == [("All markets", "all"), ("de-de (2)", "de-de"), ("de-at (1)", "de-at")]
    assert ("second-hand (1)", "second_hand") in choices["kind"]


# --- overview, summary, list -------------------------------------------------------------


def test_overview_of_a_plan_warns_when_the_quota_is_short():
    record = run("planned")
    record["calls"][0].update(status="planned")
    short = {"plan_name": "Free Plan", "searches_left": 0, "this_hour_searches": 0, "hourly_limit": 50}
    html = view.overview_html(record, [], None, short)
    assert "Nothing has been sent to SerpApi yet" in html
    assert "sd-warn" in html and "needs more searches than are left" in html
    assert "sd-warn" not in view.overview_html(record, [], None, {**short, "searches_left": 5})


def test_overview_of_a_running_run_shows_progress():
    record = run("running", active=True)
    record["calls"].append({**record["calls"][0], "index": 2, "status": "planned", "q": "Steppjacke"})
    html = view.overview_html(record, [lead()], None)
    assert 'style="width:50%"' in html and "1 of 2 searches finished" in html and "Steppjacke" in html


def test_summary_of_an_older_record_without_newer_keys():
    old = {"leads": 1, "duplicates_merged": 0, "distinct_sources": 1, "distinct_sites": 1, "top_source": "shop",
           "top_source_share": 1.0, "by_route": {"organic": 1}, "by_market": {"de-de": 1},
           "by_platform_kind": {"unclassified": 1}, "rejected": 0, "new_sources_per_call": []}
    html = view.summary_html(old)
    assert "1 distinct sources" in html and "Web 1" in html and "Results" not in html


def test_run_labels():
    item = {"status": "completed", "created_at": "2026-10-26T19:54:04+00:00", "leads": 1,
            "first_query": "braune Steppjacke " * 5, "image_name": None}
    label = view.run_label(item)
    assert label.startswith("✓ ") and "1 lead ·" in label and label.endswith("…")
    assert " planned · " in view.run_label({**item, "status": "planned"})


# --- form helpers -------------------------------------------------------------------------


def test_query_table_round_trip():
    rows = discovery_ui.query_rows({"fr": {"precise": "doudoune"}}, ["de", "fr"])
    assert rows == [["de", "", "", ""], ["fr", "doudoune", "", ""]]
    edited = rows + [[" IT ", " giacca ", None, float("nan")], ["", "", "", ""]]
    assert discovery_ui.rows_to_queries(edited) == {"fr": {"precise": "doudoune"}, "it": {"precise": "giacca"}}
    with pytest.raises(ValueError, match="language code"):
        discovery_ui.rows_to_queries([["", "jacket", "", ""]])
    assert discovery_ui.add_language_rows([["de", "x", "", ""], ["", "", "", ""]], ["de", "fr"]) == [
        ["de", "x", "", ""], ["fr", "", "", ""]]


def test_queries_file_is_checked_before_use(tmp_path):
    good = tmp_path / "q.json"
    good.write_text(json.dumps({"de": {"precise": "Steppjacke"}}), encoding="utf-8")
    assert discovery_ui.read_queries_file(str(good)) == {"de": {"precise": "Steppjacke"}}
    for content, message in [("{", "not valid JSON"), ('["de"]', "wrong shape"),
                             ('{"de": {"exact": "x"}}', "Unknown query kind de.exact"),
                             (" " * 100_001, "larger than")]:
        good.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            discovery_ui.read_queries_file(str(good))


def test_reference_image_only_for_a_stored_asset_id():
    record = run(source={"kind": "image", "image": {"name": "jacket.png", "asset_id": "../../etc/passwd"}})
    assert discovery_ui.reference_asset(record) == (None, None)
    asset = "0b7c5f1e-3a7a-4c55-9c39-2f1a3f0d9e11"
    record["source"]["image"]["asset_id"] = asset
    assert discovery_ui.reference_asset(record) == (asset, "jacket.png")


def test_signature_changes_with_progress():
    record = run("running")
    before = discovery_ui.run_signature(record)
    assert discovery_ui.run_signature(run("running")) == before
    assert discovery_ui.run_signature({**record, "leads": [lead()]}) != before
