"""What the formatter says when it will not rewrite a file."""

from __future__ import annotations


class FormatError(ValueError):
    """Why a source was rejected, left as the caller's file rather than rewritten."""
