"""
Offline unit tests for agents/json_utils.py — the shared Claude-JSON extraction
helpers used by email_triage, email_digest, and weekly_report.

These are pure string functions with no external dependencies, so the whole file
is trivially CI-safe. The load-bearing case is test_two_json_blocks_returns_first:
it pins the self-correction failure mode (two JSON blocks) that the old
rindex-based slice turned into an "Extra data" parse error.
"""

import pytest

from agents.json_utils import strip_code_fences, clean_json_response


# ── strip_code_fences ────────────────────────────────────────────────────────

def test_strip_code_fences_removes_json_wrapper():
    wrapped = '```json\n{"a": 1}\n```'
    assert strip_code_fences(wrapped) == '{"a": 1}'


def test_strip_code_fences_removes_bare_wrapper():
    wrapped = '```\n{"a": 1}\n```'
    assert strip_code_fences(wrapped) == '{"a": 1}'


def test_strip_code_fences_leaves_unwrapped_unchanged():
    plain = '{"a": 1}'
    assert strip_code_fences(plain) == '{"a": 1}'


def test_strip_code_fences_empty_string():
    assert strip_code_fences("") == ""


# ── clean_json_response ──────────────────────────────────────────────────────

def test_single_object_returned_exactly():
    text = '{"a": 1, "b": 2}'
    assert clean_json_response(text) == '{"a": 1, "b": 2}'


def test_two_json_blocks_returns_first():
    # The exact self-correction failure mode being fixed: two complete JSON
    # objects separated by prose. The old rindex slice spanned both blocks
    # (producing "Extra data"); brace-counting must return only the first.
    text = '{"a": 1}\nLet me redo this.\n{"a": 2}'
    assert clean_json_response(text) == '{"a": 1}'


def test_nested_objects_returned_whole():
    text = '{"urgent": [{"email_id": "abc", "confidence": 0.9}]}'
    assert clean_json_response(text) == text


def test_braces_inside_strings_not_counted():
    # A `}` inside a JSON string value must not be treated as a closing brace,
    # or the object would be truncated mid-string.
    text = '{"text": "use { and } in sentences"}'
    assert clean_json_response(text) == text


def test_truncated_json_raises():
    text = '{"urgent": [{"email_id": "abc"'
    with pytest.raises(ValueError, match="truncated"):
        clean_json_response(text)


def test_no_json_raises():
    with pytest.raises(ValueError, match="No JSON object found"):
        clean_json_response("Let me think about this...")


# ── Extra edge cases that exercise the string-state machine ──────────────────

def test_leading_prose_before_object_is_trimmed():
    text = 'Here is your JSON:\n{"a": 1}'
    assert clean_json_response(text) == '{"a": 1}'


def test_escaped_quote_inside_string():
    # A backslash-escaped quote must not flip the in_string state, so the brace
    # after it stays "inside" the string and is not counted.
    text = '{"text": "she said \\"hi\\" }"}'
    assert clean_json_response(text) == text
