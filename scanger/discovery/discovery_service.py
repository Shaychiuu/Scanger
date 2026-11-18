"""Web discovery for the app: plan, run and inspect discovery runs without prompts.

Runs are the same JSON records as `python -m scanger.discover` writes
(DATA_ROOT/discovery/<id>/), so the CLI can list, replay and reuse runs made in
the app and the other way round.

Planning may call Cursor (with an image) but never SerpApi. A planned run is
executed in a background thread that saves the record after every search,
including the leads found so far, so the app can show progress while it runs.
At most one run executes at a time. The registry of executing runs lives in
this process, so this is only safe with a single API process, which is how
Scanger runs.
"""

import io
import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO

from scanger import discover
from scanger.config import cursor_api_key, discovery_config_path, interpret_model, serpapi_api_key
from scanger.discover import Call, DiscoveryError, RunNotFound, Settings
from scanger.interpret import QUERY_KEYS
from scanger.leads import CallResult, LeadSettings, build_leads, clean_text
from scanger.localize import LANGUAGE_NAMES
from scanger.serpapi import AccountStatus, ProviderError, SerpApiClient

SKIPPED = ("skipped_budget", "skipped_no_query", "skipped_duplicate")
INTERRUPTED_NOTE = "interrupted: the app stopped before this search was sent"

ClientFactory = Callable[[str], Any]  # api key -> object with search() and account()


class RunConflict(DiscoveryError):
    """The run's state does not allow the request (e.g. it is already running)."""


@dataclass(frozen=True)
class RunOptions:
    """Per-run overrides of discovery.toml, as the CLI's --markets/--max-calls/--no-*."""

    markets: list[str] | None = None
    max_calls: int | None = None
    no_modifiers: bool = False
    no_sites: bool = False


_lock = threading.Lock()
_active: dict[str, threading.Event] = {}  # record id -> cancel event


# --- settings --------------------------------------------------------------------


def load_settings(options: RunOptions | None = None) -> Settings:
    settings = discover.load_settings(discovery_config_path())
    if options is None:
        return settings
    markets = [m.strip().lower() for m in options.markets if m.strip()] if options.markets else None
    return discover.apply_overrides(settings, markets, options.max_calls, options.no_modifiers, options.no_sites)


def settings_info() -> dict[str, Any]:
    """What the new-search form offers, and which keys are configured."""
    settings = load_settings()
    return {
        "source": settings.source,
        "markets": [
            {
                "id": locale.market,
                "language": locale.language,
                "language_name": LANGUAGE_NAMES.get(locale.language, locale.language),
                "country": locale.country,
                "google_domain": locale.google_domain,
                "enabled": locale.market in settings.markets,
            }
            for locale in settings.locales.values()
        ],
        "default_markets": list(settings.markets),
        "max_calls": settings.max_calls,
        "hard_max_calls": discover.HARD_MAX_CALLS,
        "modifiers": {code: list(values) for code, values in settings.modifiers.items()},
        "site_targets": list(settings.site_targets),
        "has_modifier_steps": any(step.with_modifiers for step in settings.steps),
        "has_site_steps": any(step.with_sites for step in settings.steps),
        "query_kinds": list(QUERY_KEYS),
        "serpapi_configured": serpapi_api_key() is not None,
        "cursor_configured": cursor_api_key() is not None and interpret_model() is not None,
        "interpret_model": interpret_model(),
    }


def account_status(client_factory: ClientFactory = SerpApiClient) -> dict[str, Any]:
    """Remaining SerpApi quota (the Account API is free)."""
    return asdict(_account(_client(client_factory)))


def _client(client_factory: ClientFactory):
    api_key = serpapi_api_key()
    if api_key is None:
        raise DiscoveryError("SERPAPI_API_KEY is not set. Add it to .env (see .env.example) "
                             "and restart the app.")
    return client_factory(api_key)


def _account(client) -> AccountStatus:
    try:
        return client.account()
    except ProviderError as exc:
        raise DiscoveryError(f"Cannot read the SerpApi account: {exc.message}") from None


# --- reading runs -------------------------------------------------------------------


def _with_state(record: dict[str, Any]) -> dict[str, Any]:
    return {**record, "active": record["id"] in _active}


