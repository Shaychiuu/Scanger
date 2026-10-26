"""Turn raw search responses into normalized, deduplicated discovery leads.

Everything here is offline and deterministic, so saved raw responses can be
normalized again ("replayed") after changing this code or discovery.toml
without spending searches.

All provider data is untrusted. Text is stripped of control and formatting
characters (terminal escapes, bidi overrides) and truncated. A URL becomes a
lead only if it is a public http(s) address without credentials or unusual
ports; IP-literal and suffix-less hosts (localhost, *.local) are rejected.
Only provider-hosted thumbnail URLs are kept, and nothing here fetches them.
Prices, ratings and delivery text are search-result claims, never verified.
"""

import ipaddress
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, unquote_plus, urlsplit, urlunsplit

import tldextract

# Bundled Public Suffix List snapshot only: no download, no cache files.
_EXTRACT = tldextract.TLDExtract(
    cache_dir=None, suffix_list_urls=(), include_psl_private_domains=True
)

MAX_URL_LENGTH = 2048
MAX_TITLE_LENGTH = 300
MAX_SHORT_TEXT = 120

TRACKING_PARAMS = frozenset({
    "gclid", "gclsrc", "dclid", "gbraid", "wbraid", "fbclid", "msclkid", "yclid",
    "twclid", "ttclid", "igshid", "srsltid", "mc_cid", "mc_eid", "_ga", "_gl",
    "mkt_tok", "spm", "ref", "ref_",
})
TRACKING_PREFIXES = ("utm_",)

PRODUCT_PATH = re.compile(
    r"/(products?|produkte?|produit|prodotto|artikel|articolo|item|itm|listing|dp|p)/[^/]",
    re.IGNORECASE,
)
CATEGORY_PATH = re.compile(
    r"/(collections?|category|categories|kategorie|categorie|categoria|c|search|s)(/|$)",
    re.IGNORECASE,
)

_UNSAFE_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}


class UrlRejected(ValueError):
    pass


@dataclass(frozen=True)
class PlatformRule:
    name: str
    kind: str  # marketplace | second_hand | social | aggregator | retailer
    labels: tuple[str, ...]


@dataclass(frozen=True)
class CheckedUrl:
    url: str  # tracking parameters and fragment removed, host lower-case ASCII
    key: str  # deduplication key (no scheme, no "www.", no trailing slash)
    host: str
    site: str  # registrable domain, e.g. zalando.co.uk
    site_label: str  # e.g. zalando
    idn: bool  # host has punycode labels; the displayed name may imitate another


@dataclass(frozen=True)
class CallResult:
    """One saved provider response with the plan context it was requested in."""

    index: int
    route: str
    market: str  # e.g. "de-at"
    language: str
    country: str
    query_kind: str
    query: str
    body: dict[str, Any]


@dataclass
class Lead:
    call_index: int
    route: str
    market: str
    language: str
    country: str
    query_kind: str
    query: str
    position: int
    title: str | None
    url: str | None  # retailer page; None when the provider gave none
    url_kind: str  # "page" | "google_product_page"
    google_url: str | None
    key: str
    host: str | None
    site: str | None
    idn_host: bool
    merchant: str | None  # name the provider displayed
    source_key: str  # diversity unit
    platform: str | None
    platform_kind: str | None
    page_hint: str | None  # "product_like" | "category_like" | None
    price: str | None
    price_value: float | None
    rating: float | None
    reviews: int | None
    delivery: str | None
    thumbnail: str | None
    rank: int = 0
    over_soft_cap: bool = False
    also_found: list[dict[str, int]] = field(default_factory=list)


# --- text and URLs -------------------------------------------------------------


def clean_text(value: Any, limit: int = MAX_SHORT_TEXT) -> str | None:
    """Printable single-line text, or None. Removes control/format characters."""
    if not isinstance(value, str):
        return None
    text = "".join(" " if unicodedata.category(ch) in _UNSAFE_CATEGORIES else ch for ch in value)
    text = " ".join(text.split())
    return text[:limit] or None


def _is_tracking(name: str) -> bool:
    name = name.lower()
    return name in TRACKING_PARAMS or name.startswith(TRACKING_PREFIXES)


