"""M04 probe: discover candidate product URLs on the web via SerpApi.

Commands, run by the owner (settings: discovery.toml):

    python -m scanger.discover IMAGE [--text "..."]
        Interprets IMAGE and text with the Cursor SDK (as scanger.interpret
        does), then writes queries for the other languages (a text-only SDK
        call), shows the search plan and runs it on SerpApi after confirmation.

    python -m scanger.discover --queries FILE.json
        Uses hand-written or edited queries instead of the LLM, e.g.
        {"de": {"precise": "...", "broad": "..."}, "fr": {...}}.

    python -m scanger.discover --from-record ID
        Reuses the queries of a saved run with the current settings.

    python -m scanger.discover --replay ID     Re-normalize saved responses. No network.
    python -m scanger.discover --list          List saved runs.

Options: --markets de-at,fr (market ids, or a language for all its markets)
         --max-calls N  --no-modifiers  --no-sites  --yes
         --plan-only (save and show the plan, send nothing to SerpApi)

A market is a language + country pair (e.g. de-de, de-at). Queries are written
per language and shared by all markets of that language.

What leaves the machine: with IMAGE, the image (re-encoded without metadata)
and the text go to Cursor; the queries and locale settings go to SerpApi and
from there to Google. No result page or image is fetched.

Each run is saved under DATA_ROOT/discovery/<id>/: record.json (plan, calls,
leads), queries.json (copy, edit, pass back with --queries) and raw/ (SerpApi
responses, key removed). Search results are unverified leads, not products.
"""

import argparse
import dataclasses
import json
import os
import re
import sys
import tomllib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scanger import assets
from scanger.config import (
    cursor_api_key,
    data_root,
    discovery_config_path,
    interpret_model,
    interpret_model_params,
    serpapi_api_key,
    upload_limits,
)
from scanger.interpret import QUERY_KEYS, InterpretationRun
from scanger.leads import (
    CallResult,
    Lead,
    LeadSettings,
    PlatformRule,
    build_leads,
    clean_text,
    result_items,
)
from scanger.localize import MAX_QUERY_CHARS
from scanger.serpapi import ENGINES, AccountStatus, ProviderError, SerpApiClient

RECORD_VERSION = 1
RECORD_DIR = "discovery"
HARD_MAX_CALLS = 50  # the free plan's hourly limit; protects against config typos
MAX_QUERIES_FILE_BYTES = 100_000
PRINT_LEADS = 60

ROUTES = tuple(ENGINES)
PLATFORM_KINDS = ("marketplace", "second_hand", "social", "aggregator", "retailer")
_LANGUAGE = re.compile(r"^[a-z]{2,3}$")
_MARKET = re.compile(r"^[a-z]{2,3}-[a-z]{2}$")
_COUNTRY = re.compile(r"^[a-z]{2}$")
_GOOGLE_DOMAIN = re.compile(r"^google(\.[a-z]{2,3}){1,2}$")
_HL = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,3})?$")
_LOCATION = re.compile(r"^[\w .,'-]{2,100}$")
_MODIFIER = re.compile(r"^[^\W\d_]+(?:[ '’-][^\W\d_]+)*$")
_SITE = re.compile(r"^(?=.{4,100}$)(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")
_LABEL = re.compile(r"^[a-z0-9-]{2,63}$")
_RAW_FILE = re.compile(r"^raw/\d{2,3}-[a-z]+-[a-z]{2,3}-[a-z]{2}\.json$")


class SettingsError(Exception):
    pass


class DiscoveryError(Exception):
    """Expected problem; the message is shown to the owner."""


# --- settings ----------------------------------------------------------------


@dataclass(frozen=True)
class Locale:
    market: str  # e.g. "de-at"
    language: str
    country: str  # SerpApi `gl`
    google_domain: str
    hl: str
    location: str | None = None


@dataclass(frozen=True)
class Step:
    query: str
    route: str
    with_modifiers: bool = False
    with_sites: bool = False
    small_business: bool = False


@dataclass(frozen=True)
class Settings:
    markets: tuple[str, ...]  # searched, in this order
    max_calls: int
    steps: tuple[Step, ...]
    locales: dict[str, Locale]  # all defined markets
    modifiers: dict[str, tuple[str, ...]]  # per language
    site_targets: tuple[str, ...]
    leads: LeadSettings
    source: str = ""  # config file name, for the record

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.locales[m].language for m in self.markets))

    def countries(self, language: str) -> list[str]:
        return [self.locales[m].country for m in self.markets if self.locales[m].language == language]


def _mapping(value: Any, where: str) -> dict:
    if not isinstance(value, dict):
        raise SettingsError(f"{where} must be a table.")
    return value


