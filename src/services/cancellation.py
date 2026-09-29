from __future__ import annotations

from typing import Callable, Optional

CancelCheck = Optional[Callable[[], None]]


class CancellationRequested(RuntimeError):
    """Raised when a caller has requested cooperative task cancellation."""