def check_url(raw: Any) -> CheckedUrl:
    """Validate and normalize a result URL; raise UrlRejected with a reason."""
    if not isinstance(raw, str) or not raw:
        raise UrlRejected("missing URL")
    if len(raw) > MAX_URL_LENGTH:
        raise UrlRejected("URL too long")
    if any(ord(ch) < 33 or ord(ch) == 127 or unicodedata.category(ch) in _UNSAFE_CATEGORIES | {"Zs"}
           for ch in raw):
        raise UrlRejected("whitespace or control characters in URL")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise UrlRejected("malformed URL") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UrlRejected(f"scheme {scheme or 'missing'!r} not allowed")
    if "@" in parts.netloc:
        raise UrlRejected("credentials in URL")
    if port is not None and (scheme, port) not in (("http", 80), ("https", 443)):
        raise UrlRejected("non-standard port")
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise UrlRejected("missing host")
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise UrlRejected("invalid host name") from None
    try:
        ipaddress.ip_address(ascii_host)
    except ValueError:
        pass
    else:
        raise UrlRejected("IP address instead of a domain")
    ext = _EXTRACT(ascii_host)
    if not ext.suffix or not ext.domain:
        raise UrlRejected("host has no public domain suffix")

    # Filter raw "k=v" segments so the remaining ones keep their original encoding.
    kept = [seg for seg in parts.query.split("&")
            if seg and not _is_tracking(unquote_plus(seg.partition("=")[0]))]
    query = "&".join(kept)
    path = parts.path or "/"
    url = urlunsplit((scheme, ascii_host, path, query, ""))
    key_host = ascii_host[4:] if ascii_host.startswith("www.") else ascii_host
    key = key_host + (path.rstrip("/") or "/") + ("?" + "&".join(sorted(kept)) if kept else "")
    return CheckedUrl(
        url=url,
        key=key,
        host=ascii_host,
        site=ext.top_domain_under_public_suffix,
        site_label=ext.domain,
        idn=any(label.startswith("xn--") for label in ascii_host.split(".")),
    )


def unwrap_google_redirect(checked: CheckedUrl) -> CheckedUrl:
    """google.*/url?q=<target> -> the target (one level only)."""
    if checked.site_label != "google" or urlsplit(checked.url).path != "/url":
        return checked
    params = dict(parse_qsl(urlsplit(checked.url).query))
    target = params.get("q") or params.get("url")
    inner = check_url(target)
    if inner.site_label == "google" and urlsplit(inner.url).path == "/url":
        raise UrlRejected("nested Google redirect")
    return inner


def provider_thumbnail(raw: Any) -> str | None:
    """Keep thumbnails hosted by SerpApi or Google's image CDN; drop all others."""
    try:
        checked = check_url(raw)
    except UrlRejected:
        return None
    if not checked.url.startswith("https://"):
        return None
    if checked.host == "serpapi.com" or checked.host.endswith(".gstatic.com"):
        return checked.url
    return None


def page_hint(url: str) -> str | None:
    parts = urlsplit(url)
    if PRODUCT_PATH.search(parts.path):
        return "product_like"
    if CATEGORY_PATH.search(parts.path) or any(k in ("q", "query", "search") for k, _ in parse_qsl(parts.query)):
        return "category_like"
    return None


# --- identities --------------------------------------------------------------


_SEPARATOR = re.compile(r"\s+[-–|]\s+")


def _norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


def _merchant_label(merchant: str) -> str | None:
    """'Zalando.de' or 'Amazon.de - Seller' -> 'zalando' / 'amazon'; plain names -> None."""
    first = _SEPARATOR.split(merchant, maxsplit=1)[0].strip().lower()
    if not first or " " in first:
        return None
    ext = _EXTRACT(first)
    return ext.domain if ext.suffix and ext.domain else None


def match_platform(site_label: str | None, merchant: str | None,
                   rules: tuple[PlatformRule, ...]) -> PlatformRule | None:
    """Match by the result's domain, else by the merchant name's first part
    ("Etsy", "eBay - shop42", "Amazon.de"). "Otto Fashion Store" is not Otto."""
    names = set()
    if merchant:
        names = {_norm(_SEPARATOR.split(merchant, maxsplit=1)[0]), _merchant_label(merchant)}
    for rule in rules:
        if site_label and site_label in rule.labels:
            return rule
        if names & set(rule.labels):
            return rule
    return None


