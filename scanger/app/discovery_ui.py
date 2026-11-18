"""The web discovery tab of the Scanger frontend (M04), through the Scanger API.

What `python -m scanger.discover` does, as pages: plan from a reference image
and a description (always plan-only first: nothing goes to SerpApi before "Run
searches"), choose markets, the search budget and the extra searches
(--markets, --max-calls, --no-modifiers, --no-sites), write or load your own
queries (--queries), rebuild the leads offline (--replay) and browse saved runs
(--list). A run page shows the leads; the full log is behind "Show full log".
"""

import json
import uuid
from pathlib import Path
from typing import Any

import gradio as gr

from scanger import discovery_view as view
from scanger.api_client import ApiError, call, fetch_image

PLAN_TIMEOUT = 300  # Cursor reads the image, then translates the queries
START_TIMEOUT = 60  # the API checks the SerpApi quota before starting
POLL_SECONDS = 2.0
MAX_QUERIES_FILE_BYTES = 100_000  # as the command line
QUERY_COLUMNS = ["language", *view.QUERY_KINDS]
QUERIES_FILE_HELP = 'A JSON object keyed by language code: {"en": {"precise": "…", "synonym": "…", "broad": "…"}}'
LEGEND = ("✓ completed · ◐ partial · ✗ failed · ○ planned · ▶ running · ■ stopped  \n"
          "Runs are shared with `python -m scanger.discover`.")


# --- helpers without Gradio state ------------------------------------------------


def market_choices(settings: dict) -> list[tuple[str, str]]:
    return [(f"{m['id']} · {m['language_name']}, {m['country'].upper()} ({m['google_domain']})", m["id"])
            for m in settings["markets"]]


def languages_of(settings: dict, markets: list[str]) -> list[str]:
    by_id = {m["id"]: m["language"] for m in settings["markets"]}
    return list(dict.fromkeys(by_id[m] for m in markets or [] if m in by_id))


def step_choices(settings: dict) -> list[tuple[str, str]]:
    choices = []
    if settings.get("has_modifier_steps"):
        words = [w for values in settings.get("modifiers", {}).values() for w in values][:3]
        example = f" (e.g. {', '.join(words)})" if words else ""
        choices.append((f"Shopping searches with modifier words{example}", "modifiers"))
    if settings.get("has_site_steps"):
        sites = settings.get("site_targets") or []
        example = f" ({', '.join(sites[:3])}{'…' if len(sites) > 3 else ''})" if sites else ""
        choices.append((f"Web searches limited to target sites{example}", "sites"))
    return choices


def _cell(value: Any) -> str:
    return "" if value is None or value != value else str(value).strip()  # NaN != NaN


def query_rows(queries: dict, languages: list[str]) -> list[list[str]]:
    """Table rows: the selected languages first, then any other language given."""
    rows = {code: [code] + [_cell((entry or {}).get(kind)) for kind in view.QUERY_KINDS]
            for code, entry in queries.items()}
    for code in languages:
        rows.setdefault(code, [code, "", "", ""])
    ordered = [rows.pop(code) for code in languages] + list(rows.values())
    return ordered or [["", "", "", ""]]


def add_language_rows(rows: list[list[Any]] | None, languages: list[str]) -> list[list[str]]:
    kept = [[_cell(c) for c in (list(row) + [""] * 4)[:4]] for row in rows or []]
    kept = [row for row in kept if any(row)]
    present = {row[0].lower() for row in kept}
    kept += [[code, "", "", ""] for code in languages if code not in present]
    return kept or [["", "", "", ""]]


def rows_to_queries(rows: list[list[Any]] | None) -> dict[str, dict[str, str]]:
    queries: dict[str, dict[str, str]] = {}
    for row in rows or []:
        cells = [_cell(c) for c in (list(row) + [""] * 4)[:4]]
        code, texts = cells[0].lower(), cells[1:]
        if not any(texts):
            continue
        if not code:
            raise ValueError("Every row with queries needs a language code, e.g. en or de.")
        queries.setdefault(code, {}).update({k: t for k, t in zip(view.QUERY_KINDS, texts) if t})
    return queries


