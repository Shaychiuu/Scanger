"""Offline checks for the M03.1 interpretation probe. No SDK calls are made."""

import json

import pytest
from cursor_sdk import ModelParameterDefinition, ModelParameterDefinitionValue, SDKModel

from scanger.config import interpret_model_params
from scanger.interpret import build_prompt, model_selection, validate_interpretation

VALID = {
    "category": "midi wrap dress",
    "observed": ["emerald green", "satin look", "v-neck"],
    "requested_changes": ["long sleeves"],
    "must_have": [],
    "exclude": ["belt"],
    "uncertain": ["material composition"],
    "queries": {
        "precise": "emerald satin midi wrap dress long sleeves",
        "synonym": "green silky wrap midi dress with long sleeves",
        "broad": "green long sleeve wrap dress",
    },
}


def test_valid_minified_json_passes():
    data, problems = validate_interpretation(json.dumps(VALID, separators=(",", ":")))
    assert problems == []
    assert data == VALID


def test_markdown_fence_is_rejected():
    data, problems = validate_interpretation("```json\n" + json.dumps(VALID) + "\n```")
    assert data is None
    assert "not bare JSON" in problems[0]


def test_missing_extra_and_mistyped_keys_are_reported():
    reply = dict(VALID, colour="green", observed="green", category=" ")
    del reply["exclude"]
    data, problems = validate_interpretation(json.dumps(reply))
    assert data is None
    assert any("Missing keys: ['exclude']" in p for p in problems)
    assert any("Unexpected keys: ['colour']" in p for p in problems)
    assert any(p.startswith("observed should be list") for p in problems)
    assert any(p == "category is empty" for p in problems)


def test_queries_need_all_three_non_empty():
    reply = dict(VALID, queries={"precise": "green wrap dress", "broad": ""})
    data, problems = validate_interpretation(json.dumps(reply))
    assert data is None
    assert any("should have exactly ['precise', 'synonym', 'broad']" in p for p in problems)
    assert any(p == "queries.broad should be a non-empty string" for p in problems)


def test_old_single_query_schema_is_rejected():
    reply = {k: v for k, v in VALID.items() if k != "queries"}
    reply["search_query"] = "green wrap dress"
    data, problems = validate_interpretation(json.dumps(reply))
    assert data is None
    assert any("Missing keys: ['queries']" in p for p in problems)


def test_user_text_is_delimited_in_prompt():
    assert "User text: <<<no belt>>>" in build_prompt("  no belt \n")


CATALOG = [
    SDKModel(
        id="example-model",
        display_name="Example",
        description="",
        parameters=[
            ModelParameterDefinition(
                id="thinking",
                display_name="Thinking",
                values=[
                    ModelParameterDefinitionValue(value="false", display_name=""),
                    ModelParameterDefinitionValue(value="true", display_name=""),
                ],
            )
        ],
        variants=[],
    )
]


def test_model_selection_accepts_listed_param():
    selection = model_selection(CATALOG, "example-model", {"thinking": "false"})
    assert selection.id == "example-model"
    assert [(p.id, p.value) for p in selection.params] == [("thinking", "false")]


@pytest.mark.parametrize(
    "model_id, params, message",
    [
        ("other-model", {}, "not in this account's catalog"),
        ("example-model", {"effort": "low"}, "has no parameter 'effort'"),
        ("example-model", {"thinking": "off"}, "accepts ['false', 'true']"),
    ],
)
def test_model_selection_rejects_unlisted(model_id, params, message):
    with pytest.raises(RuntimeError, match=message.replace("[", r"\[").replace("]", r"\]")):
        model_selection(CATALOG, model_id, params)


def test_interpret_model_params_parsing(monkeypatch):
    monkeypatch.setenv("INTERPRET_MODEL_PARAMS", " thinking=false , effort=low,")
    assert interpret_model_params() == {"thinking": "false", "effort": "low"}
    monkeypatch.setenv("INTERPRET_MODEL_PARAMS", "thinking")
    with pytest.raises(RuntimeError):
        interpret_model_params()
