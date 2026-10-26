"""Offline checks for lead normalization: URL safety, identities, interleaving."""

import pytest

from scanger.leads import (
    CallResult,
    LeadSettings,
    PlatformRule,
    UrlRejected,
    build_leads,
    check_url,
    clean_text,
    match_platform,
    page_hint,
    provider_thumbnail,
    source_key,
    unwrap_google_redirect,
)

RULES = (
    PlatformRule("etsy", "marketplace", ("etsy",)),
    PlatformRule("ebay", "marketplace", ("ebay",)),
    PlatformRule("otto", "marketplace", ("otto",)),
    PlatformRule("pinterest", "social", ("pinterest",)),
)
SETTINGS = LeadSettings(max_leads_per_call=10, soft_cap_per_source=2, soft_cap_per_marketplace=3, platforms=RULES)


# --- text and URLs -------------------------------------------------------------


def test_clean_text_strips_terminal_escapes_and_bidi_overrides():
    assert clean_text("Coat\x1b[2J\x1b]0;pwned\x07 \u202egnp.exe\n") == "Coat [2J ]0;pwned gnp.exe"
    assert clean_text("  ") is None
    assert clean_text(42) is None
    assert clean_text("x" * 500, 10) == "x" * 10


@pytest.mark.parametrize(
    "url, reason",
    [
        ("javascript:alert(1)", "scheme"),
        ("data:text/html,<b>x</b>", "scheme"),
        ("ftp://shop.de/file", "scheme"),
        ("https://etsy.com@evil.example/listing/1", "credentials"),
        ("http://127.0.0.1/admin", "IP address"),
        ("http://[::1]/", "IP address"),
        ("http://192.168.1.1/", "IP address"),
        ("http://localhost:8010/sessions", "non-standard port"),
        ("http://localhost/sessions", "no public domain suffix"),
        ("https://printer.local/", "no public domain suffix"),
        ("https://shop.de:8443/p/1", "non-standard port"),
        ("https://shop.de/a b", "whitespace"),
        ("https://shop.de/\u202ep/1", "control"),
        ("https://shop.de/\x1b[31m", "control"),
        ("", "missing"),
        (None, "missing"),
        ("https://shop.de/" + "a" * 3000, "too long"),
    ],
)
def test_unsafe_urls_are_rejected(url, reason):
    with pytest.raises(UrlRejected, match=reason):
        check_url(url)


def test_tracking_params_and_fragment_removed_but_variant_kept():
    checked = check_url("https://WWW.Shop.de/products/coat/?variant=123&utm_source=g&srsltid=AbC&color=Braun%20Hell#reviews")
    assert checked.url == "https://www.shop.de/products/coat/?variant=123&color=Braun%20Hell"
    assert checked.key == "shop.de/products/coat?color=Braun%20Hell&variant=123"
    assert (checked.site, checked.site_label) == ("shop.de", "shop")


def test_registrable_domain_uses_public_suffix_list():
    assert check_url("https://www.zalando.co.uk/x").site == "zalando.co.uk"
    assert check_url("https://my-label.myshopify.com/products/a").site == "my-label.myshopify.com"


def test_lookalike_unicode_host_is_shown_as_punycode():
    checked = check_url("https://\u0435tsy.com/listing/1")  # Cyrillic "е"
    assert checked.host.startswith("xn--") and checked.idn
    assert match_platform(checked.site_label, None, RULES) is None


def test_google_redirect_is_unwrapped_once():
    wrapped = check_url("https://www.google.com/url?q=https://shop.de/p/1?utm_medium=x&sa=U")
    assert unwrap_google_redirect(wrapped).url == "https://shop.de/p/1"
    nested = check_url("https://www.google.de/url?q=https://www.google.com/url?q=https://shop.de/")
    with pytest.raises(UrlRejected):
        unwrap_google_redirect(nested)


def test_only_provider_hosted_thumbnails_are_kept():
    assert provider_thumbnail("https://serpapi.com/searches/1/images/a.png")
    assert provider_thumbnail("https://encrypted-tbn0.gstatic.com/images?q=tbn:x")
    assert provider_thumbnail("https://cdn.shop.de/coat.jpg") is None
    assert provider_thumbnail("http://serpapi.com/x.png") is None
    assert provider_thumbnail("data:image/png;base64,AAAA") is None


@pytest.mark.parametrize(
    "url, hint",
    [
        ("https://shop.de/products/brown-coat", "product_like"),
        ("https://www.etsy.com/de/listing/123/coat", "product_like"),
        ("https://shop.de/collections/coats", "category_like"),
        ("https://shop.de/search?q=coat", "category_like"),
        ("https://blog.de/2025/best-coats", None),
    ],
)
def test_page_hints(url, hint):
    assert page_hint(url) == hint


# --- identities --------------------------------------------------------------


