"""Tests for gencan_sse.filters module."""

from gencan_sse.filters import TextFilter, strip_markdown, is_code_block


class TestStripMarkdown:
    """Tests for the strip_markdown() function."""

    def test_heading(self):
        assert strip_markdown("### Introduction") == "Introduction"

    def test_bold(self):
        assert strip_markdown("**bold text**") == "bold text"

    def test_italic(self):
        assert strip_markdown("*italic text*") == "italic text"

    def test_inline_code(self):
        assert strip_markdown("`some code`") == "some code"

    def test_bullet_list(self):
        assert strip_markdown("- list item") == "list item"

    def test_numbered_list(self):
        assert strip_markdown("1. first item") == "first item"

    def test_blockquote(self):
        assert strip_markdown("> quoted text") == "quoted text"

    def test_plain_text_unchanged(self):
        assert strip_markdown("plain text") == "plain text"


class TestIsCodeBlock:
    """Tests for the is_code_block() function."""

    def test_code_fence(self):
        assert is_code_block("```python") is True

    def test_closing_fence(self):
        assert is_code_block("```") is True

    def test_no_fence(self):
        assert is_code_block("regular text") is False

    def test_inline_backticks(self):
        assert is_code_block("`not a code block`") is False


class TestTextFilter:
    """Tests for the TextFilter class."""

    def test_none_input(self):
        f = TextFilter()
        assert f.filter(None) is None

    def test_empty_input(self):
        f = TextFilter()
        assert f.filter("") is None

    def test_whitespace_only(self):
        f = TextFilter()
        assert f.filter("   ") is None

    def test_horizontal_rule(self):
        f = TextFilter()
        assert f.filter("---") is None
        assert f.filter("***") is None
        assert f.filter("___") is None

    def test_code_fence_tracking(self):
        f = TextFilter()
        assert f.filter("```python") is None  # opens code block
        assert f.filter("print('hello')") is None  # inside code block
        assert f.filter("```") is None  # closes code block
        assert f.filter("regular text") == "regular text"  # outside again

    def test_inline_code_skipped(self):
        f = TextFilter()
        assert f.filter("`variable_name`") is None

    def test_url_replacement(self):
        f = TextFilter()
        result = f.filter("Visit https://example.com for details")
        assert "https://" not in result
        assert "a URL" in result

    def test_file_path_replacement(self):
        f = TextFilter()
        result = f.filter("Open /usr/local/bin/python")
        assert "/usr/local" not in result
        assert "file path" in result

    def test_deduplication(self):
        f = TextFilter()
        result1 = f.filter("Hello world")
        result2 = f.filter("Hello world")
        assert result1 == "Hello world"
        assert result2 is None  # deduplicated

    def test_markdown_stripped(self):
        f = TextFilter()
        result = f.filter("### Important Note")
        assert result == "Important Note"

    def test_reset(self):
        f = TextFilter()
        f.filter("```")  # open code block
        f.reset()
        result = f.filter("should not be skipped")
        assert result == "should not be skipped"
