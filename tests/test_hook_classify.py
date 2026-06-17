from mlx_mcp_server.hook.classify import classify, Classification
from mlx_mcp_server.hook.omlx import ChatResult


def _chat_returning(text):
    def chat(system, user):
        return ChatResult(text, 10, 4)
    return chat


def test_classify_parses_well_formed_json():
    c = classify("summarize this", _chat_returning(
        '{"task_type":"summarize","offloadable":true,"confidence":0.9}'))
    assert c == Classification("summarize", True, 0.9)


def test_classify_coerces_unknown_task_type_to_other():
    c = classify("x", _chat_returning('{"task_type":"banana","offloadable":true,"confidence":0.8}'))
    assert c.task_type == "other"


def test_classify_falls_back_on_unparseable_response():
    c = classify("x", _chat_returning("I cannot answer that as JSON"))
    assert c == Classification("other", False, 0.0)


def test_classify_extracts_json_embedded_in_prose():
    c = classify("x", _chat_returning(
        'Sure:\n{"task_type":"extract","offloadable":true,"confidence":0.7}\nhope that helps'))
    assert c.task_type == "extract" and c.offloadable is True
