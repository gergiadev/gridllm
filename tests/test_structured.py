import pytest

from gridllm.messages import Review, Verdict
from gridllm.structured import convert, extract


def test_extract_finds_an_object_embedded_in_prose():
    assert extract('some words {"a": 1} trailing') == {"a": 1}


def test_extract_rejects_a_response_without_an_object():
    with pytest.raises(ValueError):
        extract("no json here at all")


def test_extract_rejects_a_truncated_object():
    with pytest.raises(ValueError):
        extract('{"broken": ')


def test_convert_skips_an_echoed_schema_and_finds_the_answer():
    text = (
        "The schema I must follow:\n"
        '{"properties": {"approved": {"type": "boolean"}}, "title": "Review", "type": "object"}\n\n'
        "My answer:\n"
        '{"approved": true, "note": "applied as instructed"}'
    )
    result = convert(text, Review)
    assert result.approved is True
    assert result.note == "applied as instructed"


def test_convert_reads_through_a_code_fence():
    text = '```json\n{"approved": false, "note": "missing the second edit"}\n```'
    assert convert(text, Review).approved is False


def test_convert_accepts_a_bare_object():
    verdict = convert('{"verdict": "do it", "rationale": "because", "allowed_files": ["a.c"]}', Verdict)
    assert verdict.allowed_files == ["a.c"]


def test_convert_reports_the_schema_when_nothing_conforms():
    with pytest.raises(ValueError, match="does not conform to Review"):
        convert('{"approved": "maybe"}', Review)


def test_convert_reports_a_missing_object_distinctly():
    with pytest.raises(ValueError, match="no json object found"):
        convert("I refuse to answer in json", Review)
