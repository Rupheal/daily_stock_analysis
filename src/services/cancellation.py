from __future__ import annotations

from typing import Callable, Optional

CancelCheck = Optional[Callable[[], None]]


class CancellationRequested(BaseException):
    """Control-flow signal for cooperative cancellation.

    This deliberately does not inherit from Exception. The analysis pipeline
    contains fail-open `except Exception` blocks for optional data/provider
    failures; Stop must pass through those handlers and reach the TaskQueue
    cancellation seam instead of being downgraded to an ordinary analysis
    failure.
    """