def _load(root: Path, run_id: uuid.UUID | str) -> dict[str, Any]:
    return discover.load_record(root, discover.find_record(root, str(run_id)))


def list_runs(root: Path) -> list[dict[str, Any]]:
    """Saved runs, newest first (like `--list`)."""
    base = root / discover.RECORD_DIR
    items = []
    for path in base.iterdir() if base.is_dir() else []:
        try:
            record_id = uuid.UUID(path.name)
            record = discover.load_record(root, record_id)
        except (ValueError, DiscoveryError):
            continue
        calls = record.get("calls") or []
        source = record.get("source") or {}
        first = next(iter((record.get("queries") or {}).values()), {})
        items.append({
            "id": str(record_id),
            "created_at": record.get("created_at"),
            "status": record.get("status"),
            "active": str(record_id) in _active,
            "source_kind": source.get("kind"),
            "image_name": (source.get("image") or {}).get("name"),
            "user_text": source.get("user_text"),
            "markets": (record.get("settings") or {}).get("markets", []),
            "calls_done": sum(c.get("status") in ("ok", "empty") for c in calls),
            "calls_planned": sum(c.get("status") not in SKIPPED for c in calls),
            "leads": len(record.get("leads") or []),
            "first_query": first.get("precise") or next(iter(first.values()), None),
        })
    return sorted(items, key=lambda item: item["created_at"] or "", reverse=True)


def get_run(root: Path, run_id: uuid.UUID | str) -> dict[str, Any]:
    return _with_state(_load(root, run_id))


def replay(root: Path, run_id: uuid.UUID | str) -> dict[str, Any]:
    """Leads rebuilt from the saved responses with the current code and
    discovery.toml lead settings (like `--replay`). No search is spent and the
    record is not changed."""
    record = _load(root, run_id)
    out = io.StringIO()
    results = discover.saved_calls(root, record, out)
    if not results:
        raise DiscoveryError("This run has no saved responses (it was only planned, or every search failed).")
    settings = load_settings()
    leads, summary = build_leads(results, settings.leads)
    return {
        "leads": [asdict(lead) for lead in leads],
        "summary": summary,
        "settings_source": settings.source,
        "notes": [line.strip() for line in out.getvalue().splitlines() if line.strip()],
    }


def raw_response(root: Path, run_id: uuid.UUID | str, index: int) -> dict[str, Any]:
    """One saved SerpApi response (the key was removed before saving)."""
    record = _load(root, run_id)
    call = next((c for c in record.get("calls", []) if c.get("index") == index), None)
    if call is None or not call.get("raw_file"):
        raise RunNotFound(f"Search {index} has no saved response.")
    path = discover.record_path(root, uuid.UUID(record["id"]), call["raw_file"])
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RunNotFound(f"The saved response of search {index} is missing or unreadable.") from None


def run_log(root: Path, run_id: uuid.UUID | str, replayed: bool = False) -> str:
    """The whole run as text, in the CLI's format, with every lead."""
    record = _load(root, run_id)
    leads, summary = record.get("leads") or [], record.get("summary")
    note = None
    if replayed:
        again = replay(root, run_id)
        leads, summary = again["leads"], again["summary"]
        note = (f"Leads replayed from the saved responses with the current code and "
                f"{again['settings_source']} lead settings; no searches were spent.")
    out = io.StringIO()
    write_log(record, out, leads, summary, note)
    return out.getvalue()


