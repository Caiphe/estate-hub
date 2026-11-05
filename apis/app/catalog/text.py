"""Text normalization shared by catalog records. Database checks reject unnormalized values."""

import re

_WHITESPACE = re.compile(r"\s+")


def normalize_label(value: str) -> str:
    """Trim and collapse whitespace. The database rejects anything this would change."""
    return _WHITESPACE.sub(" ", value).strip()


def normalize_optional_text(value: str | None) -> str | None:
    """Trim free text; blank becomes ``None`` so "no value" has one representation."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_optional_label(value: str | None) -> str | None:
    normalized = normalize_optional_text(value)
    return normalize_label(normalized) if normalized else None


def escape_like(term: str) -> str:
    """Escape LIKE wildcards so a search is literal (use with ``escape="\\"``)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
