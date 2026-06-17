"""Tests for gencan_sse.classifier module."""

import json

from gencan_sse.classifier import classify
from gencan_sse.types import EventType, Priority


class TestClassify:
    """Tests for the classify() function."""

    def test_message_event(self):
        line = json.dumps({"type": "message", "content": "Hello, world!"})
        event = classify(line)
        assert event.event_type == EventType.MESSAGE
        assert event.text == "Hello, world!"
        assert event.priority == Priority.RESPONSE

    def test_tool_use_event(self):
        line = json.dumps({"type": "tool_use", "tool": "read_file"})
        event = classify(line)
        assert event.event_type == EventType.TOOL_USE
        assert event.text == "Running read_file"
        assert event.priority == Priority.TOOL

    def test_tool_result_event(self):
        line = json.dumps({"type": "tool_result", "output": "some output"})
        event = classify(line)
        assert event.event_type == EventType.TOOL_RESULT
        assert event.text == "some output"

    def test_error_event(self):
        line = json.dumps({"type": "error", "message": "Something broke"})
        event = classify(line)
        assert event.event_type == EventType.ERROR
        assert event.text == "Something broke"
        assert event.priority == Priority.ERROR

    def test_thinking_event(self):
        line = json.dumps({"type": "thinking", "content": "Hmm..."})
        event = classify(line)
        assert event.event_type == EventType.THINKING
        assert event.text == "Hmm..."
        assert event.priority == Priority.THINKING

    def test_init_event_skipped(self):
        line = json.dumps({"type": "init", "session": "abc"})
        event = classify(line)
        assert event.event_type == EventType.SKIP

    def test_result_event_skipped(self):
        line = json.dumps({"type": "result", "summary": "done"})
        event = classify(line)
        assert event.event_type == EventType.SKIP

    def test_unknown_event_skipped(self):
        line = json.dumps({"type": "unknown_type"})
        event = classify(line)
        assert event.event_type == EventType.SKIP

    def test_empty_string(self):
        event = classify("")
        assert event.event_type == EventType.SKIP

    def test_whitespace_only(self):
        event = classify("   ")
        assert event.event_type == EventType.SKIP

    def test_invalid_json(self):
        event = classify("not json at all{{{")
        assert event.event_type == EventType.SKIP

    def test_json_array(self):
        event = classify("[1, 2, 3]")
        assert event.event_type == EventType.SKIP

    def test_missing_content(self):
        line = json.dumps({"type": "message"})
        event = classify(line)
        assert event.event_type == EventType.MESSAGE
        assert event.text == ""

    def test_preserves_raw(self):
        data = {"type": "message", "content": "hi", "extra": "data"}
        line = json.dumps(data)
        event = classify(line)
        assert event.raw == data

    def test_sample_events(self, sample_events):
        """Classify all sample events without error."""
        for event_data in sample_events:
            line = json.dumps(event_data)
            result = classify(line)
            assert result is not None
            assert isinstance(result.event_type, EventType)
