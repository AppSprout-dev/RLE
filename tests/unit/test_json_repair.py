"""Tests for rle.agents.json_repair module."""

from __future__ import annotations

import json

import pytest

from rle.agents.json_repair import repair_json, try_parse_json


class TestRepairJson:
    """Tests for the repair_json function."""

    def test_valid_json_passes_through(self):
        raw = '{"key": "value", "num": 42}'
        result = repair_json(raw)
        assert json.loads(result) == {"key": "value", "num": 42}

    def test_trailing_comma_in_object(self):
        raw = '{"a": 1,}'
        result = repair_json(raw)
        assert json.loads(result) == {"a": 1}

    def test_trailing_comma_in_array(self):
        raw = '[1, 2,]'
        result = repair_json(raw)
        assert json.loads(result) == [1, 2]

    def test_extra_text_after_json(self):
        raw = '{"a": 1} some garbage'
        result = repair_json(raw)
        assert json.loads(result) == {"a": 1}

    def test_preamble_before_json(self):
        raw = 'Here is your JSON: {"a": 1}'
        result = repair_json(raw)
        assert json.loads(result) == {"a": 1}

    def test_markdown_code_fences(self):
        raw = '```json\n{"a": 1}\n```'
        result = repair_json(raw)
        assert json.loads(result) == {"a": 1}

    def test_nested_braces_with_trailing_commas(self):
        raw = '{"a": {"b": 1,},}'
        result = repair_json(raw)
        assert json.loads(result) == {"a": {"b": 1}}

    def test_braces_inside_strings(self):
        raw = '{"reason": "build {wall}",}'
        result = repair_json(raw)
        parsed = json.loads(result)
        assert parsed == {"reason": "build {wall}"}

    def test_unterminated_string_not_corrupted(self):
        raw = '{"key": "unterminated'
        result = repair_json(raw)
        # Should not crash; returns best-effort (original or extracted)
        assert isinstance(result, str)

    def test_valid_json_is_identical(self):
        raw = '{"x": [1, 2, 3], "y": {"nested": true}}'
        result = repair_json(raw)
        assert result == raw


class TestTryParseJson:
    """Tests for the try_parse_json helper."""

    def test_returns_none_for_invalid_input(self):
        assert try_parse_json("not json at all") is None

    def test_returns_dict_for_valid_input(self):
        result = try_parse_json('{"a": 1}')
        assert result == {"a": 1}

    def test_returns_none_for_array(self):
        # try_parse_json only returns dicts
        assert try_parse_json("[1, 2, 3]") is None

    def test_repairs_before_parsing(self):
        raw = '```json\n{"key": "val",}\n```'
        result = try_parse_json(raw)
        assert result == {"key": "val"}

    def test_returns_none_for_empty_string(self):
        assert try_parse_json("") is None