def read_queries_file(path: str) -> dict[str, dict[str, str]]:
    file = Path(path)
    if file.stat().st_size > MAX_QUERIES_FILE_BYTES:
        raise ValueError(f"{file.name} is larger than {MAX_QUERIES_FILE_BYTES // 1000} KB.")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"{file.name} is not valid JSON: {exc}") from None
    if not isinstance(data, dict) or not all(isinstance(entry, dict) for entry in data.values()):
        raise ValueError(f"{file.name} has the wrong shape. {QUERIES_FILE_HELP}")
    for code, entry in data.items():
        unknown = sorted(set(entry) - set(view.QUERY_KINDS))
        if unknown:
            raise ValueError(f"Unknown query kind {code}.{unknown[0]}; use {', '.join(view.QUERY_KINDS)}.")
    return data


def run_signature(run: dict) -> str:
    """Changes whenever a poll would show something new."""
    calls = run.get("calls") or []
    return "|".join(str(x) for x in (run.get("status"), run.get("active"),
                                     sum(c.get("status") != "planned" for c in calls), len(run.get("leads") or [])))


def raw_choices(run: dict) -> list[tuple[str, int]]:
    return [(f"{c['index']:02d} · {view.ROUTES.get(c.get('route'), c.get('route'))} · {c.get('market')} · "
             f"{view.clip(c.get('q'), 60)}", c["index"])
            for c in run.get("calls") or [] if c.get("raw_file") and isinstance(c.get("index"), int)]


def reference_asset(run: dict) -> tuple[str | None, str | None]:
    image = (run.get("source") or {}).get("image") or {}
    try:
        return str(uuid.UUID(str(image.get("asset_id")))), image.get("name")
    except ValueError:
        return None, None


def lead_filter(text, route, market, kind, sort, flags) -> tuple[view.LeadFilter, bool]:
    flags = flags or []
    return view.LeadFilter(text=text or "", route=route or "all", market=market or "all", kind=kind or "all",
                           sort=sort or "rank", no_listings="no_listings" in flags,
                           shop_link="shop_link" in flags), "thumbnails" in flags


def run_list() -> list[tuple[str, str]]:
    return [(view.run_label(item), item["id"]) for item in call("GET", "/discovery/runs")]


def fetch_account() -> tuple[dict | None, str | None]:
    try:
        return call("GET", "/discovery/account", timeout=20), None
    except ApiError as exc:
        return None, str(exc)


# --- the tab -------------------------------------------------------------------------