def source_key(site_label: str | None, merchant: str | None, platform: PlatformRule | None) -> str:
    """The unit used for diversity counts and soft caps.

    A site counts once (zalando.de and zalando.fr are both "zalando"). On a
    marketplace, a seller named after a separator ("eBay - vintageshop42") is
    kept as a separate source ("ebay:vintageshop42").
    """
    if platform is not None:
        if platform.kind == "marketplace" and merchant:
            parts = _SEPARATOR.split(merchant, maxsplit=1)
            if len(parts) == 2 and _norm(parts[1]):
                return f"{platform.name}:{_norm(parts[1])}"
        return platform.name
    label = site_label or (_merchant_label(merchant) if merchant else None)
    if label:
        return label
    return _norm(merchant or "") or "unknown"


# --- per-route extraction ----------------------------------------------------------


def _number(value: Any, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if low <= value <= high else None


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def result_items(route: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    key = "shopping_results" if route == "shopping" else "organic_results"
    items = body.get(key)
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _rich_snippet_extensions(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("rich_snippet")
    if not isinstance(snippet, dict):
        return {}
    for part in ("top", "bottom"):
        section = snippet.get(part)
        if isinstance(section, dict) and isinstance(section.get("detected_extensions"), dict):
            return section["detected_extensions"]
    return {}


def lead_from_item(call: CallResult, item: dict[str, Any], position: int,
                   rules: tuple[PlatformRule, ...]) -> Lead:
    """Build one lead; raise UrlRejected if the item has no acceptable URL."""
    merchant = clean_text(item.get("source"))
    google_url = None
    page: CheckedUrl | None = None

    if call.route == "shopping":
        if item.get("link"):
            candidate = unwrap_google_redirect(check_url(item.get("link")))
            if candidate.site_label != "google":
                page = candidate
        if item.get("product_link"):
            google = check_url(item.get("product_link"))
            if google.site_label != "google":
                raise UrlRejected("product_link is not a Google URL")
            google_url = google.url
        if page is None and google_url is None:
            raise UrlRejected("no product link")
        price = clean_text(item.get("price"))
        price_value = _number(item.get("extracted_price"), 0, 1e7)
        rating = _number(item.get("rating"), 0, 5)
        reviews = _count(item.get("reviews"))
        delivery = clean_text(item.get("delivery"))
        thumbnail = provider_thumbnail(item.get("serpapi_thumbnail")) or provider_thumbnail(item.get("thumbnail"))
    else:
        page = unwrap_google_redirect(check_url(item.get("link")))
        ext = _rich_snippet_extensions(item)
        value = _number(ext.get("price"), 0, 1e7)
        currency = clean_text(ext.get("currency"), 10)
        price = f"{ext['price']} {currency or ''}".strip() if value is not None else None
        price_value = value
        rating = _number(ext.get("rating"), 0, 5)
        reviews = _count(ext.get("reviews"))
        delivery = None
        thumbnail = provider_thumbnail(item.get("thumbnail"))

    site_label = page.site_label if page else None
    platform = match_platform(site_label, merchant, rules)
    if page is not None:
        key = page.key
    else:
        product_id = clean_text(item.get("product_id"), 100) or ""
        key = f"shopping:{product_id}:{_norm(merchant or '')}"
    return Lead(
        call_index=call.index,
        route=call.route,
        market=call.market,
        language=call.language,
        country=call.country,
        query_kind=call.query_kind,
        query=call.query,
        position=position,
        title=clean_text(item.get("title"), MAX_TITLE_LENGTH),
        url=page.url if page else None,
        url_kind="page" if page else "google_product_page",
        google_url=google_url,
        key=key,
        host=page.host if page else None,
        site=page.site if page else None,
        idn_host=page.idn if page else False,
        merchant=merchant,
        source_key=source_key(site_label, merchant, platform),
        platform=platform.name if platform else None,
        platform_kind=platform.kind if platform else None,
        page_hint=page_hint(page.url) if page else None,
        price=price,
        price_value=price_value,
        rating=rating,
        reviews=reviews,
        delivery=delivery,
        thumbnail=thumbnail,
    )


# --- combining calls ---------------------------------------------------------------


@dataclass(frozen=True)
class LeadSettings:
    max_leads_per_call: int
    soft_cap_per_source: int
    # Marketplace results without a known seller may come from many sellers.
    soft_cap_per_marketplace: int
    platforms: tuple[PlatformRule, ...]


def build_leads(calls: list[CallResult], settings: LeadSettings) -> tuple[list[Lead], dict[str, Any]]:
    """Normalize, interleave, deduplicate and soft-cap leads from saved calls.

    Calls are interleaved round-robin by result position (every call's #1,
    then every call's #2, ...) so no single route or language dominates the
    top. Duplicates keep their first occurrence and remember the others.
    Sources over their soft cap move to the end; they are never dropped.
    """
    per_call: list[list[Lead]] = []
    rejections: list[dict[str, Any]] = []
    for call in calls:
        leads = []
        for offset, item in enumerate(result_items(call.route, call.body)[: settings.max_leads_per_call]):
            position = _count(item.get("position")) or offset + 1
            try:
                leads.append(lead_from_item(call, item, position, settings.platforms))
            except UrlRejected as exc:
                rejections.append({
                    "call_index": call.index,
                    "position": position,
                    "reason": str(exc),
                    "title": clean_text(item.get("title")),
                })
        per_call.append(leads)

    seen: dict[str, Lead] = {}
    ordered: list[Lead] = []
    for depth in range(max((len(leads) for leads in per_call), default=0)):
        for leads in per_call:
            if depth >= len(leads):
                continue
            lead = leads[depth]
            first = seen.get(lead.key)
            if first is not None:
                first.also_found.append({"call_index": lead.call_index, "position": lead.position})
                continue
            seen[lead.key] = lead
            ordered.append(lead)

    counts: Counter[str] = Counter()
    kept, overflow = [], []
    for lead in ordered:
        unknown_seller = lead.platform_kind == "marketplace" and ":" not in lead.source_key
        cap = settings.soft_cap_per_marketplace if unknown_seller else settings.soft_cap_per_source
        if counts[lead.source_key] >= cap:
            lead.over_soft_cap = True
            overflow.append(lead)
        else:
            kept.append(lead)
        counts[lead.source_key] += 1
    final = kept + overflow
    for rank, lead in enumerate(final, start=1):
        lead.rank = rank
    return final, summarize(final, per_call, calls, rejections)


def summarize(leads: list[Lead], per_call: list[list[Lead]], calls: list[CallResult],
              rejections: list[dict[str, Any]]) -> dict[str, Any]:
    sources = Counter(lead.source_key for lead in leads)
    top_source, top_count = sources.most_common(1)[0] if sources else (None, 0)
    seen: set[str] = set()
    new_per_call = []
    for call, call_leads in zip(calls, per_call):
        keys = {lead.source_key for lead in call_leads}
        new_per_call.append({"call_index": call.index, "leads": len(call_leads), "new_sources": len(keys - seen)})
        seen |= keys
    return {
        "leads": len(leads),
        "duplicates_merged": sum(len(lead.also_found) for lead in leads),
        "distinct_sources": len(sources),
        "distinct_sites": len({lead.site for lead in leads if lead.site}),
        "top_source": top_source,
        "top_source_share": round(top_count / len(leads), 2) if leads else None,
        "by_route": dict(Counter(lead.route for lead in leads)),
        "by_market": dict(Counter(lead.market for lead in leads)),
        "by_platform_kind": dict(Counter(lead.platform_kind or "unclassified" for lead in leads)),
        "without_page_url": sum(1 for lead in leads if lead.url is None),
        "idn_hosts": sum(1 for lead in leads if lead.idn_host),
        "over_soft_cap": sum(1 for lead in leads if lead.over_soft_cap),
        "rejected": len(rejections),
        "rejections": rejections[:50],
        "new_sources_per_call": new_per_call,
    }
