import io
import uuid

import pytest
import requests
from PIL import Image
from sqlalchemy import select

from scanger import api, history
from scanger.config import UploadLimits
from scanger.models import SearchResult, SearchRun, Session, Turn
from scanger.retrieval import (
    AdapterInfo,
    RetrievalError,
    RetrievedItem,
    VisualMatchHttpAdapter,
)


class FixtureAdapter:
    """Deterministic stand-in for VisualMatch; records the queries it receives."""

    info = AdapterInfo(
        backend="fixture",
        model_name="fixture-model",
        index_version="fixture-index-1",
        dataset_version="fixture-dataset-1",
        score_kind="cosine_similarity",
        higher_is_better=True,
        result_limit=3,
    )

    def __init__(self, fail_with: Exception | None = None):
        self.fail_with = fail_with
        self.calls = []

    def search(self, mode, text, image, alpha):
        self.calls.append((mode, text, image, alpha))
        if self.fail_with:
            raise self.fail_with
        return [
            RetrievedItem("dataset", f"ITEM_{mode}_{i}", f"deepfashion-inshop:data:{i}", 1.0 - i / 10, {"color": "Black"})
            for i in range(5)  # more than result_limit; only 3 are kept
        ]


def png_bytes(color=(10, 120, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def asset(db, data_root):
    from scanger import assets

    return assets.store_image(db, png_bytes(), "ref.png", data_root, UploadLimits())


# --- sessions ----------------------------------------------------------------


def test_create_rename_and_list_by_recent_activity(db):
    first = history.create_session(db, "  brown boots ")
    second = history.create_session(db, "white hat")
    assert first.title == "brown boots"
    assert [s.id for s in history.list_sessions(db)] == [second.id, first.id]

    history.rename_session(db, first.id, "dark brown boots")
    assert [s.title for s in history.list_sessions(db)] == ["dark brown boots", "white hat"]


@pytest.mark.parametrize("title", ["", "   ", "x" * 201])
def test_invalid_titles_are_rejected(db, title):
    with pytest.raises(history.InvalidRequest):
        history.create_session(db, title)


# --- turns and runs -----------------------------------------------------------


@pytest.mark.parametrize(
    "with_image, text, mode",
    [(True, None, "image"), (False, "black dress", "text"), (True, "but in red", "composed")],
)
def test_turn_persists_query_run_and_ranked_results(db, data_root, asset, with_image, text, mode):
    session = history.create_session(db, "s")
    adapter = FixtureAdapter()
    request = history.TurnRequest(
        prompt_text=text, reference_asset_id=asset.id if with_image else None, alpha=0.7
    )
    turn = history.submit_turn(db, session.id, request, adapter, data_root)

    db.expire_all()
    saved = history.get_session_detail(db, session.id).turns
    assert [t.id for t in saved] == [turn.id]
    run = saved[0].runs[0]
    assert (run.status, run.search_mode, run.attempt) == ("completed", mode, 1)
    assert (run.model_name, run.index_version, run.dataset_version) == (
        "fixture-model", "fixture-index-1", "fixture-dataset-1",
    )
    assert (run.score_kind, run.higher_is_better, run.result_limit) == ("cosine_similarity", True, 3)
    assert run.configuration_version == 1
    assert ("alpha" in run.configuration) == (mode == "composed")
    assert [r.rank for r in run.results] == [1, 2, 3]
    assert run.results[0].source_item_id == f"ITEM_{mode}_0"
    assert run.started_at and run.finished_at

    sent_mode, sent_text, sent_image, _ = adapter.calls[0]
    assert sent_mode == mode and sent_text == text
    assert (sent_image is not None) == with_image
    if with_image:
        assert sent_image.data == png_bytes()


def test_turns_are_numbered_per_session_and_touch_activity(db, data_root):
    a = history.create_session(db, "a")
    b = history.create_session(db, "b")
    adapter = FixtureAdapter()
    for text in ("one", "two"):
        history.submit_turn(db, a.id, history.TurnRequest(prompt_text=text), adapter, data_root)
    history.submit_turn(db, b.id, history.TurnRequest(prompt_text="three"), adapter, data_root)
    history.submit_turn(db, a.id, history.TurnRequest(prompt_text="four"), adapter, data_root)

    db.expire_all()
    assert [(t.ordinal, t.prompt_text) for t in history.get_session_detail(db, a.id).turns] == [
        (1, "one"), (2, "two"), (3, "four"),
    ]
    assert [s.title for s in history.list_sessions(db)] == ["a", "b"]


def test_empty_query_is_rejected_without_saving(db, data_root):
    session = history.create_session(db, "s")
    with pytest.raises(history.InvalidRequest):
        history.submit_turn(db, session.id, history.TurnRequest(prompt_text="  "), FixtureAdapter(), data_root)
    assert db.scalars(select(Turn)).all() == []


def test_repeated_request_id_returns_the_same_turn(db, data_root):
    session = history.create_session(db, "s")
    adapter = FixtureAdapter()
    request = history.TurnRequest(prompt_text="boots", client_request_id=uuid.uuid4())
    first = history.submit_turn(db, session.id, request, adapter, data_root)
    second = history.submit_turn(db, session.id, request, adapter, data_root)
    assert first.id == second.id
    assert len(adapter.calls) == 1
    assert len(db.scalars(select(Turn)).all()) == 1


def test_retrieval_failure_saves_failed_run_without_results(db, data_root):
    session = history.create_session(db, "s")
    adapter = FixtureAdapter(fail_with=RetrievalError("VisualMatch API returned 503: down"))
    turn = history.submit_turn(db, session.id, history.TurnRequest(prompt_text="x"), adapter, data_root)

    db.expire_all()
    run = db.scalars(select(SearchRun).where(SearchRun.turn_id == turn.id)).one()
    assert run.status == "failed"
    assert run.error_message == "VisualMatch API returned 503: down"
    assert run.finished_at is not None
    assert db.scalars(select(SearchResult)).all() == []


def test_missing_reference_file_fails_the_run(db, data_root, asset):
    session = history.create_session(db, "s")
    (data_root / asset.storage_key).unlink()
    turn = history.submit_turn(
        db, session.id, history.TurnRequest(reference_asset_id=asset.id), FixtureAdapter(), data_root
    )
    db.expire_all()
    run = db.get(Turn, turn.id).runs[0]
    assert run.status == "failed" and "missing" in run.error_message


def test_retry_creates_a_new_run_and_keeps_earlier_results(db, data_root):
    session = history.create_session(db, "s")
    turn = history.submit_turn(
        db, session.id, history.TurnRequest(prompt_text="x"), FixtureAdapter(RetrievalError("down")), data_root
    )
    history.retry_turn(db, turn.id, FixtureAdapter(), data_root)
    history.retry_turn(db, turn.id, FixtureAdapter(), data_root)

    db.expire_all()
    runs = db.get(Turn, turn.id).runs
    assert [(r.attempt, r.status, len(r.results)) for r in runs] == [
        (1, "failed", 0), (2, "completed", 3), (3, "completed", 3),
    ]


def test_reconcile_marks_unfinished_runs_interrupted(db):
    session = Session(title="s")
    turn = Turn(session=session, ordinal=1, prompt_text="x")
    pending = SearchRun(turn=turn, attempt=1, status="pending", search_mode="text", result_limit=10, configuration={})
    running = SearchRun(turn=turn, attempt=2, status="running", search_mode="text", result_limit=10, configuration={})
    done = SearchRun(turn=turn, attempt=3, status="completed", search_mode="text", result_limit=10, configuration={})
    db.add_all([session, turn, pending, running, done])
    db.commit()

    assert history.reconcile_interrupted_runs(db) == 2
    db.expire_all()
    assert [r.status for r in db.get(Turn, turn.id).runs] == ["interrupted", "interrupted", "completed"]


# --- VisualMatch HTTP adapter (no server needed) ------------------------------


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code, self._payload, self.text = status_code, payload, str(payload)

    def json(self):
        return self._payload


def test_http_adapter_maps_results(monkeypatch):
    sent = {}

    def fake_post(url, data, files, timeout):
        sent.update(url=url, data=data, files=files)
        return FakeResponse(200, {"results": [
            {"index": 7, "item_id": "MEN_X", "category1": "men", "category2": "denim", "color": "Black", "score": 0.81},
        ]})

    monkeypatch.setattr(requests, "post", fake_post)
    adapter = VisualMatchHttpAdapter("http://vm", "siglip_vitb16")
    from scanger.retrieval import QueryImage

    items = adapter.search("composed", "red", QueryImage(b"img", "image/png", "a.png"), 0.3)
    assert sent["url"] == "http://vm/search/composed"
    assert sent["data"] == {"query": "red", "alpha": 0.3}
    assert sent["files"]["file"] == ("a.png", b"img", "image/png")
    assert items[0].source_item_id == "MEN_X"
    assert items[0].image_locator == "deepfashion-inshop:data:7"
    assert items[0].metadata["dataset_index"] == 7
    assert adapter.info.index_version is not None


def test_http_adapter_turns_errors_into_retrieval_errors(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(503, {"detail": "engine down"}))
    with pytest.raises(RetrievalError, match="503: engine down"):
        VisualMatchHttpAdapter("http://vm", None).search("text", "x", None, 0.5)

    def refuse(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "post", refuse)
    with pytest.raises(RetrievalError, match="not reachable"):
        VisualMatchHttpAdapter("http://vm", None).search("text", "x", None, 0.5)


# --- HTTP API -----------------------------------------------------------------


@pytest.fixture
def api_client(client):
    adapter = FixtureAdapter()
    api.app.dependency_overrides[api.get_adapter] = lambda: adapter
    return client


def test_api_session_and_turn_round_trip(api_client):
    session = api_client.post("/sessions", json={"title": "white hat"}).json()
    asset = api_client.post("/assets", files={"file": ("hat.png", png_bytes(), "image/png")}).json()
    again = api_client.post("/assets", files={"file": ("hat-copy.png", png_bytes(), "image/png")}).json()
    assert again["id"] == asset["id"]  # identical bytes reuse the stored asset

    response = api_client.post(
        f"/sessions/{session['id']}/turns",
        json={"prompt_text": "wider brim", "reference_asset_id": asset["id"], "alpha": 0.6},
    )
    assert response.status_code == 201
    turn = response.json()
    assert turn["runs"][0]["status"] == "completed"
    assert [r["rank"] for r in turn["runs"][0]["results"]] == [1, 2, 3]

    retried = api_client.post(f"/turns/{turn['id']}/runs").json()
    assert retried["attempt"] == 2

    detail = api_client.get(f"/sessions/{session['id']}").json()
    assert detail["title"] == "white hat"
    assert detail["turns"][0]["reference_asset"]["id"] == asset["id"]
    assert [r["attempt"] for r in detail["turns"][0]["runs"]] == [1, 2]

    renamed = api_client.patch(f"/sessions/{session['id']}", json={"title": "cream hat"}).json()
    assert renamed["title"] == "cream hat"
    assert api_client.get("/sessions").json()[0]["id"] == session["id"]


def test_api_controlled_errors(api_client):
    assert api_client.get(f"/sessions/{uuid.uuid4()}").status_code == 404
    assert api_client.post(f"/sessions/{uuid.uuid4()}/turns", json={"prompt_text": "x"}).status_code == 404
    assert api_client.post(f"/turns/{uuid.uuid4()}/runs").status_code == 404
    assert api_client.post("/sessions", json={"title": " "}).status_code == 422
    session = api_client.post("/sessions", json={"title": "s"}).json()
    assert api_client.post(f"/sessions/{session['id']}/turns", json={}).status_code == 422
    assert api_client.post(
        f"/sessions/{session['id']}/turns", json={"reference_asset_id": str(uuid.uuid4())}
    ).status_code == 422
    assert api_client.get(f"/results/{uuid.uuid4()}/1/image").status_code == 404