def build(tab: gr.Tab) -> None:
    """Build the tab's content inside `tab`; it loads when the tab is first opened."""
    loaded_st = gr.State(False)
    settings_st = gr.State(None)
    run_st = gr.State(None)
    replay_st = gr.State(None)
    version_st = gr.State("")
    from_st = gr.State(None)
    log_open_st = gr.State(False)
    timer = gr.Timer(POLL_SECONDS, active=False)

    gr.Markdown(
        "Find where a garment like yours is sold, with Google Shopping and web results through SerpApi. "
        "Every search is planned first and nothing is sent to SerpApi until you run the plan. "
        "Leads are search results, not verified offers."
    )
    with gr.Column() as loading:
        gr.Markdown("_Loading saved runs…_")
    # Gradio 6.18 loses visibility updates in three cases: for components never on screen (in
    # a closed tab, or created hidden), and for components (not layouts) whose parent is shown
    # again, which resets them to how they were created. So the content loads when the tab is
    # opened, everything shown or hidden later starts visible, only layouts are toggled
    # (components sit in a gr.Column of their own), and showing a panel sets all of them.
    with gr.Row(visible=False) as body:
        with gr.Column(scale=1, min_width=280):
            new_btn = gr.Button("New web search", variant="primary")
            runs_radio = gr.Radio(label="Saved runs", choices=[], elem_classes=["sd-runlist"])
            refresh_btn = gr.Button("Refresh list", size="sm")
            side_msg = gr.Markdown()
            gr.Markdown(LEGEND)

        with gr.Column(scale=4):
            with gr.Column() as form_panel:
                gr.Markdown("### New web search")
                keys_md = gr.Markdown()
                mode = gr.Radio(
                    [("From a reference image: Cursor writes the queries", "image"),
                     ("My own queries: no LLM", "queries")],
                    value="image", label="Queries",
                )
                with gr.Row() as image_row:
                    image_in = gr.Image(label="Reference image", type="filepath", image_mode=None,
                                        sources=["upload", "clipboard"], height=280)
                    with gr.Column():
                        text_in = gr.Textbox(label="What to change or insist on (optional)", lines=3,
                                             max_length=2000, placeholder="e.g. fluffy hood instead of fur")
                        gr.Markdown(
                            "The image, without its metadata, and this text are sent to Cursor, which writes "
                            "the queries and translates them for the languages of your markets. You see the "
                            "queries and every planned search before anything is sent to SerpApi."
                        )
                with gr.Column() as queries_col:
                    from_md = gr.Markdown()
                    queries_df = gr.Dataframe(
                        headers=QUERY_COLUMNS, datatype=["str"] * 4, type="array", column_count=4,
                        interactive=True, wrap=True, max_height=320, column_widths=["14%", "30%", "30%", "26%"],
                        label="Queries per language (leave a cell empty to skip that kind of query)",
                    )
                    queries_file = gr.File(label="Or load a queries file (.json)", file_types=[".json"],
                                           type="filepath", height=110)
                    gr.Markdown(f"_{QUERIES_FILE_HELP}_")
                markets_in = gr.CheckboxGroup(label="Markets: Google country and language", choices=[])
                budget_in = gr.Slider(1, 60, value=12, step=1, label="Search budget",
                                      info="The most SerpApi searches this run may use; each costs one "
                                           "search of your SerpApi plan.")
                with gr.Column() as steps_box:
                    steps_in = gr.CheckboxGroup(label="Extra searches from discovery.toml", choices=[])
                plan_btn = gr.Button("Plan searches", variant="primary")
                plan_msg = gr.Markdown()

            with gr.Column() as run_panel:
                with gr.Row(equal_height=False):
                    with gr.Column(scale=1, min_width=150) as ref_box:
                        ref_img = gr.Image(show_label=False, interactive=False, height=190, buttons=[])
                    with gr.Column(scale=5):
                        overview = gr.HTML(apply_default_css=False)
                        with gr.Row():
                            with gr.Column(min_width=160) as run_box:
                                run_btn = gr.Button("Run searches", variant="primary")
                            with gr.Column(min_width=160) as stop_box:
                                stop_btn = gr.Button("Stop after this search", variant="stop")
                            with gr.Column(min_width=160) as reuse_box:
                                reuse_btn = gr.Button("New search with these queries")
                            with gr.Column(min_width=160) as replay_box:
                                replay_btn = gr.Button("Replay offline")
                            with gr.Column(min_width=160):
                                log_btn = gr.Button("Show full log")
                        run_msg = gr.Markdown()
                with gr.Column() as log_panel:
                    log_code = gr.Code(label="Full log: settings, model replies, every search and every lead",
                                       language=None, lines=18, max_lines=40, interactive=False,
                                       buttons=["copy", "download"])
                    raw_dd = gr.Dropdown(label="Saved SerpApi response (the API key was removed before saving)",
                                         choices=[], value=None)
                    with gr.Column() as raw_box:
                        raw_code = gr.Code(language="json", lines=12, max_lines=40, interactive=False,
                                           buttons=["copy", "download"], show_label=False)
                with gr.Accordion("What was searched for", open=False):
                    intent = gr.HTML(apply_default_css=False)
                with gr.Column() as filters_col:
                    with gr.Row():
                        find_in = gr.Textbox(show_label=False, placeholder="Filter by title, shop, site or text",
                                             scale=2, min_width=200)
                        route_f = gr.Dropdown(show_label=False, choices=[("All", "all")], value="all",
                                              scale=1, min_width=150)
                        market_f = gr.Dropdown(show_label=False, choices=[("All markets", "all")], value="all",
                                               scale=1, min_width=150)
                        kind_f = gr.Dropdown(show_label=False, choices=[("All kinds", "all")], value="all",
                                             scale=1, min_width=150)
                        sort_f = gr.Dropdown(show_label=False, choices=view.SORTS, value="rank",
                                             scale=1, min_width=220)
                    flags_in = gr.CheckboxGroup(show_label=False, choices=view.FLAGS, value=["thumbnails"])
                results = gr.HTML(apply_default_css=False, max_height="78vh", elem_id="sd-results")
                with gr.Accordion("Searches", open=False) as plan_acc:
                    plan = gr.HTML(apply_default_css=False)
                with gr.Accordion("Summary and diversity", open=False) as summary_acc:
                    summary_box = gr.HTML(apply_default_css=False)

    filters = [find_in, route_f, market_f, kind_f, sort_f, flags_in]
    everything = [
        loaded_st, body, loading, settings_st, run_st, replay_st, version_st, from_st, log_open_st, timer,
        runs_radio, side_msg,
        form_panel, keys_md, mode, image_row, image_in, text_in, queries_col, from_md, queries_df,
        markets_in, budget_in, steps_box, steps_in, plan_msg,
        run_panel, ref_box, ref_img, overview, run_box, stop_box, reuse_box, replay_box, replay_btn, log_btn,
        run_msg, log_panel, log_code, raw_dd, raw_box, raw_code, intent, filters_col, *filters, results,
        plan_acc, plan, summary_acc, summary_box,
    ]

    # --- rendering a run ----------------------------------------------------------

    def run_view(run: dict, replay: dict | None, f: view.LeadFilter, thumbnails: bool,
                 account: dict | None = None, account_error: str | None = None) -> dict:
        source = replay or run
        leads, summary = source.get("leads") or [], source.get("summary")
        status = run.get("status")
        planned = status in ("planned", "preparing")
        running = status == "running"
        choices = view.filter_choices(run, leads)

        def keep(value: str, options: list[tuple[str, str]]) -> str:
            return value if value in {v for _, v in options} else "all"

        note = None
        if replay:
            note = (f"Showing leads rebuilt offline from the saved responses with the current code and "
                    f"{replay.get('settings_source')}; no searches were spent and the run is unchanged.")
        counts = view.call_counts(run)
        shown = view.filter_leads(leads, f)
        return {
            run_st: run,
            replay_st: replay,
            version_st: run_signature(run),
            timer: gr.Timer(active=running),
            overview: view.overview_html(run, leads, summary, account, account_error, note),
            intent: view.intent_html(run),
            results: view.results_html(run, leads, shown, thumbnails, summary, f.sort),
            plan: view.plan_html(run),
            plan_acc: gr.Accordion(visible=not planned,
                                   label=f"Searches: {counts['done']} done of {counts['planned']}"
                                         + (f", {counts['skipped']} not sent" if counts["skipped"] else "")),
            summary_box: view.summary_html(summary),
            summary_acc: gr.Accordion(visible=not planned and summary is not None),
            filters_col: gr.Column(visible=bool(leads)),
            route_f: gr.Dropdown(choices=choices["route"], value=keep(f.route, choices["route"])),
            market_f: gr.Dropdown(choices=choices["market"], value=keep(f.market, choices["market"])),
            kind_f: gr.Dropdown(choices=choices["kind"], value=keep(f.kind, choices["kind"])),
            run_box: gr.Column(visible=status == "planned"),
            stop_box: gr.Column(visible=running and bool(run.get("active"))),
            reuse_box: gr.Column(visible=bool(run.get("queries")) and not running),
            replay_box: gr.Column(visible=bool(raw_choices(run)) and not running),
            replay_btn: gr.Button(value="Show saved leads" if replay else "Replay offline"),
            raw_dd: gr.Dropdown(choices=raw_choices(run)),
        }

    def open_view(run: dict, flags: list[str]) -> dict:
        """A freshly opened run: filters reset, log closed, quota shown for plans."""
        account = account_error = None
        if run.get("status") == "planned":
            account, account_error = fetch_account()
        asset_id, name = reference_asset(run)
        updates = run_view(run, None, view.LeadFilter(), "thumbnails" in (flags or []), account, account_error)
        updates.update({
            form_panel: gr.Column(visible=False),
            run_panel: gr.Column(visible=True),
            ref_box: gr.Column(visible=asset_id is not None),
            ref_img: gr.Image(value=fetch_image(f"/assets/{asset_id}"), label=name) if asset_id else None,
            find_in: "",
            sort_f: "rank",
            log_open_st: False,
            log_panel: gr.Column(visible=False),
            log_btn: gr.Button(value="Show full log"),
            log_code: "",
            raw_dd: gr.Dropdown(choices=raw_choices(run), value=None),
            raw_box: gr.Column(visible=False),
            raw_code: "",
            run_msg: "",
        })
        return updates

    def form_view(settings: dict | None, from_run: dict | None = None) -> dict:
        """The new-search form, empty or prefilled with a run's queries and settings."""
        updates: dict = {
            form_panel: gr.Column(visible=True),
            run_panel: gr.Column(visible=False),
            run_st: None,
            replay_st: None,
            timer: gr.Timer(active=False),
            runs_radio: gr.Radio(value=None),
            plan_msg: "",
            from_st: None,
            from_md: "",
        }
        if not settings:
            updates.update({image_row: gr.Row(visible=False), queries_col: gr.Column(visible=False),
                            steps_box: gr.Column(visible=False)})
            return updates
        markets = settings["default_markets"]
        budget = settings["max_calls"]
        steps = [value for _, value in step_choices(settings)]
        queries: dict = {}
        if from_run:
            known = {m["id"] for m in settings["markets"]}
            saved = from_run.get("settings") or {}
            markets = [m for m in saved.get("markets", []) if m in known] or markets
            budget = min(saved.get("max_calls") or budget, settings["hard_max_calls"])
            saved_steps = saved.get("steps") or []
            steps = [value for value in steps
                     if any(s.get("with_modifiers" if value == "modifiers" else "with_sites") for s in saved_steps)]
            queries = from_run.get("queries") or {}
            updates.update({
                from_st: from_run["id"],
                from_md: (f"Reusing the queries of run **{from_run['id'][:8]}**: edit them freely. "
                          "The new run keeps a link to that run and its image interpretation."),
            })
        own = bool(from_run) or not settings["cursor_configured"]
        updates.update({
            mode: "queries" if own else "image",
            image_row: gr.Row(visible=not own),
            queries_col: gr.Column(visible=own),
            queries_df: query_rows(queries, languages_of(settings, markets)),
            markets_in: gr.CheckboxGroup(choices=market_choices(settings), value=markets),
            budget_in: gr.Slider(maximum=settings["hard_max_calls"], value=budget),
            steps_box: gr.Column(visible=bool(step_choices(settings))),
            steps_in: gr.CheckboxGroup(choices=step_choices(settings), value=steps),
        })
        if not from_run:
            updates.update({image_in: None, text_in: ""})
        return updates

    # --- handlers -----------------------------------------------------------------------

    def load_tab(loaded, run, flags):
        if loaded:
            return refresh(run)
        updates: dict = {body: gr.Row(visible=True), loading: gr.Column(visible=False)}
        notes = []
        try:
            settings = call("GET", "/discovery/settings")
        except ApiError as exc:
            settings = None
            notes.append(f"**Web discovery is not available:** {exc}")
        else:
            if not settings["serpapi_configured"]:
                notes.append("**SERPAPI_API_KEY is not set:** you can plan and open saved runs, "
                             "but not run searches. Add it to `.env` and restart the API.")
            if not settings["cursor_configured"]:
                notes.append("**CURSOR_API_KEY or INTERPRET_MODEL is not set:** write your own queries, "
                             "or add them to `.env` to have Cursor write queries from an image.")
        updates[settings_st] = settings
        updates[loaded_st] = settings is not None
        updates[keys_md] = "  \n".join(notes)
        try:
            runs = run_list()
        except ApiError as exc:
            runs = []
            updates[side_msg] = f"**Error:** {exc}"
        updates.update(form_view(settings))
        updates[runs_radio] = gr.Radio(choices=runs, value=runs[0][1] if runs else None)
        if runs:
            try:
                updates.update(open_view(call("GET", f"/discovery/runs/{runs[0][1]}"), flags))
            except ApiError as exc:
                updates[side_msg] = f"**Error:** {exc}"
        return updates

    def refresh(run):
        try:
            return {runs_radio: gr.Radio(choices=run_list(), value=run["id"] if run else None), side_msg: ""}
        except ApiError as exc:
            return {side_msg: f"**Error:** {exc}"}

    def open_run(run_id, flags):
        if not run_id:
            return {}
        try:
            return open_view(call("GET", f"/discovery/runs/{run_id}"), flags)
        except ApiError as exc:
            raise gr.Error(str(exc))

    def switch_mode(value):
        return {image_row: gr.Row(visible=value == "image"), queries_col: gr.Column(visible=value == "queries")}

    def sync_languages(settings, markets, rows):
        if not settings:
            return gr.skip()
        return add_language_rows(rows, languages_of(settings, markets))

    def load_file(path, settings, markets):
        if not path or not settings:
            return gr.skip(), gr.skip()
        try:
            data = read_queries_file(path)
        except (OSError, ValueError) as exc:
            raise gr.Error(str(exc))
        rows = query_rows({code: {k: v if isinstance(v, str) else "" for k, v in entry.items()}
                           for code, entry in data.items()}, languages_of(settings, markets))
        return rows, f"Loaded **{Path(path).name}**. Check the queries, then plan."

    def planning_note(value):
        note = ("_Cursor is reading the image and writing the queries; this can take a minute…_"
                if value == "image" else "_Saving the plan…_")
        return {plan_msg: note, plan_btn: gr.Button(interactive=False)}

    def submit_plan(settings, mode_value, image_path, text, rows, markets, budget, steps, from_record) -> dict:
        if not settings:
            raise ValueError("The discovery settings could not be loaded; see the message above.")
        if not markets:
            raise ValueError("Choose at least one market.")
        choices = {value for _, value in step_choices(settings)}
        body: dict[str, Any] = {
            "markets": markets,
            "max_calls": int(budget),
            "no_modifiers": "modifiers" in choices and "modifiers" not in (steps or []),
            "no_sites": "sites" in choices and "sites" not in (steps or []),
        }
        if mode_value != "image":
            body.update(source="queries", queries=rows_to_queries(rows), from_record=from_record)
            return call("POST", "/discovery/runs", json=body)
        if not image_path:
            raise ValueError("Add a reference image, or choose “My own queries”.")
        if not settings["cursor_configured"]:
            raise ValueError("CURSOR_API_KEY and INTERPRET_MODEL must be set in .env to write queries "
                             "from an image. Choose “My own queries” instead.")
        with open(image_path, "rb") as handle:
            asset = call("POST", "/assets", files={"file": (Path(image_path).name, handle.read())})
        body.update(source="image", asset_id=asset["id"], text=text or "")
        return call("POST", "/discovery/runs", json=body, timeout=PLAN_TIMEOUT)

    def plan_run(settings, mode_value, image_path, text, rows, markets, budget, steps, from_record, flags):
        try:
            result = submit_plan(settings, mode_value, image_path, text, rows, markets, budget, steps, from_record)
        except (ApiError, ValueError, OSError) as exc:
            updates = {plan_msg: f"**Could not plan:** {exc}"}
            if "saved in run" in str(exc):
                updates.update(refresh(None))
            return updates
        run = result["run"]
        updates = open_view(run, flags)
        updates[runs_radio] = gr.Radio(choices=run_list(), value=run["id"])
        updates[plan_msg] = ""
        if result.get("notes"):
            updates[run_msg] = "  \n".join(f"_{note}_" for note in result["notes"])
        return updates

    def start(run, *values):
        try:
            fresh = call("POST", f"/discovery/runs/{run['id']}/start", timeout=START_TIMEOUT)
        except ApiError as exc:
            raise gr.Error(str(exc))
        f, thumbnails = lead_filter(*values)
        updates = run_view(fresh, None, f, thumbnails)
        updates[run_msg] = ""
        updates.update(refresh(fresh))
        return updates

    def stop(run, *values):
        try:
            fresh = call("POST", f"/discovery/runs/{run['id']}/cancel")
        except ApiError as exc:
            raise gr.Error(str(exc))
        f, thumbnails = lead_filter(*values)
        updates = run_view(fresh, None, f, thumbnails)
        updates[run_msg] = "_Stopping: the search already sent finishes, no new ones are sent._"
        return updates

    def poll(run, version, *values):
        if not run:
            return {timer: gr.Timer(active=False)}
        try:
            fresh = call("GET", f"/discovery/runs/{run['id']}", timeout=10)
        except ApiError:
            return {}
        if run_signature(fresh) == version:
            return {}
        f, thumbnails = lead_filter(*values)
        updates = run_view(fresh, None, f, thumbnails)
        if fresh.get("status") != "running":
            updates[run_msg] = ""
            updates.update(refresh(fresh))
        return updates

    def toggle_replay(run, replay, *values):
        new = None
        if not replay:
            try:
                new = call("GET", f"/discovery/runs/{run['id']}/replay", timeout=60)
            except ApiError as exc:
                raise gr.Error(str(exc))
        f, thumbnails = lead_filter(*values)
        updates = run_view(run, new, f, thumbnails)
        updates[run_msg] = "  \n".join(f"_{note}_" for note in (new or {}).get("notes", []))
        updates.update({log_panel: gr.Column(visible=False), log_btn: gr.Button(value="Show full log"),
                        log_open_st: False})
        return updates

    def toggle_log(run, replay, is_open):
        if is_open:
            return {log_panel: gr.Column(visible=False), log_btn: gr.Button(value="Show full log"),
                    log_open_st: False}
        try:
            text = call("GET", f"/discovery/runs/{run['id']}/log",
                        params={"replayed": "true" if replay else "false"}, timeout=60)["text"]
        except ApiError as exc:
            raise gr.Error(str(exc))
        return {log_panel: gr.Column(visible=True), log_btn: gr.Button(value="Hide full log"),
                log_code: text, log_open_st: True}

    def show_raw(run, index):
        if index is None or not run:
            return {raw_box: gr.Column(visible=False), raw_code: ""}
        try:
            response = call("GET", f"/discovery/runs/{run['id']}/raw/{int(index)}")
        except ApiError as exc:
            raise gr.Error(str(exc))
        return {raw_box: gr.Column(visible=True), raw_code: json.dumps(response, indent=2, ensure_ascii=False)}

    def refilter(run, replay, *values):
        if not run:
            return gr.skip()
        f, thumbnails = lead_filter(*values)
        source = replay or run
        leads = source.get("leads") or []
        return view.results_html(run, leads, view.filter_leads(leads, f), thumbnails, source.get("summary"), f.sort)

    # --- wiring ---------------------------------------------------------------------------

    quiet = {"show_progress": "hidden"}
    tab.select(load_tab, inputs=[loaded_st, run_st, flags_in], outputs=everything, show_progress_on=[loading])
    refresh_btn.click(refresh, inputs=[run_st], outputs=everything)
    runs_radio.input(open_run, inputs=[runs_radio, flags_in], outputs=everything,
                     show_progress="minimal", show_progress_on=[overview])
    new_btn.click(form_view, inputs=[settings_st], outputs=everything, **quiet)
    reuse_btn.click(form_view, inputs=[settings_st, run_st], outputs=everything, **quiet)

    mode.input(switch_mode, inputs=[mode], outputs=[image_row, queries_col], **quiet)
    markets_in.input(sync_languages, inputs=[settings_st, markets_in, queries_df], outputs=[queries_df], **quiet)
    queries_file.upload(load_file, inputs=[queries_file, settings_st, markets_in], outputs=[queries_df, plan_msg])
    plan_btn.click(planning_note, inputs=[mode], outputs=[plan_msg, plan_btn], **quiet).then(
        plan_run,
        inputs=[settings_st, mode, image_in, text_in, queries_df, markets_in, budget_in, steps_in, from_st, flags_in],
        outputs=everything, show_progress="minimal", show_progress_on=[plan_msg],
    ).then(lambda: gr.Button(interactive=True), outputs=[plan_btn], **quiet)

    run_btn.click(start, inputs=[run_st, *filters], outputs=everything,
                  show_progress="minimal", show_progress_on=[overview], trigger_mode="once")
    stop_btn.click(stop, inputs=[run_st, *filters], outputs=everything, **quiet)
    timer.tick(poll, inputs=[run_st, version_st, *filters], outputs=everything, **quiet)
    replay_btn.click(toggle_replay, inputs=[run_st, replay_st, *filters], outputs=everything,
                     show_progress="minimal", show_progress_on=[results])
    log_btn.click(toggle_log, inputs=[run_st, replay_st, log_open_st],
                  outputs=[log_panel, log_btn, log_code, log_open_st], **quiet)
    raw_dd.input(show_raw, inputs=[run_st, raw_dd], outputs=[raw_box, raw_code], **quiet)

    for control in filters:
        control.input(refilter, inputs=[run_st, replay_st, *filters], outputs=[results],
                      trigger_mode="always_last", **quiet)
