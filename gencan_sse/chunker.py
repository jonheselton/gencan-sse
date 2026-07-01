"""Chunker module — split text into sentence-sized chunks for TTS."""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Sentence-ending punctuation followed by whitespace or end-of-string.
# Negative lookbehind for common abbreviations to avoid false splits.
_ABBREVIATIONS = (
    r"(?<!\bMr)(?<!\bMrs)(?<!\bDr)(?<!\bSt)(?<!\bJr)(?<!\bSr)"
    r"(?<!\be\.g)(?<!\bi\.e)(?<!\bvs)(?<!\betc)"
    r"(?<!\bProf)(?<!\bInc)(?<!\bCorp)(?<!\bLtd)(?<!\bPh\.D)(?<!\bU\.S\.A)"
)
_SENTENCE_SPLIT = re.compile(
    _ABBREVIATIONS + r'([.!?])(?:\s+|$)',
    re.UNICODE,
)


def split_by_words(text: str, max_size: int = 400) -> list[str]:
    """Split a long string into chunks of at most max_size characters,
    splitting on word boundaries (whitespace).
    """
    if len(text) <= max_size:
        return [text]

    words = text.split()
    chunks = []
    current_chunk = []
    current_len = 0

    for word in words:
        added_len = len(word) + (1 if current_chunk else 0)
        if current_len + added_len > max_size:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = [word]
                current_len = len(word)
            else:
                chunks.append(word[:max_size])
                remaining = word[max_size:]
                while len(remaining) > max_size:
                    chunks.append(remaining[:max_size])
                    remaining = remaining[max_size:]
                current_chunk = [remaining]
                current_len = len(remaining)
        else:
            current_chunk.append(word)
            current_len += added_len

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def chunk_sentences(text: str, min_length: int = 5, target_chunk_size: int = 250, max_chunk_size: int = 400) -> list[str]:
    """Split text into sentence-sized chunks for natural TTS delivery.

    Args:
        text: The input text to split into sentences.
        min_length: Minimum character length for a chunk. Shorter fragments
                    are merged with the next chunk.
        target_chunk_size: Target size for grouped sentence chunks.
        max_chunk_size: Maximum chunk size limit. Sentences exceeding this
                        will be split by word boundaries.

    Returns:
        A list of sentence strings. Empty input returns an empty list.
    """
    if not text or not text.strip():
        return []

    # Limit input text length to 100,000 characters to prevent DOS
    if len(text) > 100_000:
        logger.warning("Input text too long (%d chars), truncating to 100,000.", len(text))
        text = text[:100_000]

    text = text.strip()

    # Split using sentence-ending punctuation
    parts = _SENTENCE_SPLIT.split(text)

    # Reassemble: parts alternate between text and punctuation captures
    # e.g. ["Hello world", ".", " How are you", "?", ""]
    raw_sentences: list[str] = []
    i = 0
    while i < len(parts):
        chunk = parts[i]
        # If the next part is a captured punctuation mark, append it
        if i + 1 < len(parts) and len(parts[i + 1]) == 1 and parts[i + 1] in ".!?":
            chunk += parts[i + 1]
            i += 2
        else:
            i += 1
        chunk = chunk.strip()
        if chunk:
            raw_sentences.append(chunk)

    if not raw_sentences:
        # No sentence breaks found — return the whole text as one chunk
        raw_sentences = [text]

    # Merge short fragments into adjacent sentences and group up to target_chunk_size
    merged: list[str] = []
    buffer = ""

    for sentence in raw_sentences:
        if buffer:
            if len(buffer) + 1 + len(sentence) <= target_chunk_size or len(buffer) < min_length:
                buffer = buffer + " " + sentence
            else:
                merged.append(buffer)
                buffer = sentence
        else:
            buffer = sentence

    # Flush remaining buffer
    if buffer:
        merged.append(buffer)

    # Final pass: check if any chunk exceeds max_chunk_size, and if so, split it by words
    final_chunks: list[str] = []
    for chunk in merged:
        if len(chunk) > max_chunk_size:
            final_chunks.extend(split_by_words(chunk, max_size=max_chunk_size))
        else:
            final_chunks.append(chunk)

    return final_chunks
