"""HTML for the web discovery tab, built from saved discovery records.

Pure functions: record in, HTML out. Every text in a record comes from a search
provider, an LLM or the owner and is escaped here. Links must be http(s), and
thumbnails HTTPS on SerpApi or Google's image CDN, as scanger.leads keeps them;
the browser loads those thumbnails directly, without a referrer.
"""

import html
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

ROUTES = {"shopping": "Shopping", "organic": "Web"}
KINDS = {
    "marketplace": "marketplace", "retailer": "retailer", "second_hand": "second-hand",
    "aggregator": "aggregator", "social": "social", "unclassified": "unclassified",
}
STATUS = {
    "preparing": ("preparing", "Writing the queries."),
    "planned": ("planned", "Nothing has been sent to SerpApi yet. Review the plan below, then run it."),
    "running": ("running", "Searching. Leads appear as searches finish."),
    "completed": ("completed", "All planned searches ran."),
    "partial": ("partial", "Some searches failed or were not sent; the leads come from the others."),
    "failed": ("failed", "No search completed."),
    "cancelled": ("stopped", "Stopped before all searches ran; leads from the finished ones are kept."),
}
STATUS_ICONS = {"preparing": "…", "planned": "○", "running": "▶", "completed": "✓",
                "partial": "◐", "failed": "✗", "cancelled": "■"}
SKIPPED = ("skipped_budget", "skipped_no_query", "skipped_duplicate")
DONE = ("ok", "empty")
QUERY_KINDS = ("precise", "synonym", "broad")
SORTS = [
    ("Sort by rank", "rank"),
    ("Cheapest first", "price_up"),
    ("Most expensive first", "price_down"),
    ("Sort by source", "source"),
]
FLAGS = [
    ("Hide listing pages", "no_listings"),
    ("Only with a shop link", "shop_link"),
    ("Show thumbnails", "thumbnails"),
]
EXTERNAL = 'target="_blank" rel="noopener noreferrer nofollow" referrerpolicy="no-referrer"'
UNVERIFIED = "Prices, ratings and delivery are what Google showed in the results; nothing was checked."


# --- small helpers ---------------------------------------------------------------


def esc(value: Any) -> str:
    return "" if value is None else html.escape(str(value), quote=True)


