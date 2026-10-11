from agent.schema_bridge import _flatten, get_input_schema


class FakeTool:
    name = "t"
    description = "d"
    def __init__(self, schema): self.input_schema = schema


def test_reads_snake_case_attribute():
    # mcp 2.x exposes input_schema; reading inputSchema yields an empty schema.
    s = get_input_schema(FakeTool({"type": "object", "properties": {"a": {"type": "number"}}}))
    assert s["properties"]["a"]["type"] == "number"


def test_optional_param_anyof_is_flattened():
    out = _flatten({"anyOf": [{"type": "number"}, {"type": "null"}], "default": None})
    assert out["type"] == "number"
    assert "anyOf" not in out


def test_titles_are_stripped():
    out = _flatten({"type": "object", "title": "X",
                    "properties": {"a": {"type": "number", "title": "A"}}})
    assert "title" not in out
    assert "title" not in out["properties"]["a"]


def test_nested_structures_survive():
    out = _flatten({"type": "object", "properties": {
        "items": {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}})
    assert out["properties"]["items"]["items"]["type"] == "string"


def test_missing_schema_degrades_safely():
    class Bare: name = "b"; description = ""
    assert get_input_schema(Bare()) == {"type": "object", "properties": {}}


def test_keep_alive_is_coerced_to_a_number():
    # Ollama rejects the STRING "-1" with: time: missing unit in duration "-1"
    from agent.ollama import _keep_alive
    assert _keep_alive("-1") == -1
    assert _keep_alive("300") == 300
    assert _keep_alive("30m") == "30m"      # duration strings pass through
    assert _keep_alive("") == -1


def test_repl_history_keeps_question_and_answer_only():
    from agent.main import _compact
    msgs = [{"role": "system"}, {"role": "user", "content": "q"},
            {"role": "assistant", "tool_calls": [1]}, {"role": "tool", "content": "{...}"},
            {"role": "assistant", "content": "a"}]
    _compact(msgs, 1)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
    assert msgs[-1]["content"] == "a"
