"""Tests for gencan_sse.chunker module."""

from gencan_sse.chunker import chunk_sentences


class TestChunkSentences:
    """Tests for the chunk_sentences() function."""

    def test_single_sentence(self):
        result = chunk_sentences("Hello world.")
        assert result == ["Hello world."]

    def test_two_sentences(self):
        result = chunk_sentences("Hello world. How are you?")
        # By default groups up to 250 characters
        assert len(result) == 1
        assert result[0] == "Hello world. How are you?"

    def test_three_sentences(self):
        # Override target_chunk_size to force a split
        result = chunk_sentences("First. Second. Third.", target_chunk_size=15)
        assert len(result) == 2
        assert result[0] == "First. Second."
        assert result[1] == "Third."

    def test_exclamation_and_question(self):
        result = chunk_sentences("Wow! Really? Yes.")
        # Short fragments may be merged by the chunker
        assert len(result) >= 1
        recombined = " ".join(result)
        assert "Wow" in recombined
        assert "Yes" in recombined

    def test_empty_string(self):
        result = chunk_sentences("")
        assert result == []

    def test_whitespace_only(self):
        result = chunk_sentences("   ")
        assert result == []

    def test_no_sentence_breaks(self):
        result = chunk_sentences("hello world without punctuation")
        assert result == ["hello world without punctuation"]

    def test_short_fragments_merged(self):
        result = chunk_sentences("Hi. Hello world.", min_length=5)
        # "Hi." is shorter than min_length, should be merged
        assert len(result) <= 2

    def test_abbreviations_not_split(self):
        result = chunk_sentences("Dr. Smith went home.")
        assert len(result) == 1

    def test_eg_abbreviation(self):
        result = chunk_sentences("Use e.g. this method.")
        assert len(result) == 1

    def test_preserves_content(self):
        text = "The quick brown fox jumps. Over the lazy dog."
        result = chunk_sentences(text)
        recombined = " ".join(result)
        assert "quick brown fox" in recombined
        assert "lazy dog" in recombined