def write_log(record: dict[str, Any], out: TextIO, leads: list[dict[str, Any]],
              summary: dict[str, Any] | None, note: str | None = None) -> None:
    source = record.get("source") or {}
    settings = record.get("settings") or {}

    def say(text: str = "") -> None:
        print(text, file=out)

    say(f"Run {record.get('id')}: {record.get('status')}")
    say(f"  created {record.get('created_at')}, finished {record.get('finished_at') or '-'}")
    say(f"  source: {source.get('kind')}")
    for key in ("from_record", "queries_file", "user_text"):
        if source.get(key):
            say(f"  {key}: {clean_text(source[key], 300)}")
    image = source.get("image")
    if image:
        say(f"  image: {clean_text(image.get('name'), 200) or '?'} ({image.get('width')}x{image.get('height')}, "
            f"{image.get('byte_size')} bytes; {image.get('sent_byte_size')} bytes sent without metadata)")
    say(f"  settings: {settings.get('source') or '?'}; markets {', '.join(settings.get('markets', []))}; "
        f"max_calls {settings.get('max_calls')}")
    if record.get("cancelled"):
        say("  cancelled by the owner")
    if record.get("interrupted"):
        say("  interrupted: the app stopped during the run")
    if record.get("error"):
        say(f"  error: {clean_text(record['error'], 500)}")

    for name in ("interpretation", "localization"):
        llm = record.get(name)
        if not llm:
            continue
        usage = llm.get("usage") or {}
        tokens = (f"in={usage.get('input_tokens')} out={usage.get('output_tokens')}" if usage else "tokens n/a")
        say(f"\n{name.capitalize()}: {llm.get('model')} {llm.get('params') or {}}, prompt {llm.get('prompt_version')}")
        say(f"  {llm.get('status')}, {llm.get('duration_s') or 0:.1f}s, {tokens}, billing: {llm.get('billed')}")
        if llm.get("error"):
            say(f"  error: {clean_text(llm['error'], 500)}")
        for problem in llm.get("problems") or []:
            say(f"  invalid: {clean_text(problem, 300)}")
        say(f"  reply: {clean_text(llm.get('raw_text'), 5000) or '-'}")

    discover.print_queries(record.get("queries") or {}, out)
    if record.get("account_before"):
        discover.print_account(AccountStatus(**record["account_before"]), out)

    say("\nSearches:")
    for call in record.get("calls", []):
        say(f" {call['index']:02d} {call['route']:<8} {call['market']:<6} {call.get('q') or '-'}")
        detail = {
            "ok": f"{call.get('result_count')} results in {call.get('duration_s')}s, "
                  f"search id {call.get('provider_search_id') or '-'}, {call.get('raw_file')}",
            "empty": f"no results in {call.get('duration_s')}s",
        }.get(call["status"], "")
        note_text = clean_text(call.get("note"), 300)
        say(f"    {call['status']}" + (f": {detail}" if detail else "") + (f" ({note_text})" if note_text else ""))

    if note:
        say(f"\n{note}")
    discover.print_leads(discover.leads_from_json(leads), out, limit=None)
    if summary:
        discover.print_summary(summary, record.get("calls", []), out)
        rejections = summary.get("rejections") or []
        if rejections:
            say(f"\nRejected results ({len(rejections)} of {summary.get('rejected')} listed):")
            for item in rejections:
                say(f"  call {item.get('call_index')} #{item.get('position')}: {item.get('reason')}"
                    f" ({clean_text(item.get('title')) or 'no title'})")


# --- planning -----------------------------------------------------------------------


def plan_from_image(root: Path, settings: Settings, data: bytes, name: str | None, text: str,
                    asset_id: str | None = None) -> dict[str, Any]:
    """Interpret the image (and text) with Cursor, write the queries and save the
    plan. Nothing is sent to SerpApi."""
    record = discover.new_record("image", settings, text)
    sent, info = discover.prepare_image(record, data, name)
    if asset_id:
        record["source"]["image"]["asset_id"] = asset_id
    selection, api_key = discover.cursor_selection()
    try:
        queries = discover.image_queries(record, sent, info.mime_type, text, settings,
                                         selection, api_key, io.StringIO())
    except DiscoveryError as exc:
        if record["interpretation"] is None:
            raise
        record["status"] = "failed"
        discover.save_record(root, record, [])
        raise DiscoveryError(f"{exc} The model's reply is saved in run {record['id'][:8]}.") from None
    discover.save_plan(root, record, settings, queries)
    return _with_state(record)


def plan_from_queries(root: Path, settings: Settings, data: Any,
                      from_record: uuid.UUID | str | None = None) -> tuple[dict[str, Any], list[str]]:
    """Save a plan for queries written (or edited) by the owner; no LLM. With
    `from_record`, the queries' origin and its interpretation are kept."""
    queries, notes = discover.clean_queries(data, settings.languages)
    if not any(queries.values()):
        raise DiscoveryError("Enter at least one query for a language of the selected markets "
                             f"({', '.join(settings.languages)}).")
    record = discover.new_record("queries", settings, None)
    if from_record is not None:
        old = _load(root, from_record)
        record["source"]["from_record"] = old["id"]
        record["interpretation"] = old.get("interpretation")
    discover.save_plan(root, record, settings, queries)
    return _with_state(record), notes


