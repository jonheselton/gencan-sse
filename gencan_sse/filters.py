"""Filters module — content filtering for TTS pipeline."""

import re
import logging
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

# Patterns
_CODE_FENCE = re.compile(r'```')
_INLINE_CODE = re.compile(r'^`[^`]+`$')
_URL_PATTERN = re.compile(r'https?://\S+')
_FILE_PATH_PATTERN = re.compile(r'(?:^|\s)([~/][\w./\-]+|[A-Z]:\\[\w\\\.\-]+)')

# Markdown stripping patterns
_MD_HEADING = re.compile(r'^#{1,6}\s+')          # ### Heading → stripped prefix
_MD_BOLD_ITALIC = re.compile(r'\*{1,3}([^*]+)\*{1,3}')  # **bold** / *italic* → text
_MD_BOLD_UNDER = re.compile(r'_{1,2}([^_]+)_{1,2}')     # __bold__ / _italic_ → text
_MD_INLINE_CODE_SPAN = re.compile(r'`([^`]+)`')          # `code` → text only
_MD_BULLET = re.compile(r'^[\*\-\+]\s+')         # bullet list prefix → stripped
_MD_NUMBERED = re.compile(r'^\d+\.\s+')           # numbered list prefix → stripped
_MD_HR = re.compile(r'^[-\*_]{3,}\s*$')           # horizontal rule (---, ***)
_MD_BLOCKQUOTE = re.compile(r'^>\s*')             # > blockquote prefix → stripped


def strip_markdown(text: str) -> str:
    """Strip common markdown formatting tokens from text for clean TTS output.

    Args:
        text: Raw text potentially containing markdown.

    Returns:
        Plain text with markdown formatting removed.
    """
    # Strip heading prefixes (### Intro → Intro)
    text = _MD_HEADING.sub('', text)
    # Strip blockquote prefix
    text = _MD_BLOCKQUOTE.sub('', text)
    # Strip bullet/numbered list prefixes
    text = _MD_BULLET.sub('', text)
    text = _MD_NUMBERED.sub('', text)
    # Unwrap bold/italic markers, keeping inner text
    text = _MD_BOLD_ITALIC.sub(r'\1', text)
    text = _MD_BOLD_UNDER.sub(r'\1', text)
    # Unwrap inline code spans, keeping inner text
    text = _MD_INLINE_CODE_SPAN.sub(r'\1', text)
    return text.strip()


def is_code_block(text: str) -> bool:
    """Returns True if text contains a code fence (triple backticks).

    Args:
        text: The text to check.

    Returns:
        True if the text contains or is part of a code fence block.
    """
    return bool(_CODE_FENCE.search(text))


class TextFilter:
    """Stateful text filter that applies content filtering rules for TTS.

    Maintains a small LRU cache of recent outputs for deduplication.
    """

    def __init__(self, dedupe_size: int = 5):
        """Initialize the filter.

        Args:
            dedupe_size: Number of recent outputs to track for deduplication.
        """
        self._recent: deque[str] = deque(maxlen=dedupe_size)
        self._in_code_block = False
        self._consecutive_skips = 0

    def filter(self, text: str) -> Optional[str]:
        """Apply all filtering rules to the input text.

        Rules are applied in order:
        1. None or whitespace-only → None
        2. Horizontal rules (---) → None
        3. Code fence tracking → None (toggles code block state)
        4. Inside code block → None
        5. Entirely inline code → None
        6. Strip markdown formatting tokens
        7. Replace file paths → "a file path"
        8. Replace URLs → "a URL"
        9. Deduplicate against recent outputs

        Args:
            text: The raw text to filter.

        Returns:
            Filtered text ready for TTS, or None if the text should be skipped.
        """
        result = self._filter_impl(text)
        if result is None:
            self._consecutive_skips += 1
            if self._consecutive_skips >= 30:
                logger.info("Auto-resetting filter state after 30 consecutive empty/skipped outputs.")
                self.reset()
        else:
            self._consecutive_skips = 0
        return result

    def _filter_impl(self, text: Optional[str]) -> Optional[str]:
        # Rule 1: Skip empty/whitespace
        if text is None or not text.strip():
            return None

        text = text.strip()

        # Rule 2: Skip horizontal rules (---, ***, ___)
        if _MD_HR.match(text):
            logger.debug("Skipping horizontal rule: %s", text)
            return None

        lines = text.splitlines()
        kept_lines = []
        for line in lines:
            if line.strip().startswith('```'):
                self._in_code_block = not self._in_code_block
                self._consecutive_skips = -1
                logger.debug("Code fence detected, in_code_block=%s", self._in_code_block)
                continue
            if self._in_code_block:
                continue
            kept_lines.append(line)

        if not kept_lines:
            return None
        text = "\n".join(kept_lines)

        # Rule 5: Entirely inline code
        if _INLINE_CODE.match(text):
            logger.debug("Skipping inline code: %s", text[:50])
            return None

        # Rule 6: Strip markdown formatting for clean speech
        text = strip_markdown(text)
        if not text.strip():
            return None

        # Rule 7: Replace file paths
        text = _FILE_PATH_PATTERN.sub(" a file path", text)

        # Rule 8: Replace URLs
        text = _URL_PATTERN.sub("a URL", text)

        # Clean up extra whitespace from substitutions
        text = " ".join(text.split())

        if not text.strip():
            return None

        # Rule 9: Deduplicate
        if text in self._recent:
            logger.debug("Deduplicating: %s", text[:50])
            return None

        self._recent.append(text)
        return text

    def reset(self) -> None:
        """Reset the filter state (code block tracking and dedupe cache)."""
        self._in_code_block = False
        self._recent.clear()
        self._consecutive_skips = 0
