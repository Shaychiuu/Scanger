"""Scanger frontend (Gradio). Talks only to the Scanger API.

The open session's ID is the only session state kept in the browser; history is
always re-read from the API, which reads it from PostgreSQL.

Run from the repository root (the Scanger and VisualMatch APIs must be running):
    python -m scanger.frontend
"""

import io
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import gradio as gr
import requests
from PIL import Image, ImageDraw

from scanger.config import scanger_api_url

API_URL = scanger_api_url()
HTTP = requests.Session()
SEARCH_TIMEOUT = 600  # the first search loads the model in the VisualMatch API
MODE_LABELS = {"image": "image only", "text": "text only", "composed": "image + text"}


class ApiError(Exception):
    pass


def call(method: str, path: str, timeout: float = 30, **kwargs) -> dict | list:
    try:
        response = HTTP.request(method, f"{API_URL}{path}", timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise ApiError(f"Scanger API is not reachable at {API_URL}. Is it running?") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text[:300]
        raise ApiError(f"{detail}")
    return response.json()


@lru_cache(maxsize=1024)
def _image_bytes(path: str) -> bytes:
    # Stored assets and saved results are immutable, so caching is safe.
    # Failures raise and are therefore not cached.
    response = HTTP.get(f"{API_URL}{path}", timeout=30)
    response.raise_for_status()
    return response.content


def placeholder(text: str = "Image missing") -> Image.Image:
    image = Image.new("RGB", (256, 256), (225, 225, 225))
    ImageDraw.Draw(image).text((70, 120), text, fill=(90, 90, 90))
    return image


def fetch_image(path: str | None) -> Image.Image:
    if not path:
        return placeholder()
    try:
        return Image.open(io.BytesIO(_image_bytes(path)))
    except Exception:
        return placeholder()


def local_time(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")


# --- sessions ----------------------------------------------------------------


def session_choices() -> list[tuple[str, str]]:
    sessions = call("GET", "/sessions")
    return [(f"{s['title']}  ·  {local_time(s['updated_at'])}", s["id"]) for s in sessions]


def load_page():
    try:
        choices = session_choices()
    except ApiError as exc:
        return gr.update(choices=[]), f"**Error:** {exc}", str(uuid.uuid4())
    value = choices[0][1] if choices else None
    return gr.update(choices=choices, value=value), "", str(uuid.uuid4())


def create_session(title: str):
    try:
        session = call("POST", "/sessions", json={"title": title})
        choices = session_choices()
    except ApiError as exc:
        raise gr.Error(str(exc))
    return gr.update(choices=choices, value=session["id"]), "", f"Created **{session['title']}**."


def rename_session(session_id: str | None, title: str):
    if not session_id:
        raise gr.Error("Open a session first.")
    try:
        session = call("PATCH", f"/sessions/{session_id}", json={"title": title})
        choices = session_choices()
    except ApiError as exc:
        raise gr.Error(str(exc))
    return gr.update(choices=choices, value=session_id), "", f"Renamed to **{session['title']}**."


def open_session(session_id: str | None):
    # Switching sessions forgets any reused reference from the previous one.
    return session_id, None


# --- searching ---------------------------------------------------------------


def describe_query(image_path, text, alpha, reuse) -> str:
    has_image, has_text = image_path is not None, bool((text or "").strip())
    if not (has_image or has_text):
        return "_Add a reference image, a description, or both._"
    mode = "composed" if has_image and has_text else ("image" if has_image else "text")
    lines = [f"**Will search:** {MODE_LABELS[mode]}"]
    if has_image:
        if reuse:
            lines.append(f"**Reference:** reused from turn {reuse['ordinal']} (shown on the left)")
        else:
            lines.append(f"**Reference:** {Path(image_path).name} (shown on the left)")
    if has_text:
        lines.append(f"**Description:** {text.strip()}")
    if mode == "composed":
        lines.append(f"**Image weight:** {alpha:.2f}")
    return "  \n".join(lines)


def search(session_id, image_path, text, alpha, reuse, request_id, version):
    if not session_id:
        raise gr.Error("Create or open a session first.")
    try:
        asset_id = None
        if image_path is not None:
            if reuse:
                asset_id = reuse["asset_id"]
            else:
                with open(image_path, "rb") as handle:
                    asset = call(
                        "POST",
                        "/assets",
                        files={"file": (Path(image_path).name, handle.read())},
                    )
                asset_id = asset["id"]
        turn = call(
            "POST",
            f"/sessions/{session_id}/turns",
            timeout=SEARCH_TIMEOUT,
            json={
                "prompt_text": text,
                "reference_asset_id": asset_id,
                "alpha": alpha,
                "client_request_id": request_id,
            },
        )
    except ApiError as exc:
        raise gr.Error(str(exc))

    run = turn["runs"][-1]
    if run["status"] == "completed":
        message = f"Turn {turn['ordinal']}: {len(run['results'])} results."
    else:
        message = f"Turn {turn['ordinal']} {run['status']}: {run['error_message']}"
    # A fresh request ID: the next click is a new search, not a repeat.
    return version + 1, str(uuid.uuid4()), message


def retry(turn_id: str, version: int):
    try:
        run = call("POST", f"/turns/{turn_id}/runs", timeout=SEARCH_TIMEOUT)
    except ApiError as exc:
        raise gr.Error(str(exc))
    return version + 1, f"Run {run['attempt']} {run['status']}."


def reuse_reference(turn: dict):
    ref = turn["reference_asset"]
    return fetch_image(ref["url"]), {"asset_id": ref["id"], "ordinal": turn["ordinal"]}


# --- history -----------------------------------------------------------------


def run_summary(run: dict) -> str:
    parts = [
        f"**Run {run['attempt']}**",
        MODE_LABELS.get(run["search_mode"], run["search_mode"]),
        run["status"],
    ]
    if run["status"] == "completed":
        parts.append(f"{len(run['results'])} results")
    if run["model_name"]:
        parts.append(f"model {run['model_name']}")
    if "alpha" in run["configuration"]:
        parts.append(f"image weight {run['configuration']['alpha']:.2f}")
    text = "  ·  ".join(parts)
    if run["score_kind"] == "cosine_similarity":
        text += "  \n_Scores are cosine similarity (higher = closer); they are not probabilities._"
    if run["error_message"]:
        text += f"  \n**Error:** {run['error_message']}"
    return text


def result_gallery(run: dict) -> None:
    if not run["results"]:
        return
    items = []
    for r in run["results"]:
        meta = r["metadata"]
        label = " ".join(x for x in (meta.get("color"), meta.get("category2")) if x)
        score = f"{r['raw_score']:.3f}" if r["raw_score"] is not None else "n/a"
        items.append((fetch_image(r["image_url"]), f"#{r['rank']} {label} · {score} · {r['source_item_id']}"))
    gr.Gallery(value=items, columns=5, height="auto", show_label=False, allow_preview=True)


with gr.Blocks(title="Scanger") as demo:
    session_id = gr.State(None)
    history_version = gr.State(0)
    request_id = gr.State(None)
    reuse = gr.State(None)

    gr.Markdown(
        "# Scanger\nLocal clothing search. Results are images from the DeepFashion "
        "dataset, not products for sale."
    )
    with gr.Row():
        with gr.Column(scale=1, min_width=260):
            session_dd = gr.Dropdown(label="Session", choices=[], interactive=True)
            new_title = gr.Textbox(label="New session title", placeholder="e.g. brown boots")
            create_btn = gr.Button("Create session")
            rename_title = gr.Textbox(label="Rename open session")
            rename_btn = gr.Button("Rename")
            status = gr.Markdown()

        with gr.Column(scale=4):
            with gr.Row():
                image_in = gr.Image(
                    label="Reference image",
                    type="filepath",
                    image_mode=None,  # pass the uploaded file through unchanged
                    sources=["upload", "clipboard"],
                    height=300,
                )
                with gr.Column():
                    text_in = gr.Textbox(label="Description (optional)", lines=3)
                    alpha_in = gr.Slider(
                        0, 1, value=0.5, step=0.05,
                        label="Image weight for image + text (1 = image only, 0 = text only)",
                    )
                    preview = gr.Markdown(describe_query(None, "", 0.5, None))
                    search_btn = gr.Button("Search", variant="primary")

            @gr.render(inputs=[session_id, history_version])
            def render_history(sid, _version):
                if not sid:
                    gr.Markdown("_Create a session or open one to start._")
                    return
                try:
                    detail = call("GET", f"/sessions/{sid}")
                except ApiError as exc:
                    gr.Markdown(f"**Error:** {exc}")
                    return
                gr.Markdown(f"## {detail['title']}")
                if not detail["turns"]:
                    gr.Markdown("_No searches yet in this session._")
                for turn in detail["turns"]:
                    with gr.Group():
                        gr.Markdown(
                            f"### Turn {turn['ordinal']}  ·  {local_time(turn['created_at'])}  \n"
                            f"**Description:** {turn['prompt_text'] or '—'}"
                        )
                        with gr.Row():
                            ref = turn["reference_asset"]
                            with gr.Column(scale=1, min_width=160):
                                if ref:
                                    gr.Image(
                                        value=fetch_image(ref["url"]),
                                        label=ref["original_name"] or "Reference",
                                        interactive=False,
                                        height=180,
                                    )
                                    reuse_btn = gr.Button("Use this reference", size="sm")
                                    reuse_btn.click(
                                        lambda t=turn: reuse_reference(t),
                                        outputs=[image_in, reuse],
                                    )
                                else:
                                    gr.Markdown("_No reference image_")
                                retry_btn = gr.Button("Run again", size="sm")
                                retry_btn.click(
                                    lambda v, tid=turn["id"]: retry(tid, v),
                                    inputs=[history_version],
                                    outputs=[history_version, status],
                                )
                            with gr.Column(scale=5):
                                runs = turn["runs"]
                                for run in runs[:-1]:
                                    with gr.Accordion(
                                        f"Earlier run {run['attempt']} ({run['status']})",
                                        open=False,
                                    ):
                                        gr.Markdown(run_summary(run))
                                        result_gallery(run)
                                if runs:
                                    gr.Markdown(run_summary(runs[-1]))
                                    result_gallery(runs[-1])

    query_inputs = [image_in, text_in, alpha_in, reuse]
    for trigger in (image_in.change, text_in.change, alpha_in.change, reuse.change):
        trigger(describe_query, inputs=query_inputs, outputs=preview)
    # A new upload or a cleared image replaces any reused reference.
    image_in.upload(lambda: None, outputs=reuse)
    image_in.clear(lambda: None, outputs=reuse)

    demo.load(load_page, outputs=[session_dd, status, request_id])
    session_dd.change(open_session, inputs=session_dd, outputs=[session_id, reuse])
    create_btn.click(create_session, inputs=new_title, outputs=[session_dd, new_title, status])
    rename_btn.click(
        rename_session, inputs=[session_id, rename_title], outputs=[session_dd, rename_title, status]
    )
    search_btn.click(
        search,
        inputs=[session_id, image_in, text_in, alpha_in, reuse, request_id, history_version],
        outputs=[history_version, request_id, status],
        trigger_mode="once",
    )


if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7861, share=False)
