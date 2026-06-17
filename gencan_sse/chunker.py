"""Chunker module — split text into sentence-sized chunks for TTS."""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Sentence-ending punctuation followed by whitespace or end-of-string.
# Negative lookbehind for common abbreviations to avoid false splits.
_ABBREVIATIONS = r"(?<!\bMr)(?<!\bMrs)(?<!\bDr)(?<!\bSt)(?<!\bJr)(?<!\bSr)(?<!\be\.g)(?<!\bi\.e)(?<!\bvs)(?<!\betc)"
_SENTENCE_SPLIT = re.compile(
    _ABBREVIATIONS + r'([.!?])(?:\s+|$)',
    re.UNICODE,
)


def chunk_sentences(text: str, min_length: int = 5) -> list[str]:
    """Split text into sentence-sized chunks for natural TTS delivery.

    Args:
        text: The input text to split into sentences.
        min_length: Minimum character length for a chunk. Shorter fragments
                    are merged with the next chunk.

    Returns:
        A list of sentence strings. Empty input returns an empty list.
    """
    if not text or not text.strip():
        return []

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
        return [text]

    # Merge short fragments into adjacent sentences
    merged: list[str] = []
    buffer = ""

    for sentence in raw_sentences:
        if buffer:
            sentence = buffer + " " + sentence
            buffer = ""

        if len(sentence) < min_length:
            buffer = sentence
        else:
            merged.append(sentence)

    # Flush remaining buffer
    if buffer:
        if merged:
            merged[-1] = merged[-1] + " " + buffer
        else:
            merged.append(buffer)

    return merged