def safe_link(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    return url if parts.scheme in ("http", "https") and parts.hostname else None


def safe_thumbnail(url: Any) -> str | None:
    link = safe_link(url)
    if link is None or not link.startswith("https://"):
        return None
    host = urlsplit(link).hostname or ""
    return link if host == "serpapi.com" or host.endswith(".gstatic.com") else None


def when(iso: str | None, short: bool = False) -> str:
    if not iso:
        return "?"
    try:
        moment = datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return "?"
    return moment.strftime("%d %b %H:%M" if short else "%d %b %Y, %H:%M")


def clip(text: Any, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _badge(text: str, kind: str = "", tip: str = "") -> str:
    title = f' title="{esc(tip)}"' if tip else ""
    return f'<span class="sd-badge {kind}"{title}>{esc(text)}</span>'


def _chips(values: list[Any], kind: str = "") -> str:
    return "".join(f'<span class="sd-chip {kind}">{esc(v)}</span>' for v in values if v)


def _calls_by_index(run: dict) -> dict[int, dict]:
    return {c.get("index"): c for c in run.get("calls") or []}


def call_counts(run: dict) -> dict[str, int]:
    calls = run.get("calls") or []
    return {
        "planned": sum(c.get("status") not in SKIPPED for c in calls),
        "done": sum(c.get("status") in DONE for c in calls),
        "failed": sum(c.get("status") == "failed" for c in calls),
        "not_run": sum(c.get("status") == "not_run" for c in calls),
        "waiting": sum(c.get("status") == "planned" for c in calls),
        "skipped": sum(c.get("status") in SKIPPED for c in calls),
    }


# --- saved runs list ------------------------------------------------------------


def run_label(item: dict) -> str:
    status = item.get("status") or "?"
    icon = STATUS_ICONS.get(status, "?")
    if status in ("completed", "partial", "cancelled", "running"):
        state = plural(item.get("leads") or 0, "lead")
    else:
        state = STATUS.get(status, (status, ""))[0]
    what = item.get("first_query") or item.get("image_name") or "no query"
    return f"{icon} {when(item.get('created_at'), short=True)} · {state} · {clip(what, 44)}"


# --- filters ---------------------------------------------------------------------


@dataclass(frozen=True)
class LeadFilter:
    text: str = ""
    route: str = "all"
    market: str = "all"
    kind: str = "all"
    sort: str = "rank"
    no_listings: bool = False
    shop_link: bool = False


def filter_choices(run: dict, leads: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """Choices for the filter controls, with how many leads each one keeps."""
    routes = Counter(lead.get("route") for lead in leads)
    markets = Counter(lead.get("market") for lead in leads)
    kinds = Counter(lead.get("platform_kind") or "unclassified" for lead in leads)
    order = list((run.get("settings") or {}).get("markets") or []) + sorted(markets)
    return {
        "route": [(f"All ({len(leads)})", "all")]
        + [(f"{label} ({routes[key]})", key) for key, label in ROUTES.items() if routes[key]],
        "market": [("All markets", "all")]
        + [(f"{market} ({markets[market]})", market) for market in dict.fromkeys(order) if markets[market]],
        "kind": [("All kinds", "all")]
        + [(f"{label} ({kinds[key]})", key) for key, label in KINDS.items() if kinds[key]],
    }


def filter_leads(leads: list[dict], f: LeadFilter) -> list[dict]:
    terms = (f.text or "").casefold().split()
    kept = []
    for lead in leads:
        if f.route != "all" and lead.get("route") != f.route:
            continue
        if f.market != "all" and lead.get("market") != f.market:
            continue
        if f.kind != "all" and (lead.get("platform_kind") or "unclassified") != f.kind:
            continue
        if f.no_listings and lead.get("page_hint") == "category_like":
            continue
        if f.shop_link and not lead.get("url"):
            continue
        if terms:
            text = " ".join(str(lead.get(key) or "") for key in
                            ("title", "merchant", "host", "snippet", "source_key", "platform")).casefold()
            if not all(term in text for term in terms):
                continue
        kept.append(lead)
    rank = lambda lead: lead.get("rank") or 0  # noqa: E731
    if f.sort == "price_up":
        kept.sort(key=lambda lead: (lead.get("price_value") is None, lead.get("price_value") or 0, rank(lead)))
    elif f.sort == "price_down":
        kept.sort(key=lambda lead: (lead.get("price_value") is None, -(lead.get("price_value") or 0), rank(lead)))
    elif f.sort == "source":
        kept.sort(key=lambda lead: ((lead.get("merchant") or lead.get("source_key") or "").casefold(), rank(lead)))
    return kept


# --- overview -----------------------------------------------------------------------


def _source_html(run: dict) -> str:
    source = run.get("source") or {}
    kind = source.get("kind")
    parts = []
    if kind == "image":
        image = source.get("image") or {}
        size = f" ({image['width']}×{image['height']})" if image.get("width") else ""
        parts.append(f"Reference image <b>{esc(image.get('name') or 'unnamed')}</b>{esc(size)}")
        text = source.get("user_text")
        parts.append(f"Description: “{esc(text)}”" if text else "no description")
    elif kind == "queries_file":
        parts.append(f"Queries from the file <b>{esc(source.get('queries_file'))}</b>")
    elif kind == "queries":
        parts.append("Queries written in the app")
    elif kind == "record":
        parts.append("Queries reused from a saved run")
    if source.get("from_record"):
        parts.append(f"based on run {esc(str(source['from_record'])[:8])}")
    return " · ".join(parts)


def _looking_for(run: dict) -> str:
    data = ((run.get("interpretation") or {}).get("data")) or {}
    if not data.get("category"):
        return ""
    changes = data.get("requested_changes") or []
    extra = f" — changes: {esc('; '.join(changes))}" if changes else ""
    return f'<div>Looking for <b>{esc(data["category"])}</b>{extra}</div>'


def _stat(value: Any, label: str, tip: str = "") -> str:
    title = f' title="{esc(tip)}"' if tip else ""
    return f'<div class="sd-stat"{title}><b>{esc(value)}</b><span>{esc(label)}</span></div>'


def account_line(account: dict | None, planned: int) -> tuple[str, bool]:
    """(text, enough quota) for the SerpApi account before a run."""
    if not account:
        return "", True
    left, used, limit = account.get("searches_left"), account.get("this_hour_searches"), account.get("hourly_limit")
    text = (f"SerpApi {account.get('plan_name') or 'account'}: "
            f"{left if left is not None else '?'} searches left this month, "
            f"{used if used is not None else '?'} of {limit or '?'} used this hour.")
    enough = (left is None or planned <= left) and (not limit or used is None or planned <= limit - used)
    return text, enough


def overview_html(run: dict, leads: list[dict], summary: dict | None, account: dict | None = None,
                  account_error: str | None = None, replay_note: str | None = None) -> str:
    status = run.get("status") or "?"
    label, explanation = STATUS.get(status, (status, ""))
    if status == "running" and not run.get("active"):
        explanation = ("Marked as running, but not running in this app; it may be running from the "
                       "command line. Refresh later.")
    counts = call_counts(run)
    markets = (run.get("settings") or {}).get("markets") or []
    rows = [
        '<div class="sd-head">'
        f'<span class="sd-pill sd-st-{esc(status)}">{esc(label)}</span>'
        f'<h3>Run {esc(str(run.get("id"))[:8])}</h3>'
        f'<span class="sd-muted">{esc(when(run.get("created_at")))}</span></div>',
        f'<div class="sd-muted">{_source_html(run)}</div>',
        _looking_for(run),
    ]

    if status in ("planned", "preparing"):
        stats = [
            _stat(counts["planned"], "searches planned", "Each uses one search from your SerpApi plan"),
            _stat(counts["skipped"], "not sent", "Over the budget, duplicates, or no query for that language"),
            _stat(len(markets), "markets", ", ".join(markets)),
            _stat(len(run.get("queries") or {}), "query languages", ", ".join(run.get("queries") or {})),
        ]
    else:
        sources = (summary or {}).get("distinct_sources")
        stats = [
            _stat(len(leads), "leads", "Search results after removing duplicates; unverified"),
            _stat(sources if sources is not None else "–", "distinct sources", "Shops, sites or marketplace sellers"),
            _stat(f"{counts['done']}/{counts['planned']}", "searches done",
                  f"{counts['failed']} failed, {counts['not_run']} not sent"),
            _stat(", ".join(markets) or "–", "markets"),
        ]
    rows.append(f'<div class="sd-stats">{"".join(stats)}</div>')

    if status == "running" and counts["planned"]:
        finished = counts["done"] + counts["failed"]
        percent = round(100 * finished / counts["planned"])
        current = next((c for c in run.get("calls") or [] if c.get("status") == "planned"), None)
        now = ""
        if current is not None and run.get("active"):
            now = (f' · now: {esc(ROUTES.get(current.get("route"), current.get("route")))} '
                   f'{esc(current.get("market"))} “{esc(clip(current.get("q"), 60))}”')
        rows.append(f'<div class="sd-progress" title="{percent}%"><div style="width:{percent}%"></div></div>'
                    f'<div class="sd-muted">{finished} of {counts["planned"]} searches finished{now}</div>')

    notices = [explanation] if explanation else []
    if run.get("interrupted"):
        notices.append("The app stopped during this run; searches that were not sent are marked “not run”.")
    if run.get("error"):
        notices.append(f"Error: {run['error']}")
    if status == "failed" and (run.get("interpretation") or {}).get("status") and not run.get("calls"):
        notices.append("The image interpretation failed, so nothing was searched. See the full log for the reply.")
    if replay_note:
        notices.append(replay_note)
    rows.extend(f'<div class="sd-notice">{esc(n)}</div>' for n in notices)
    if status == "planned":
        text, enough = account_line(account, counts["planned"])
        if account_error:
            rows.append(f'<div class="sd-notice sd-warn">{esc(account_error)}</div>')
        elif text:
            warn = "" if enough else (" The plan needs more searches than are left; plan again with a "
                                      "lower budget or fewer markets.")
            rows.append(f'<div class="sd-notice{"" if enough else " sd-warn"}">{esc(text + warn)}</div>')
    return f'<div class="sd sd-overview">{"".join(r for r in rows if r)}</div>'


# --- what was searched for --------------------------------------------------------


def _llm_line(name: str, llm: dict | None) -> str:
    if not llm:
        return ""
    usage = llm.get("usage") or {}
    tokens = f", {usage.get('input_tokens')} in / {usage.get('output_tokens')} out tokens" if usage else ""
    return (f"{name}: {esc(llm.get('model'))}, prompt {esc(llm.get('prompt_version'))}, "
            f"{esc(llm.get('status'))} in {llm.get('duration_s') or 0:.1f} s{esc(tokens)}")


def queries_table(queries: dict[str, dict[str, str]]) -> str:
    if not queries:
        return '<p class="sd-muted">No queries.</p>'
    rows = "".join(
        f"<tr><td><b>{esc(code)}</b></td>"
        + "".join(f"<td>{esc(entry.get(kind)) or '<span class=sd-muted>–</span>'}</td>" for kind in QUERY_KINDS)
        + "</tr>"
        for code, entry in queries.items()
    )
    head = "".join(f"<th>{kind}</th>" for kind in QUERY_KINDS)
    return f'<table class="sd-table"><tr><th>language</th>{head}</tr>{rows}</table>'


def intent_html(run: dict) -> str:
    interpretation = run.get("interpretation") or {}
    data = interpretation.get("data") or {}
    parts = []
    if data:
        fields = [
            ("Garment", f"<b>{esc(data.get('category'))}</b>"),
            ("Seen in the image", _chips(data.get("observed") or [])),
            ("Requested changes", _chips(data.get("requested_changes") or [], "sd-chip-change")),
            ("Must have", _chips(data.get("must_have") or [], "sd-chip-change")),
            ("Exclude", _chips(data.get("exclude") or [], "sd-chip-exclude")),
            ("The image cannot tell", _chips(data.get("uncertain") or [], "sd-chip-unsure")),
        ]
        items = "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in fields if value)
        parts.append(f"<dl>{items}</dl>")
    elif interpretation:
        problems = "; ".join(interpretation.get("problems") or []) or interpretation.get("error") or "no valid reply"
        parts.append(f'<div class="sd-notice sd-warn">The interpretation failed: {esc(problems)}</div>')
    else:
        parts.append('<p class="sd-muted">The queries were written by hand; no LLM was used.</p>')
    parts.append("<h4>Queries</h4>")
    parts.append(queries_table(run.get("queries") or {}))
    meta = [line for line in (_llm_line("Interpretation", run.get("interpretation")),
                              _llm_line("Queries for other languages", run.get("localization"))) if line]
    if meta:
        parts.append(f'<p class="sd-muted sd-small">{"<br>".join(meta)}</p>')
    return f'<div class="sd sd-intent">{"".join(parts)}</div>'


# --- results ------------------------------------------------------------------------


def _found_html(lead: dict, calls: dict[int, dict]) -> str:
    route = ROUTES.get(lead.get("route"), lead.get("route"))
    index = lead.get("call_index")
    text = (f'Found by search {esc(index)}: {esc(route)} · {esc(lead.get("market"))} · '
            f'{esc(lead.get("query_kind"))} query <q>{esc(lead.get("query"))}</q> · result #{esc(lead.get("position"))}')
    also = lead.get("also_found") or []
    if also:
        where = ", ".join(f"search {esc(a.get('call_index'))} #{esc(a.get('position'))}" for a in also[:4])
        more = f" and {len(also) - 4} more" if len(also) > 4 else ""
        text += f" · also in {where}{more}"
    call = calls.get(index) or {}
    extra = call.get("modifier") or (f"site:{call['site']}" if call.get("site") else None)
    if extra:
        text += f' · <span title="added to the query by discovery.toml">+ {esc(extra)}</span>'
    return text


def _card(lead: dict, calls: dict[int, dict], thumbnails: bool) -> str:
    link = safe_link(lead.get("url"))
    google = safe_link(lead.get("google_url"))
    target = link or google
    hint = lead.get("page_hint")
    title = esc(lead.get("title") or "(no title)")
    title_html = (f'<a class="sd-title" href="{esc(target)}" {EXTERNAL}>{title}</a>' if target
                  else f'<span class="sd-title">{title}</span>')
    host = lead.get("host") or ""
    host = host[4:] if host.startswith("www.") else host
    names = [n for n in dict.fromkeys([lead.get("merchant"), host]) if n]
    who = " · ".join(esc(n) for n in names) or esc(lead.get("source_key"))

    facts = []
    if lead.get("price"):
        price = f'<span class="sd-price" title="{esc(UNVERIFIED)}">{esc(lead["price"])}*</span>'
        if lead.get("old_price"):
            price += f' <s class="sd-muted">{esc(lead["old_price"])}</s>'
        facts.append(price)
    if lead.get("rating") is not None:
        reviews = f" ({lead['reviews']:,})" if lead.get("reviews") is not None else ""
        facts.append(f'<span title="rating and review count shown by Google">★ {lead["rating"]:.1f}{reviews}</span>')
    if lead.get("delivery"):
        facts.append(f'<span>Delivery: {esc(lead["delivery"])}</span>')

    badges = [_badge(ROUTES.get(lead.get("route"), lead.get("route") or "?"), f"sd-b-{esc(lead.get('route'))}",
                     "Google Shopping (merchant feeds)" if lead.get("route") == "shopping" else "Google web results")]
    if lead.get("platform_kind"):
        badges.append(_badge(KINDS.get(lead["platform_kind"], lead["platform_kind"]), "",
                             f"Platform {lead.get('platform')} (from discovery.toml)"))
    if hint == "product_like":
        badges.append(_badge("product page", "sd-b-product", "Guessed from the URL path; the page was not opened"))
    elif hint == "category_like":
        badges.append(_badge("listing page", "sd-b-listing",
                             "Guessed from the URL path: a category, search or shop page, not one product"))
    if not link:
        badges.append(_badge("no shop link", "sd-b-listing",
                             "Google Shopping named the shop but linked only to Google's product page"))
    if lead.get("condition"):
        badges.append(_badge(f"condition: {lead['condition']}", "sd-b-warn", "Second-hand condition shown by Google"))
    badges.extend(_badge(text, "sd-b-note") for text in lead.get("extensions") or [])
    if lead.get("idn_host"):
        badges.append(_badge("check the domain spelling", "sd-b-warn",
                             "Internationalized (punycode) host name; it can imitate another domain"))
    if lead.get("over_soft_cap"):
        badges.append(_badge("more from this source", "sd-b-listing",
                             "Over the soft cap per source, so moved down; nothing is dropped"))

    links = []
    if link:
        links.append(f'<a href="{esc(link)}" {EXTERNAL}>{"Open product page" if hint == "product_like" else "Open page"} ↗</a>')
    if google:
        links.append(f'<a href="{esc(google)}" {EXTERNAL}>Google product page ↗</a>')

    thumb = safe_thumbnail(lead.get("thumbnail")) if thumbnails else None
    initial = esc(str(lead.get("merchant") or host or lead.get("source_key") or "?")[:1].upper())
    picture = (f'<img src="{esc(thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer">' if thumb
               else f"<span>{initial}</span>")
    thumb_html = (f'<a class="sd-thumb" href="{esc(target)}" {EXTERNAL} tabindex="-1">{picture}</a>' if target
                  else f'<div class="sd-thumb">{picture}</div>')
    snippet = f'<p class="sd-snippet">{esc(lead["snippet"])}</p>' if lead.get("snippet") else ""
    return (
        f'<article class="sd-card{" sd-dim" if lead.get("over_soft_cap") else ""}">{thumb_html}'
        f'<div class="sd-body">'
        f'<div class="sd-title-row"><span class="sd-rank">#{esc(lead.get("rank"))}</span>{title_html}</div>'
        f'<div class="sd-who">{who}</div>'
        + (f'<div class="sd-facts">{"".join(facts)}</div>' if facts else "")
        + f'<div class="sd-badges">{"".join(badges)}</div>{snippet}'
        f'<div class="sd-found">{_found_html(lead, calls)}</div>'
        + (f'<div class="sd-links">{"".join(links)}</div>' if links else "")
        + "</div></article>"
    )


def results_html(run: dict, leads: list[dict], shown: list[dict], thumbnails: bool = True,
                 summary: dict | None = None, sort: str = "rank") -> str:
    status = run.get("status")
    if status in ("planned", "preparing"):
        return plan_html(run, heading=True)
    if not leads:
        if status == "running":
            message = "Searching… leads appear here as searches finish."
        else:
            message = "No leads. This does not mean nothing exists; only these queries found nothing."
            rejected = (summary or {}).get("rejected")
            if rejected:
                message += f" {plural(rejected, 'result')} were rejected for their URL (see the summary)."
        return f'<div class="sd sd-empty">{esc(message)}</div>'
    if not shown:
        return '<div class="sd sd-empty">No leads match these filters.</div>'
    calls = _calls_by_index(run)
    cards, divided = [], False
    for lead in shown:
        if sort == "rank" and lead.get("over_soft_cap") and not divided and len(shown) > 1:
            divided = True
            cards.append('<div class="sd-divider">More from sources already shown above '
                         '(over the soft cap per source)</div>')
        cards.append(_card(lead, calls, thumbnails))
    filtered = f" (filtered from {len(leads)})" if len(shown) != len(leads) else ""
    head = (f'<div class="sd-results-head"><span><b>{plural(len(shown), "lead")}</b>{filtered}</span>'
            f'<span class="sd-muted">* {esc(UNVERIFIED)}</span></div>')
    return f'<div class="sd">{head}<div class="sd-grid">{"".join(cards)}</div></div>'


# --- plan and summary ----------------------------------------------------------------


CALL_OUTCOMES = {
    "planned": ("planned", "sd-c-planned"),
    "ok": ("{n} results · {s} s", "sd-c-ok"),
    "empty": ("no results · {s} s", "sd-c-empty"),
    "failed": ("failed", "sd-c-failed"),
    "not_run": ("not run", "sd-c-skipped"),
    "skipped_budget": ("not sent: over the budget", "sd-c-skipped"),
    "skipped_no_query": ("not sent: no query", "sd-c-skipped"),
    "skipped_duplicate": ("not sent: same as an earlier search", "sd-c-skipped"),
}


def plan_html(run: dict, heading: bool = False) -> str:
    calls = run.get("calls") or []
    if not calls:
        return '<div class="sd sd-empty">No searches were planned.</div>'
    first_waiting = next((c.get("index") for c in calls if c.get("status") == "planned"), None)
    rows = []
    for call in calls:
        status = call.get("status")
        text, css = CALL_OUTCOMES.get(status, (status, ""))
        text = text.format(n=call.get("result_count"), s=call.get("duration_s"))
        if status == "planned" and run.get("status") == "running" and call.get("index") == first_waiting:
            text, css = "searching…", "sd-c-running"
        note = call.get("note")
        if note and status not in ("skipped_budget",):
            text += f": {note}" if status in ("failed", "not_run") else f" ({note})"
        extra = call.get("modifier") or (f"site:{call['site']}" if call.get("site") else None)
        query = esc(call.get("q") or "–")
        index = call.get("index")
        number = f"{index:02d}" if isinstance(index, int) else index
        rows.append(
            f'<tr class="{css}"><td>{esc(number)}</td>'
            f'<td>{esc(ROUTES.get(call.get("route"), call.get("route")))}</td><td>{esc(call.get("market"))}</td>'
            f'<td><span class="sd-kind">{esc(call.get("query_kind"))}</span> {query}'
            + (f' {_badge("+ " + extra, "sd-b-note")}' if extra else "")
            + f'</td><td><span class="sd-dot"></span>{esc(text)}</td></tr>'
        )
    table = ('<table class="sd-table sd-plan"><tr><th>#</th><th>Route</th><th>Market</th>'
             f'<th>Query</th><th>Outcome</th></tr>{"".join(rows)}</table>')
    intro = ""
    if heading:
        counts = call_counts(run)
        intro = (f'<p><b>The plan: {plural(counts["planned"], "search", "searches")}</b>'
                 + (f', {counts["skipped"]} more not sent (budget, duplicates or missing queries)'
                    if counts["skipped"] else "")
                 + '. Shopping searches Google Shopping (merchant feeds); Web searches Google’s web results. '
                 'Leads appear here once the run has started.</p>')
    return f'<div class="sd">{intro}{table}</div>'


def summary_html(summary: dict | None) -> str:
    if not summary:
        return '<div class="sd sd-empty">No summary yet; it is built from the finished searches.</div>'

    def counts(key: str, labels: dict | None = None) -> str:
        values = summary.get(key) or {}
        return " · ".join(f"{esc((labels or {}).get(k, k))} {v}" for k, v in sorted(values.items())) or "–"

    lines = []
    returned, checked = summary.get("results_returned"), summary.get("results_checked")
    if returned is not None:
        beyond = (f"; only the first {summary.get('max_leads_per_call')} per search are read "
                  f"(the rest stay in the raw responses)" if returned > (checked or 0) else "")
        lines.append(("Results", f"{returned} returned, {checked} read{beyond}"))
    lines.append(("Leads", f"{summary.get('leads')} after merging {summary.get('duplicates_merged')} duplicates"))
    if summary.get("leads"):
        share = summary.get("top_source_share")
        lines.append(("Diversity", f"{summary.get('distinct_sources')} distinct sources on "
                                   f"{summary.get('distinct_sites')} sites; most frequent: "
                                   f"{summary.get('top_source')} ({share:.0%} of leads)" if share is not None else "–"))
    lines.append(("By route", counts("by_route", ROUTES)))
    lines.append(("By market", counts("by_market")))
    lines.append(("By platform", counts("by_platform_kind", KINDS)))
    if summary.get("without_page_url"):
        lines.append(("No shop link", f"{summary['without_page_url']} Shopping leads link only to Google's product page"))
    if summary.get("idn_hosts"):
        lines.append(("Check spelling", f"{summary['idn_hosts']} leads use internationalized (punycode) domains"))
    if summary.get("rejected"):
        reasons = ", ".join(f"{r} ({n})" for r, n in (summary.get("rejection_reasons") or {}).items())
        lines.append(("Rejected", f"{summary['rejected']} results for their URL" + (f": {reasons}" if reasons else "")))
    rows = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in lines)

    curve = summary.get("new_sources_per_call") or []
    top = max((c.get("new_sources") or 0 for c in curve), default=0) or 1
    bars = "".join(
        f'<div class="sd-bar" title="search {esc(c.get("call_index"))}: {esc(c.get("leads"))} leads, '
        f'{esc(c.get("new_sources"))} new sources"><div style="height:{round(100 * (c.get("new_sources") or 0) / top)}%">'
        f'</div><span>{esc(c.get("call_index"))}</span></div>'
        for c in curve
    )
    chart = (f'<h4>New sources per search</h4><div class="sd-bars">{bars}</div>'
             '<p class="sd-muted sd-small">When later searches add few new sources, more searches of the same '
             'kind are unlikely to help.</p>') if curve else ""
    return f'<div class="sd sd-summary"><dl>{rows}</dl>{chart}</div>'


# --- styles ---------------------------------------------------------------------------


CSS = """
.sd { color: var(--body-text-color); font-size: 14px; line-height: 1.45; }
.sd a { color: var(--link-text-color, #2563eb); text-decoration: none; }
.sd a:hover { text-decoration: underline; }
.sd h3, .sd h4 { margin: 0; }
.sd h4 { margin: 14px 0 6px; font-size: 14px; }
.sd-muted { color: var(--body-text-color-subdued); }
.sd-small { font-size: 12px; }
.sd-empty { padding: 28px 16px; text-align: center; color: var(--body-text-color-subdued);
  border: 1px dashed var(--border-color-primary); border-radius: 10px; }

.sd-overview { display: flex; flex-direction: column; gap: 8px; }
.sd-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sd-head h3 { font-size: 18px; }
.sd-pill { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
  background: rgba(100, 116, 139, .15); }
.sd-st-planned { background: rgba(37, 99, 235, .14); color: #2563eb; }
.sd-st-running { background: rgba(147, 51, 234, .14); color: #9333ea; }
.sd-st-completed { background: rgba(22, 163, 74, .14); color: #16a34a; }
.sd-st-partial { background: rgba(202, 138, 4, .16); color: #b45309; }
.sd-st-failed { background: rgba(220, 38, 38, .14); color: #dc2626; }
.sd-stats { display: flex; flex-wrap: wrap; gap: 8px; }
.sd-stat { padding: 6px 12px; border-radius: 8px; background: var(--background-fill-secondary);
  border: 1px solid var(--border-color-primary); min-width: 96px; }
.sd-stat b { display: block; font-size: 17px; }
.sd-stat span { font-size: 12px; color: var(--body-text-color-subdued); }
.sd-progress { height: 8px; border-radius: 999px; background: var(--background-fill-secondary); overflow: hidden; }
.sd-progress > div { height: 100%; background: var(--color-accent, #f97316); transition: width .4s; }
.sd-notice { padding: 7px 10px; border-radius: 8px; font-size: 13px; background: var(--background-fill-secondary); }
.sd-warn { background: rgba(234, 88, 12, .13); }

.sd-intent dl, .sd-summary dl { display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 0; }
.sd-intent dt, .sd-summary dt { font-size: 13px; font-weight: 600; color: var(--body-text-color-subdued); }
.sd-intent dd, .sd-summary dd { margin: 0; display: flex; flex-wrap: wrap; gap: 4px; }
.sd-chip { font-size: 12px; padding: 2px 8px; border-radius: 6px; background: var(--background-fill-secondary);
  border: 1px solid var(--border-color-primary); }
.sd-chip-change { background: rgba(147, 51, 234, .12); border-color: rgba(147, 51, 234, .3); }
.sd-chip-exclude { background: rgba(220, 38, 38, .10); border-color: rgba(220, 38, 38, .3); }
.sd-chip-unsure { border-style: dashed; color: var(--body-text-color-subdued); background: transparent; }
.sd-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.sd-table th, .sd-table td { text-align: left; padding: 5px 8px; vertical-align: top;
  border-bottom: 1px solid var(--border-color-primary); }
.sd-table th { font-size: 12px; font-weight: 600; color: var(--body-text-color-subdued); }
.sd-plan td:first-child { font-variant-numeric: tabular-nums; color: var(--body-text-color-subdued); }
.sd-kind { font-size: 11px; text-transform: uppercase; letter-spacing: .03em; color: var(--body-text-color-subdued); }
.sd-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px;
  background: rgba(100, 116, 139, .5); }
.sd-c-ok .sd-dot { background: #16a34a; }
.sd-c-empty .sd-dot { background: #ca8a04; }
.sd-c-failed .sd-dot { background: #dc2626; }
.sd-c-running .sd-dot { background: #9333ea; }
.sd-c-planned .sd-dot { background: #2563eb; }
.sd-c-skipped td { color: var(--body-text-color-subdued); }

#sd-results { max-height: 78vh; overflow-y: auto; padding-right: 4px; }
.sd-results-head { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px 12px;
  font-size: 13px; margin: 2px 0 10px; }
.sd-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 440px), 1fr)); gap: 10px; }
.sd-divider { grid-column: 1 / -1; margin-top: 6px; padding-top: 8px; font-size: 12px; text-transform: uppercase;
  letter-spacing: .04em; color: var(--body-text-color-subdued); border-top: 1px dashed var(--border-color-primary); }
.sd-card { display: flex; gap: 12px; padding: 10px; border-radius: 10px; min-width: 0;
  border: 1px solid var(--border-color-primary); background: var(--background-fill-primary); }
.sd-card:hover { border-color: var(--color-accent, #f97316); }
.sd-dim { opacity: .8; }
.sd-thumb { flex: 0 0 104px; height: 104px; border-radius: 8px; overflow: hidden; display: flex;
  align-items: center; justify-content: center; background: var(--background-fill-secondary); }
.sd-thumb img { width: 100%; height: 100%; object-fit: cover; }
.sd-thumb span { font-size: 30px; font-weight: 700; color: var(--body-text-color-subdued); }
.sd-thumb:hover { text-decoration: none !important; }
.sd-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.sd-title-row { display: flex; gap: 6px; align-items: baseline; }
.sd-rank { font-size: 12px; color: var(--body-text-color-subdued); font-variant-numeric: tabular-nums; }
.sd .sd-title { font-weight: 600; color: var(--body-text-color); display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; overflow: hidden; }
.sd-who { font-size: 13px; color: var(--body-text-color-subdued); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.sd-facts { display: flex; flex-wrap: wrap; gap: 2px 12px; align-items: baseline; font-size: 13px; }
.sd-price { font-weight: 700; font-size: 15px; }
.sd-badges { display: flex; flex-wrap: wrap; gap: 4px; }
.sd-badge { font-size: 11px; padding: 1px 7px; border-radius: 999px; white-space: nowrap;
  background: var(--background-fill-secondary); border: 1px solid var(--border-color-primary); }
.sd-b-shopping { background: rgba(37, 99, 235, .12); border-color: rgba(37, 99, 235, .3); }
.sd-b-organic { background: rgba(13, 148, 136, .12); border-color: rgba(13, 148, 136, .3); }
.sd-b-product { background: rgba(22, 163, 74, .12); border-color: rgba(22, 163, 74, .3); }
.sd-b-listing { color: var(--body-text-color-subdued); }
.sd-b-note { background: rgba(147, 51, 234, .10); border-color: rgba(147, 51, 234, .25); }
.sd-b-warn { background: rgba(234, 88, 12, .14); border-color: rgba(234, 88, 12, .35); }
.sd-snippet { margin: 0; font-size: 13px; color: var(--body-text-color-subdued); display: -webkit-box;
  -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.sd-found { font-size: 12px; color: var(--body-text-color-subdued); }
.sd-found q { font-style: italic; }
.sd-links { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 13px; font-weight: 600; margin-top: 2px; }

.sd-bars { display: flex; align-items: flex-end; gap: 4px; height: 90px; padding-bottom: 16px; }
.sd-bar { position: relative; flex: 0 1 28px; height: 100%; display: flex; align-items: flex-end; }
.sd-bar > div { width: 100%; min-height: 2px; border-radius: 3px 3px 0 0; background: var(--color-accent, #f97316); }
.sd-bar span { position: absolute; bottom: -16px; left: 0; right: 0; text-align: center; font-size: 10px;
  color: var(--body-text-color-subdued); }

.sd-runlist .wrap:has(> label) { flex-direction: column; flex-wrap: nowrap; gap: 4px; max-height: 62vh;
  overflow-y: auto; }
.sd-runlist label { width: 100%; margin: 0; font-size: 13px; }
"""
