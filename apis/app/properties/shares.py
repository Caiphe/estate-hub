"""Ownership share arithmetic. Shares are ``Decimal`` percentages, never floats.

Links carry real-world dates, so a previous owner's 100% and the current owner's 100%
are both valid. The rule is therefore per date: on any single day, the known shares of
the links in force that day total at most 100. Unknown (``None``) shares are not counted
and never treated as zero or as "the rest".
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

MAX_TOTAL = Decimal(100)


@dataclass(frozen=True, slots=True)
class ShareSpan:
    share: Decimal | None
    start: date | None
    end: date | None

    def covers(self, day: date | None) -> bool:
        """``day=None`` stands for "before any known date"."""
        if day is None:
            return self.start is None
        return (self.start is None or self.start <= day) and (self.end is None or day <= self.end)


def peak_known_share(spans: Iterable[ShareSpan]) -> Decimal:
    """The highest total of known shares in force on any one day.

    Coverage only rises where a link starts, so checking each start date (and the
    open-ended past) finds the maximum.
    """
    known = [(span.share, span) for span in spans if span.share is not None]
    days: set[date | None] = {None, *(span.start for _, span in known)}
    return max(
        sum((share for share, span in known if span.covers(day)), Decimal(0)) for day in days
    )


@dataclass(frozen=True, slots=True)
class ShareSummary:
    """Shares in force on one day. ``complete`` is true only when every share is known
    and they total exactly 100; otherwise nothing is claimed about the remainder."""

    known_total: Decimal
    unknown_count: int

    @property
    def complete(self) -> bool:
        return self.unknown_count == 0 and self.known_total == MAX_TOTAL


def share_summary(spans: Iterable[ShareSpan], day: date) -> ShareSummary:
    current = [span for span in spans if span.covers(day)]
    known = [span.share for span in current if span.share is not None]
    return ShareSummary(sum(known, Decimal(0)), len(current) - len(known))
