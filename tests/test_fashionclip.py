"""FashionCLIP wiring tests. No model, index or GPU needed: the engine is faked."""

import types

import numpy as np
import pytest
from fastapi.testclient import TestClient

from scanger import fashionclip
from scanger.config import REPO_ROOT
from scanger.retrieval import INDEX_VERSIONS


def test_index_version_is_recorded_for_the_model_name():
    assert INDEX_VERSIONS[fashionclip.MODEL_NAME] == fashionclip.INDEX_VERSION
    assert fashionclip.MODEL_REVISION in fashionclip.INDEX_VERSION


def test_features_accepts_tensor_or_model_output():
    class Tensorlike:
        def norm(self): ...

    tensor = Tensorlike()
    assert fashionclip.FashionClipEncoder._features(tensor) is tensor
    output = types.SimpleNamespace(pooler_output="projected")  # transformers 5 ModelOutput
    assert fashionclip.FashionClipEncoder._features(output) == "projected"


def test_engine_requires_a_built_index(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_fashionclip_index"):
        fashionclip.FashionClipEngine(index_path=tmp_path / "missing.index")


@pytest.mark.skipif(
    not (REPO_ROOT / "upstream" / "visualmatch" / "api" / "app.py").exists(),
    reason="upstream VisualMatch checkout not present",
)
def test_server_wrapper_swaps_in_fashionclip_only_when_selected(monkeypatch):
    from scanger import visualmatch_server as server

    class FakeEngine:
        def text_search(self, query, top_k=10):
            return [{"index": 0, "item_id": "X", "score": 0.5, "query": query}]

    monkeypatch.setattr(server.upstream, "_engine", None)
    monkeypatch.setattr(fashionclip, "FashionClipEngine", FakeEngine)
    monkeypatch.setenv("VISUALMATCH_MODEL", "fashionclip")
    client = TestClient(server.app)

    assert client.get("/health").json()["engine_loaded"] is False
    response = client.post("/search/text", data={"query": "red dress"})
    assert response.status_code == 200
    assert response.json()["results"][0]["query"] == "red dress"
    assert client.get("/health").json()["engine_loaded"] is True


@pytest.mark.skipif(
    not (REPO_ROOT / "upstream" / "visualmatch" / "api" / "app.py").exists(),
    reason="upstream VisualMatch checkout not present",
)
def test_server_wrapper_reports_fashionclip_load_failure_as_503(monkeypatch):
    from scanger import visualmatch_server as server

    def broken(*args, **kwargs):
        raise FileNotFoundError("fashionclip.index does not exist")

    monkeypatch.setattr(server.upstream, "_engine", None)
    monkeypatch.setattr(fashionclip, "FashionClipEngine", broken)
    monkeypatch.setenv("VISUALMATCH_MODEL", "fashionclip")
    response = TestClient(server.app).post("/search/text", data={"query": "x"})
    assert response.status_code == 503
    assert "fashionclip.index does not exist" in response.json()["detail"]


def test_composed_vector_is_unit_norm_and_alpha_weighted():
    engine = object.__new__(fashionclip.FashionClipEngine)
    seen = {}
    engine.encoder = types.SimpleNamespace(
        encode_images=lambda images: np.array([[1.0, 0.0]], dtype="float32"),
        encode_texts=lambda texts: np.array([[0.0, 1.0]], dtype="float32"),
    )

    def capture(vec, top_k):
        seen["vec"] = vec
        return []

    engine._search_index = capture
    engine.composed_search(object(), "text", alpha=0.75)
    vec = seen["vec"]
    assert np.isclose(np.linalg.norm(vec), 1.0)
    assert vec[0] > vec[1]