def test_platform_matching_by_domain_or_merchant_name_start():
    assert match_platform("etsy", None, RULES).name == "etsy"
    assert match_platform(None, "Etsy", RULES).name == "etsy"
    assert match_platform(None, "eBay - vintage42", RULES).name == "ebay"
    assert match_platform(None, "Otto Fashion Store", RULES) is None
    assert match_platform(None, "OTTO", RULES).name == "otto"


def test_source_keys():
    ebay = RULES[1]
    assert source_key(None, "eBay - Vintage 42", ebay) == "ebay:vintage42"
    assert source_key("ebay", "eBay", ebay) == "ebay"
    assert source_key("zalando", "Zalando", None) == "zalando"
    assert source_key(None, "Zalando.de", None) == "zalando"
    assert source_key(None, "Atelier Mira", None) == "ateliermira"


# --- combining calls ---------------------------------------------------------------


def organic(*links):
    return {"organic_results": [{"position": i, "title": f"t{i}", "link": link, "source": "x"}
                                for i, link in enumerate(links, start=1)]}


def call(index, body, route="organic", language="de"):
    return CallResult(index=index, route=route, market=f"{language}-{language}", language=language,
                      country=language, query_kind="precise", query="q", body=body)


def test_round_robin_interleaving_and_deduplication():
    calls = [
        call(1, organic("https://a.de/p/1", "https://b.de/p/1")),
        call(2, organic("https://c.fr/p/1", "https://www.a.de/p/1/?utm_source=x"), language="fr"),
    ]
    leads, summary = build_leads(calls, SETTINGS)
    assert [lead.url for lead in leads] == ["https://a.de/p/1", "https://c.fr/p/1", "https://b.de/p/1"]
    assert leads[0].also_found == [{"call_index": 2, "position": 2}]
    assert summary["duplicates_merged"] == 1
    assert [c["new_sources"] for c in summary["new_sources_per_call"]] == [2, 1]


def test_soft_cap_moves_extra_results_to_the_end_without_dropping():
    body = organic("https://a.de/p/1", "https://a.de/p/2", "https://a.de/p/3", "https://b.de/p/1")
    leads, summary = build_leads([call(1, body)], SETTINGS)
    assert [lead.url for lead in leads] == [
        "https://a.de/p/1", "https://a.de/p/2", "https://b.de/p/1", "https://a.de/p/3"]
    assert leads[-1].over_soft_cap and summary["over_soft_cap"] == 1


def test_marketplace_without_seller_gets_the_higher_cap():
    body = organic(*(f"https://www.etsy.com/de/listing/{i}/x" for i in range(5)))
    leads, _ = build_leads([call(1, body)], SETTINGS)
    assert [lead.over_soft_cap for lead in leads] == [False, False, False, True, True]
    assert {lead.platform_kind for lead in leads} == {"marketplace"}


def test_shopping_result_without_shop_url_keeps_google_page_and_merchant():
    body = {"shopping_results": [{
        "position": 1, "title": "Steppjacke\x1b[31m", "product_id": "42",
        "product_link": "https://www.google.de/search?ibp=oshop&prds=catalogid:42",
        "source": "eBay - vintage42", "price": "89,95 €", "extracted_price": 89.95,
        "rating": 4.5, "reviews": 12, "delivery": "Kostenlose Lieferung",
        "serpapi_thumbnail": "https://serpapi.com/images/url/abc",
    }]}
    leads, summary = build_leads([call(1, body, route="shopping")], SETTINGS)
    lead = leads[0]
    assert lead.url is None and lead.url_kind == "google_product_page"
    assert lead.google_url.startswith("https://www.google.de/search")
    assert (lead.source_key, lead.platform_kind) == ("ebay:vintage42", "marketplace")
    assert (lead.price, lead.price_value, lead.rating, lead.reviews) == ("89,95 €", 89.95, 4.5, 12)
    assert lead.title == "Steppjacke [31m"
    assert summary["without_page_url"] == 1


def test_shopping_product_link_must_be_google():
    body = {"shopping_results": [{"position": 1, "title": "x", "product_link": "https://evil.example/x"}]}
    leads, summary = build_leads([call(1, body, route="shopping")], SETTINGS)
    assert leads == [] and summary["rejected"] == 1


def test_rejected_results_are_counted_with_reasons():
    body = organic("javascript:alert(1)", "https://ok.de/p/1")
    leads, summary = build_leads([call(1, body)], SETTINGS)
    assert len(leads) == 1
    assert summary["rejections"][0]["reason"].startswith("scheme")


def test_max_leads_per_call_limits_items():
    body = organic(*(f"https://s{i}.de/p/1" for i in range(20)))
    leads, _ = build_leads([call(1, body)], SETTINGS)
    assert len(leads) == SETTINGS.max_leads_per_call