# --- running --------------------------------------------------------------------


def start_run(root: Path, run_id: uuid.UUID | str, client_factory: ClientFactory = SerpApiClient) -> dict[str, Any]:
    """Check the quota and start a planned run in the background; return at once."""
    record_id = str(discover.find_record(root, str(run_id)))
    with _lock:
        if _active:
            other = next(iter(_active))
            raise RunConflict(f"Run {other[:8]} is still running. Wait for it or stop it first.")
        cancel = _active[record_id] = threading.Event()
    try:
        record = discover.load_record(root, uuid.UUID(record_id))
        if record.get("status") != "planned":
            raise RunConflict(f"Only planned runs can be started; this run is {record.get('status')}.")
        calls = discover.calls_from_json(record)
        planned = sum(call.status == "planned" for call in calls)
        if planned == 0:
            raise DiscoveryError("This plan has no searches to send.")
        client = _client(client_factory)
        account = _account(client)
        problem = discover.quota_problem(account, planned)
        if problem:
            raise DiscoveryError(f"{problem} Plan again with a lower search budget or fewer markets, or wait.")
        lead_settings = discover.lead_settings_from_json(record["settings"]["leads"])
        record["account_before"] = asdict(account)
        record["status"] = "running"
        discover.save_record(root, record, calls)
    except BaseException:
        with _lock:
            _active.pop(record_id, None)
        raise
    threading.Thread(
        target=_execute, args=(root, record, calls, client, cancel, lead_settings),
        name=f"discovery-{record_id[:8]}", daemon=True,
    ).start()
    return _with_state(record)


def _execute(root: Path, record: dict[str, Any], calls: list[Call], client, cancel: threading.Event,
             lead_settings: LeadSettings) -> None:
    results: list[CallResult] = []

    def show_leads_so_far(call: Call, body: dict[str, Any]) -> None:
        results.append(CallResult(index=call.index, route=call.route, market=call.market,
                                  language=call.language, country=call.country,
                                  query_kind=call.query_kind, query=call.q or "", body=body))
        leads, summary = build_leads(results, lead_settings)
        record["leads"] = [asdict(lead) for lead in leads]
        record["summary"] = summary

    try:
        discover.execute(root, record, calls, client, io.StringIO(), cancel, show_leads_so_far)
        discover.finish_run(root, record, calls, lead_settings)
    except Exception as exc:
        for call in calls:
            if call.status == "planned":
                call.status, call.note = "not_run", "stopped by an unexpected error"
        record["status"] = "failed"
        record["error"] = clean_text(f"{type(exc).__name__}: {exc}", 500)
        try:
            discover.save_record(root, record, calls)
        except Exception:
            pass
    finally:
        with _lock:
            _active.pop(record["id"], None)


def cancel_run(root: Path, run_id: uuid.UUID | str) -> dict[str, Any]:
    """Stop before the next search; the one already sent still finishes."""
    record_id = str(discover.find_record(root, str(run_id)))
    with _lock:
        cancel = _active.get(record_id)
    if cancel is None:
        raise RunConflict("This run is not running in the app.")
    cancel.set()
    return get_run(root, record_id)


def reconcile_interrupted(root: Path) -> int:
    """Finish runs left "running" by a stopped app: unsent searches become
    not_run and the leads are built from the responses saved so far.

    A run started from the CLI that is still going is also marked; the CLI
    rewrites the record with its own state on its next save.
    """
    base = root / discover.RECORD_DIR
    count = 0
    for path in base.iterdir() if base.is_dir() else []:
        try:
            record_id = uuid.UUID(path.name)
            record = discover.load_record(root, record_id)
        except (ValueError, DiscoveryError):
            continue
        if record.get("status") != "running" or str(record_id) in _active:
            continue
        calls = discover.calls_from_json(record)
        for call in calls:
            if call.status == "planned":
                call.status, call.note = "not_run", INTERRUPTED_NOTE
        record["interrupted"] = True
        try:
            discover.finish_run(root, record, calls, discover.lead_settings_from_json(record["settings"]["leads"]))
        except (OSError, KeyError, TypeError, ValueError, DiscoveryError):
            continue
        count += 1
    return count
