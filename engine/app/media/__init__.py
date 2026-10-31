"""Media operations: probing, downloading and transcoding. All functions here are blocking."""

import threading


class Cancelled(Exception):
    """Raised inside a media operation when its job was cancelled."""


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise Cancelled()


class MediaError(Exception):
    """A media operation failed in a way worth showing to the user."""