def _table(value: Any, where: str, allowed: set[str], required: set[str] = frozenset()) -> dict:
    _mapping(value, where)
    unknown = value.keys() - allowed
    if unknown:
        raise SettingsError(f"{where}: unknown key(s) {sorted(unknown)}.")
    missing = required - value.keys()
    if missing:
        raise SettingsError(f"{where}: missing key(s) {sorted(missing)}.")
    return value


def _int(value: Any, where: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SettingsError(f"{where} must be an integer from {low} to {high}.")
    return value


def _str(value: Any, where: str, pattern: re.Pattern) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise SettingsError(f"{where} has an invalid value {value!r}.")
    return value


def _bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise SettingsError(f"{where} must be true or false.")
    return value


def _list(value: Any, where: str) -> list:
    if not isinstance(value, list):
        raise SettingsError(f"{where} must be a list.")
    return value


def parse_settings(data: dict[str, Any], source: str = "") -> Settings:
    top = _table(
        data, "discovery settings",
        {"markets", "max_calls", "max_leads_per_call", "soft_cap_per_source",
         "soft_cap_per_marketplace", "site_targets", "steps", "modifiers", "locales", "platforms"},
        {"markets", "max_calls", "steps", "locales"},
    )

    locales = {}
    for market, raw in _mapping(top["locales"], "locales").items():
        where = f"locales.{market}"
        _str(market, where, _MARKET)
        table = _table(raw, where, {"language", "country", "google_domain", "hl", "location"},
                       {"language", "country", "google_domain"})
        language = _str(table["language"], f"{where}.language", _LANGUAGE)
        locales[market] = Locale(
            market=market,
            language=language,
            country=_str(table["country"], f"{where}.country", _COUNTRY),
            google_domain=_str(table["google_domain"], f"{where}.google_domain", _GOOGLE_DOMAIN),
            hl=_str(table.get("hl", language), f"{where}.hl", _HL),
            location=_str(table["location"], f"{where}.location", _LOCATION) if "location" in table else None,
        )

    markets = tuple(_str(m, "markets", _MARKET) for m in _list(top["markets"], "markets"))
    if not markets or len(set(markets)) != len(markets):
        raise SettingsError("markets must be a non-empty list without repeats.")
    for market in markets:
        if market not in locales:
            raise SettingsError(f"Market {market!r} has no [locales.{market}] table.")

    steps = []
    for i, raw in enumerate(_list(top["steps"], "steps"), start=1):
        where = f"steps #{i}"
        table = _table(raw, where, {"query", "route", "with_modifiers", "with_sites", "small_business"},
                       {"query", "route"})
        if table["query"] not in QUERY_KEYS:
            raise SettingsError(f"{where}.query must be one of {list(QUERY_KEYS)}.")
        if table["route"] not in ROUTES:
            raise SettingsError(f"{where}.route must be one of {list(ROUTES)}.")
        step = Step(
            query=table["query"],
            route=table["route"],
            with_modifiers=_bool(table.get("with_modifiers", False), f"{where}.with_modifiers"),
            with_sites=_bool(table.get("with_sites", False), f"{where}.with_sites"),
            small_business=_bool(table.get("small_business", False), f"{where}.small_business"),
        )
        if step.with_modifiers and step.with_sites:
            raise SettingsError(f"{where}: use either with_modifiers or with_sites, not both.")
        if step.with_sites and step.route != "organic":
            raise SettingsError(f"{where}: with_sites needs route = \"organic\" (Shopping ignores site:).")
        if step.small_business and step.route != "shopping":
            raise SettingsError(f"{where}: small_business needs route = \"shopping\".")
        steps.append(step)
    if not steps:
        raise SettingsError("At least one [[steps]] entry is required.")

    modifiers = {}
    for code, values in _mapping(top.get("modifiers", {}), "modifiers").items():
        _str(code, "modifiers", _LANGUAGE)
        modifiers[code] = tuple(
            _str(v, f"modifiers.{code}", _MODIFIER) for v in _list(values, f"modifiers.{code}")
        )
        if any(len(v) > 40 for v in modifiers[code]):
            raise SettingsError(f"modifiers.{code}: keep each modifier under 40 characters.")

    platforms = []
    for name, raw in _mapping(top.get("platforms", {}), "platforms").items():
        where = f"platforms.{name}"
        _str(name, where, _LABEL)
        table = _table(raw, where, {"kind", "labels"}, {"kind", "labels"})
        if table["kind"] not in PLATFORM_KINDS:
            raise SettingsError(f"{where}.kind must be one of {list(PLATFORM_KINDS)}.")
        labels = tuple(_str(v, f"{where}.labels", _LABEL) for v in _list(table["labels"], f"{where}.labels"))
        platforms.append(PlatformRule(name=name, kind=table["kind"], labels=labels))

    return Settings(
        markets=markets,
        max_calls=_int(top["max_calls"], "max_calls", 1, HARD_MAX_CALLS),
        steps=tuple(steps),
        locales=locales,
        modifiers=modifiers,
        site_targets=tuple(_str(v, "site_targets", _SITE) for v in _list(top.get("site_targets", []), "site_targets")),
        leads=LeadSettings(
            max_leads_per_call=_int(top.get("max_leads_per_call", 10), "max_leads_per_call", 1, 100),
            soft_cap_per_source=_int(top.get("soft_cap_per_source", 3), "soft_cap_per_source", 1, 100),
            soft_cap_per_marketplace=_int(top.get("soft_cap_per_marketplace", 6), "soft_cap_per_marketplace", 1, 100),
            platforms=tuple(platforms),
        ),
        source=source,
    )


def load_settings(path: Path) -> Settings:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SettingsError(f"Settings file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{path.name} is not valid TOML: {exc}") from None
    return parse_settings(data, source=path.name)


def apply_overrides(settings: Settings, markets: list[str] | None, max_calls: int | None,
                    no_modifiers: bool, no_sites: bool) -> Settings:
    """`markets` items are market ids ("de-at") or languages ("de" = its enabled
    markets, else all defined markets of that language)."""
    changes: dict[str, Any] = {}
    if markets:
        chosen = []
        for item in markets:
            if item in settings.locales:
                chosen.append(item)
                continue
            by_language = ([m for m in settings.markets if settings.locales[m].language == item]
                           or [m for m, loc in settings.locales.items() if loc.language == item])
            if not by_language:
                raise SettingsError(f"Unknown market or language {item!r}; defined markets: "
                                    f"{', '.join(sorted(settings.locales))}.")
            chosen.extend(by_language)
        changes["markets"] = tuple(dict.fromkeys(chosen))
    if max_calls is not None:
        if not 1 <= max_calls <= HARD_MAX_CALLS:
            raise SettingsError(f"--max-calls must be from 1 to {HARD_MAX_CALLS}.")
        changes["max_calls"] = max_calls
    steps = settings.steps
    if no_modifiers:
        steps = tuple(s for s in steps if not s.with_modifiers)
    if no_sites:
        steps = tuple(s for s in steps if not s.with_sites)
    if not steps:
        raise SettingsError("No steps left after --no-modifiers/--no-sites.")
    changes["steps"] = steps
    return dataclasses.replace(settings, **changes)


# --- queries -----------------------------------------------------------------


def clean_queries(data: Any, languages: tuple[str, ...]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Validate a {language: {kind: query}} mapping; partial entries are allowed.

    Returns the queries for the selected languages and notes about ignored ones.
    """
    if not isinstance(data, dict):
        raise DiscoveryError("Queries must be a JSON object keyed by language code.")
    queries, notes = {}, []
    for code, entry in data.items():
        if not isinstance(code, str) or not _LANGUAGE.match(code):
            raise DiscoveryError(f"Invalid language code {code!r} in queries.")
        if code not in languages:
            notes.append(f"Ignored queries for {code} (not in the selected languages).")
            continue
        if not isinstance(entry, dict):
            raise DiscoveryError(f"Queries for {code} must be an object with {list(QUERY_KEYS)}.")
        queries[code] = {}
        for kind, text in entry.items():
            if kind not in QUERY_KEYS:
                raise DiscoveryError(f"Unknown query kind {code}.{kind}; use {list(QUERY_KEYS)}.")
            query = clean_text(text, MAX_QUERY_CHARS + 1)
            if query is None:
                continue
            if len(query) > MAX_QUERY_CHARS:
                raise DiscoveryError(f"{code}.{kind} is longer than {MAX_QUERY_CHARS} characters.")
            queries[code][kind] = query
    return queries, notes


def load_queries_file(path: Path, languages: tuple[str, ...]) -> tuple[dict, list[str]]:
    try:
        if path.stat().st_size > MAX_QUERIES_FILE_BYTES:
            raise DiscoveryError(f"{path.name} is larger than {MAX_QUERIES_FILE_BYTES} bytes.")
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DiscoveryError(f"Cannot read {path}: {exc.strerror}") from None
    except (UnicodeDecodeError, ValueError) as exc:
        raise DiscoveryError(f"{path.name} is not valid JSON: {exc}") from None
    return clean_queries(data, languages)


# --- plan ----------------------------------------------------------------------


@dataclass
class Call:
    index: int
    market: str
    language: str
    country: str
    route: str
    query_kind: str
    modifier: str | None
    site: str | None
    q: str | None
    params: dict[str, str] = field(default_factory=dict)
    # planned | ok | empty | failed | not_run | skipped_budget | skipped_no_query | skipped_duplicate
    status: str = "planned"
    note: str | None = None
    http_status: int | None = None
    provider_search_id: str | None = None
    retrieved_at: str | None = None
    duration_s: float | None = None
    result_count: int | None = None
    error_kind: str | None = None
    raw_file: str | None = None


def call_params(locale: Locale, route: str, q: str, small_business: bool) -> dict[str, str]:
    params = {
        "engine": ENGINES[route],
        "q": q,
        "gl": locale.country,
        "hl": locale.hl,
        "google_domain": locale.google_domain,
    }
    if locale.location:
        params["location"] = locale.location
    if small_business:
        params["small_business"] = "true"
    return params


def build_plan(settings: Settings, queries: dict[str, dict[str, str]]) -> list[Call]:
    """Expand the steps into calls; mark the ones past the budget or without a query.

    Within a step, markets are interleaved (every market's first modifier,
    then every market's second ...) so a budget cut never removes a whole market.
    """
    calls: list[Call] = []
    planned, seen = 0, set()
    for step in settings.steps:
        variants: dict[str, list[tuple[str | None, str | None]]] = {}
        for market in settings.markets:
            language = settings.locales[market].language
            if step.with_modifiers:
                variants[market] = [(m, None) for m in settings.modifiers.get(language, ())]
            elif step.with_sites:
                variants[market] = [(None, s) for s in settings.site_targets]
            else:
                variants[market] = [(None, None)]
        depth = max((len(v) for v in variants.values()), default=0)
        for i in range(depth):
            for market in settings.markets:
                if i >= len(variants[market]):
                    continue
                modifier, site = variants[market][i]
                locale = settings.locales[market]
                base = queries.get(locale.language, {}).get(step.query)
                call = Call(
                    index=len(calls) + 1, market=market, language=locale.language,
                    country=locale.country, route=step.route, query_kind=step.query,
                    modifier=modifier, site=site, q=None,
                )
                calls.append(call)
                if not base:
                    call.status = "skipped_no_query"
                    call.note = f"no {step.query} query for {locale.language}"
                    continue
                call.q = " ".join(filter(None, [base, modifier, f"site:{site}" if site else None]))
                call.params = call_params(locale, step.route, call.q, step.small_business)
                identity = tuple(sorted(call.params.items()))
                if identity in seen:
                    call.status, call.note = "skipped_duplicate", "same request as an earlier call"
                elif planned >= settings.max_calls:
                    call.status, call.note = "skipped_budget", f"over max_calls = {settings.max_calls}"
                else:
                    planned += 1
                seen.add(identity)
    return calls


# --- records -------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, data: Any, ensure_ascii: bool = True) -> None:
    """Atomic write. ASCII escapes by default so files are safe to `cat`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.part")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=ensure_ascii, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def record_path(root: Path, record_id: uuid.UUID, name: str = "record.json") -> Path:
    if name != "record.json" and name != "queries.json" and not _RAW_FILE.match(name):
        raise DiscoveryError(f"Unexpected file name in record: {name!r}")
    return assets.resolve_storage_key(f"{RECORD_DIR}/{record_id}/{name}", root)


def find_record(root: Path, ref: str) -> uuid.UUID:
    """Resolve a full record ID or a unique prefix (at least 4 characters)."""
    ref = ref.strip().lower()
    if not re.fullmatch(r"[0-9a-f-]{4,36}", ref):
        raise DiscoveryError("Give a record ID or its first characters (see --list).")
    base = root / RECORD_DIR
    names = [p.name for p in base.iterdir() if p.is_dir()] if base.is_dir() else []
    matches = []
    for name in names:
        try:
            record_id = uuid.UUID(name)
        except ValueError:
            continue
        if str(record_id) == name and name.startswith(ref):
            matches.append(record_id)
    if not matches:
        raise DiscoveryError(f"No saved discovery run starts with {ref!r}.")
    if len(matches) > 1:
        raise DiscoveryError(f"{ref!r} matches {len(matches)} runs; give more characters.")
    return matches[0]


def load_record(root: Path, record_id: uuid.UUID) -> dict[str, Any]:
    try:
        record = json.loads(record_path(root, record_id).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DiscoveryError(f"Cannot read record {record_id}: {exc}") from None
    if not isinstance(record, dict) or record.get("record_version") != RECORD_VERSION:
        raise DiscoveryError(f"Record {record_id} has an unknown format.")
    return record


def save_record(root: Path, record: dict[str, Any], calls: list[Call]) -> None:
    record["calls"] = [asdict(c) for c in calls]
    record["updated_at"] = _now()
    write_json(record_path(root, uuid.UUID(record["id"])), record)


def settings_json(settings: Settings) -> dict[str, Any]:
    return asdict(settings)


def run_json(run: InterpretationRun | None) -> dict[str, Any] | None:
    return asdict(run) if run is not None else None


def saved_calls(root: Path, record: dict[str, Any]) -> list[CallResult]:
    """Load the raw responses of a record's successful calls (offline)."""
    record_id = uuid.UUID(record["id"])
    results = []
    for call in record.get("calls", []):
        if not call.get("raw_file"):
            continue
        path = record_path(root, record_id, call["raw_file"])
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"  (raw response {call['raw_file']} is missing or unreadable; skipped)")
            continue
        results.append(CallResult(
            index=call["index"], route=call["route"], market=call["market"],
            language=call["language"], country=call["country"], query_kind=call["query_kind"],
            query=call["q"] or "", body=body if isinstance(body, dict) else {},
        ))
    return results


# --- running -------------------------------------------------------------------


def execute(root: Path, record: dict[str, Any], calls: list[Call], client: SerpApiClient) -> None:
    """Run the planned calls in order, saving after each one (partial results survive)."""
    stop_reason = None
    try:
        for call in calls:
            if call.status != "planned":
                continue
            if stop_reason:
                call.status, call.note = "not_run", stop_reason
                continue
            label = f"[{call.index:02d}] {call.route:<8} {call.market} {call.q}"
            print(f"{label} ...", end=" ", flush=True)
            call.retrieved_at = _now()
            try:
                response = client.search(call.params)
            except ProviderError as exc:
                call.status, call.error_kind, call.note = "failed", exc.kind, exc.message
                call.http_status = exc.http_status
                print(f"failed: {exc.message}")
                if exc.fatal:
                    stop_reason = f"stopped after: {exc.message}"
            else:
                raw_file = f"raw/{call.index:02d}-{call.route}-{call.market}.json"
                write_json(record_path(root, uuid.UUID(record["id"]), raw_file), response.body)
                call.raw_file = raw_file
                call.http_status = response.http_status
                call.provider_search_id = clean_text(response.search_id, 64)
                call.duration_s = round(response.duration_s, 2)
                call.result_count = len(result_items(call.route, response.body))
                call.status = "ok" if call.result_count else "empty"
                call.note = clean_text(response.empty_message, 300)
                print(f"{call.result_count} results ({call.duration_s}s)")
            save_record(root, record, calls)
    except KeyboardInterrupt:
        print("\nCancelled.")
        for call in calls:
            if call.status == "planned":
                call.status, call.note = "not_run", "cancelled by owner"
        record["cancelled"] = True
        save_record(root, record, calls)


def overall_status(calls: list[Call], cancelled: bool) -> str:
    statuses = [c.status for c in calls]
    done = sum(s in ("ok", "empty") for s in statuses)
    if cancelled:
        return "cancelled"
    if done == 0:
        return "failed"
    if any(s in ("failed", "not_run") for s in statuses):
        return "partial"
    return "completed"


# --- output --------------------------------------------------------------------


def _ask(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() == "y"
    except EOFError:
        return False


def print_queries(queries: dict[str, dict[str, str]]) -> None:
    print("\nQueries:")
    for code, entry in queries.items():
        for kind in QUERY_KEYS:
            if kind in entry:
                print(f"  {code} {kind:<8} {entry[kind]}")


def print_plan(calls: list[Call]) -> None:
    print("\nPlan:")
    for call in calls:
        marker = "  " if call.status == "planned" else "x "
        text = call.q or "-"
        note = f"  ({call.status}: {call.note})" if call.status != "planned" else ""
        print(f" {marker}{call.index:02d} {call.route:<8} {call.market:<6} {text}{note}")
    planned = sum(c.status == "planned" for c in calls)
    print(f"{planned} call(s) planned; x = not sent.")


def print_leads(leads: list[Lead]) -> None:
    print("\nLeads (search results, unverified: prices, ratings and delivery are claims shown by Google)")
    for lead in leads[:PRINT_LEADS]:
        tags = [lead.source_key]
        if lead.platform_kind:
            tags.append(lead.platform_kind)
        if lead.page_hint:
            tags.append(lead.page_hint.replace("_", " "))
        if lead.over_soft_cap:
            tags.append("over soft cap")
        if lead.idn_host:
            tags.append("IDN HOST: check spelling")
        price = f"  {lead.price}*" if lead.price else ""
        print(f"\n#{lead.rank:<3} [{lead.route} {lead.market}] {' · '.join(tags)}{price}")
        print(f"     {clean_text(lead.title, 120) or '(no title)'}")
        if lead.url:
            print(f"     {lead.url}")
        else:
            merchant = f"{lead.merchant}; " if lead.merchant else ""
            print(f"     no shop URL ({merchant}Google product page): {lead.google_url}")
        if lead.also_found:
            seen = ", ".join(f"call {f['call_index']} #{f['position']}" for f in lead.also_found[:5])
            print(f"     also found in: {seen}")
    if len(leads) > PRINT_LEADS:
        print(f"\n... {len(leads) - PRINT_LEADS} more in record.json")


def print_summary(summary: dict[str, Any], calls: list[dict[str, Any]] | list[Call]) -> None:
    statuses: dict[str, int] = {}
    for call in calls:
        status = call["status"] if isinstance(call, dict) else call.status
        statuses[status] = statuses.get(status, 0) + 1
    print("\nSummary")
    print("  calls:   " + ", ".join(f"{n} {s}" for s, n in sorted(statuses.items())))
    if summary["leads"]:
        print(f"  leads:   {summary['leads']} ({summary['duplicates_merged']} duplicates merged), "
              f"{summary['distinct_sources']} distinct sources, {summary['distinct_sites']} sites; "
              f"top source {summary['top_source']} ({summary['top_source_share']:.0%})")
    else:
        print("  leads:   none. This does not mean nothing exists; only these queries found nothing.")
    for label, key in (("route", "by_route"), ("market", "by_market"), ("platform", "by_platform_kind")):
        print(f"  {label + ':':<9}" + ", ".join(f"{k} {v}" for k, v in sorted(summary[key].items())))
    if summary["without_page_url"]:
        print(f"  {summary['without_page_url']} shopping lead(s) have no shop URL, only a Google product page.")
    if summary["idn_hosts"]:
        print(f"  {summary['idn_hosts']} lead(s) use internationalized (punycode) host names; check the spelling.")
    if summary["rejected"]:
        print(f"  {summary['rejected']} result(s) rejected (unsafe or missing URL); reasons in record.json.")
    curve = ", ".join(f"{c['call_index']:02d}:+{c['new_sources']}" for c in summary["new_sources_per_call"])
    print(f"  new sources per call: {curve}")


def print_account(account: AccountStatus) -> None:
    print(f"\nSerpApi account: {clean_text(account.plan_name) or 'unknown plan'}, "
          f"{account.searches_left if account.searches_left is not None else '?'} searches left this month, "
          f"{account.this_hour_searches if account.this_hour_searches is not None else '?'}"
          f"/{account.hourly_limit or '?'} used this hour.")


# --- query sources --------------------------------------------------------------


def _cursor_selection():
    from cursor_sdk import Cursor, CursorAgentError

    from scanger.interpret import model_selection

    api_key = cursor_api_key()
    model_id = interpret_model()
    if api_key is None or model_id is None:
        raise DiscoveryError("CURSOR_API_KEY and INTERPRET_MODEL must be set for LLM queries "
                             "(or pass --queries FILE).")
    try:
        selection = model_selection(Cursor.models.list(api_key=api_key), model_id, interpret_model_params())
    except CursorAgentError as exc:
        raise DiscoveryError(f"Cursor model catalog unavailable: {exc.message}") from None
    except RuntimeError as exc:
        raise DiscoveryError(str(exc)) from None
    return selection, api_key


def _localize_into(record: dict, queries: dict, interpretation: dict, languages: list[str],
                   settings: Settings, selection, api_key: str) -> None:
    from scanger.localize import localize

    targets = {code: settings.countries(code) for code in languages}
    print(f"Writing queries for {', '.join(languages)} (text only) ...")
    run = localize(interpretation, targets, selection, api_key)
    record["localization"] = run_json(run)
    _print_llm_run("localization", run)
    if run.status != "finished" or run.problems:
        raise DiscoveryError("Localization failed; nothing was sent to SerpApi. "
                             "Try again, use fewer --languages, or pass --queries FILE.")
    queries.update(run.data)


def _print_llm_run(name: str, run: InterpretationRun) -> None:
    usage = f"in={run.usage.input_tokens} out={run.usage.output_tokens}" if run.usage else "tokens n/a"
    print(f"  {name}: {run.status}, {run.duration_s:.1f}s, {usage}, billing: {run.billed}")
    if run.error:
        print(f"  error: {run.error}")
    for problem in run.problems:
        print(f"  invalid: {problem}")


def queries_from_image(record: dict, image_path: Path, text: str, settings: Settings,
                       assume_yes: bool) -> dict:
    from scanger.interpret import interpret

    try:
        data = image_path.read_bytes()
        info = assets.inspect_image(data, upload_limits())
    except OSError as exc:
        raise DiscoveryError(f"Cannot read {image_path}: {exc.strerror}") from None
    except assets.AssetError as exc:
        raise DiscoveryError(f"Cannot use {image_path.name}: {exc}") from None
    sent = assets.without_metadata(data, info)
    record["source"]["image"] = {
        "name": clean_text(image_path.name, 200), "sha256": info.sha256, "mime_type": info.mime_type,
        "width": info.width, "height": info.height, "byte_size": info.byte_size, "sent_byte_size": len(sent),
    }
    selection, api_key = _cursor_selection()
    others = [code for code in settings.languages if code != "en"]
    then = f", then the interpretation (text only) to write queries in {', '.join(others)}" if others else ""
    print(f"This sends {image_path.name} ({info.width}x{info.height}, re-encoded without metadata, "
          f"{len(sent) // 1024} KB) and {len(text)} characters of text to Cursor's hosted model "
          f"{selection.id}{then}.")
    if not _ask("Send to Cursor?", assume_yes):
        raise DiscoveryError("Not sent.")

    run = interpret(sent, info.mime_type, text, selection, api_key)
    record["interpretation"] = run_json(run)
    _print_llm_run("interpretation", run)
    if run.status != "finished" or run.problems:
        raise DiscoveryError("Interpretation failed; nothing was sent to SerpApi.")
    for key, value in run.data.items():
        if key != "queries":
            shown = "; ".join(value) if isinstance(value, list) else value
            print(f"  {key}: {clean_text(shown, 300) or '-'}")

    queries, _ = clean_queries({"en": run.data["queries"]} if "en" in settings.languages else {},
                               settings.languages)
    if others:
        _localize_into(record, queries, run.data, others, settings, selection, api_key)
    return queries


def queries_from_record(root: Path, record: dict, ref: str, settings: Settings, assume_yes: bool) -> dict:
    old_id = find_record(root, ref)
    old = load_record(root, old_id)
    record["source"]["from_record"] = str(old_id)
    queries, notes = clean_queries(old.get("queries") or {}, settings.languages)
    for note in notes:
        print(note)
    interpretation = (old.get("interpretation") or {}).get("data")
    record["interpretation"] = old.get("interpretation")
    missing = [code for code in settings.languages if code not in queries]
    if "en" in missing and interpretation:
        english, _ = clean_queries({"en": interpretation.get("queries")}, ("en",))
        queries.update(english)
        missing.remove("en")
    if missing and interpretation:
        print(f"The saved run has no queries for {', '.join(missing)}.")
        if _ask("Write them with Cursor from the saved interpretation (text only)?", assume_yes):
            selection, api_key = _cursor_selection()
            _localize_into(record, queries, interpretation, missing, settings, selection, api_key)
    return queries


# --- commands ------------------------------------------------------------------


def command_list(root: Path) -> int:
    base = root / RECORD_DIR
    rows = []
    for path in sorted(base.iterdir()) if base.is_dir() else []:
        try:
            record = load_record(root, uuid.UUID(path.name))
        except (ValueError, DiscoveryError):
            continue
        calls = record.get("calls", [])
        done = sum(c["status"] in ("ok", "empty") for c in calls)
        planned = sum(c["status"] not in ("skipped_budget", "skipped_no_query", "skipped_duplicate") for c in calls)
        first = next(iter((record.get("queries") or {}).values()), {})
        rows.append((record.get("created_at", ""), path.name, clean_text(record.get("status")) or "?",
                     clean_text((record.get("source") or {}).get("kind")) or "?",
                     clean_text(",".join(record.get("settings", {}).get("markets", []))) or "",
                     f"{done}/{planned}", len(record.get("leads", [])), clean_text(first.get("precise")) or ""))
    if not rows:
        print("No saved discovery runs.")
        return 0
    for created, rid, status, kind, langs, calls, leads, query in sorted(rows):
        when = datetime.fromisoformat(created).astimezone().strftime("%Y-%m-%d %H:%M") if created else "?"
        print(f"{rid[:8]}  {when}  {status:<9} {kind:<12} {langs:<30} calls {calls:<6} leads {leads:<4} {query}")
    return 0


def command_replay(root: Path, ref: str, settings: Settings) -> int:
    record_id = find_record(root, ref)
    record = load_record(root, record_id)
    results = saved_calls(root, record)
    if not results:
        print("This run has no saved responses (it was only planned, or every call failed).")
        return 1
    leads, summary = build_leads(results, settings.leads)
    print(f"Replaying {record_id} ({record.get('status')}, {record.get('created_at')}) from saved responses; "
          f"no searches are spent. Leads use the current code and {settings.source} lead settings.")
    print_queries(record.get("queries") or {})
    print_leads(leads)
    print_summary(summary, record.get("calls", []))
    return 0


def command_search(args: argparse.Namespace, root: Path, settings: Settings) -> int:
    record_id = uuid.uuid4()
    kind = "image" if args.image else ("queries_file" if args.queries else "record")
    record: dict[str, Any] = {
        "record_version": RECORD_VERSION,
        "id": str(record_id),
        "created_at": _now(),
        "status": "preparing",
        "provider": "serpapi",
        "source": {"kind": kind, "user_text": args.text or None},
        "settings": settings_json(settings),
        "interpretation": None,
        "localization": None,
        "queries": {},
        "account_before": None,
        "calls": [],
        "leads": [],
        "summary": None,
    }
    calls: list[Call] = []
    try:
        if args.image:
            queries = queries_from_image(record, args.image, args.text or "", settings, args.yes)
        elif args.queries:
            record["source"]["queries_file"] = clean_text(args.queries.name, 200)
            queries, notes = load_queries_file(args.queries, settings.languages)
            for note in notes:
                print(note)
        else:
            queries = queries_from_record(root, record, args.from_record, settings, args.yes)
    except DiscoveryError:
        if record["interpretation"] is not None:
            record["status"] = "failed"
            save_record(root, record, calls)
            print(f"(LLM output saved in run {record_id})")
        raise

    record["queries"] = queries
    calls = build_plan(settings, queries)
    record["status"] = "planned"
    save_record(root, record, calls)
    write_json(record_path(root, record_id, "queries.json"), queries, ensure_ascii=False)
    print_queries(queries)
    print_plan(calls)
    print(f"\nSaved as run {record_id}.")

    planned = sum(c.status == "planned" for c in calls)
    if args.plan_only:
        print(f"Nothing sent to SerpApi. Run it later with: python -m scanger.discover --from-record {str(record_id)[:8]}")
        return 0
    if planned == 0:
        print("No calls to run.")
        return 1
    api_key = serpapi_api_key()
    if api_key is None:
        print("SERPAPI_API_KEY is not set. Add it to .env (see .env.example). The plan is saved.")
        return 1
    client = SerpApiClient(api_key)
    try:
        account = client.account()
    except ProviderError as exc:
        print(f"Cannot read the SerpApi account: {exc.message}")
        return 1
    print_account(account)
    record["account_before"] = asdict(account)
    if account.searches_left is not None and planned > account.searches_left:
        print(f"The plan needs {planned} searches but only {account.searches_left} are left. "
              "Lower --max-calls or --languages.")
        return 1
    if account.hourly_limit and account.this_hour_searches is not None \
            and planned > account.hourly_limit - account.this_hour_searches:
        print("The plan would exceed this hour's SerpApi limit. Wait or lower --max-calls.")
        return 1
    if not _ask(f"Run {planned} SerpApi searches? Each successful, uncached search uses 1 from your plan.", args.yes):
        print(f"Not sent. The plan is saved as run {record_id}.")
        return 0

    record["status"] = "running"
    save_record(root, record, calls)
    execute(root, record, calls, client)
    record["status"] = overall_status(calls, record.get("cancelled", False))
    leads, summary = build_leads(saved_calls(root, record), settings.leads)
    record["leads"] = [asdict(lead) for lead in leads]
    record["summary"] = summary
    record["finished_at"] = _now()
    save_record(root, record, calls)
    print_leads(leads)
    print_summary(summary, calls)
    print(f"\nRun {record_id}: {record['status']}. Replay for free: python -m scanger.discover --replay {str(record_id)[:8]}")
    return 0 if record["status"] in ("completed", "partial") else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", nargs="?", type=Path, help="reference image (JPEG, PNG or WebP)")
    parser.add_argument("--text", default="", help="with IMAGE: what should stay the same or change")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--queries", type=Path, help="JSON file of queries per language (no LLM)")
    source.add_argument("--from-record", metavar="ID", help="reuse the queries of a saved run")
    source.add_argument("--replay", metavar="ID", help="show a saved run again from its raw responses (offline)")
    source.add_argument("--list", action="store_true", help="list saved runs")
    parser.add_argument("--markets", help="comma-separated market ids or languages, e.g. de-at,fr")
    parser.add_argument("--max-calls", type=int, help=f"override max_calls (1-{HARD_MAX_CALLS})")
    parser.add_argument("--no-modifiers", action="store_true", help="drop steps that add small-maker modifiers")
    parser.add_argument("--no-sites", action="store_true", help="drop site-targeted steps")
    parser.add_argument("--plan-only", action="store_true", help="save and show the plan; no SerpApi calls")
    parser.add_argument("--config", type=Path, help="settings file (default: DISCOVERY_CONFIG or discovery.toml)")
    parser.add_argument("--yes", action="store_true", help="skip confirmations")
    args = parser.parse_args(argv)

    searches = [bool(args.image), bool(args.queries), bool(args.from_record)]
    if args.image and (args.queries or args.from_record or args.replay or args.list):
        parser.error("give either IMAGE or one of --queries/--from-record/--replay/--list")
    if args.text and not args.image:
        parser.error("--text needs IMAGE")
    if not any(searches) and not (args.replay or args.list):
        parser.error("give IMAGE, --queries FILE, --from-record ID, --replay ID or --list")

    root = data_root()
    try:
        if args.list:
            return command_list(root)
        settings = load_settings((args.config or discovery_config_path()).resolve())
        markets = [m.strip().lower() for m in args.markets.split(",") if m.strip()] if args.markets else None
        settings = apply_overrides(settings, markets, args.max_calls, args.no_modifiers, args.no_sites)
        if args.replay:
            return command_replay(root, args.replay, settings)
        return command_search(args, root, settings)
    except (SettingsError, DiscoveryError, assets.AssetError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
