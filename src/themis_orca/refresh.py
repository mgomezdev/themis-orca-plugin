"""Single background refresh with polling and cancellation, independent of Orca UI."""

from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Thread

from .client import Connection, ThemisClient, ThemisError
from .references import References, load_references
from .settings import Settings


@dataclass(frozen=True)
class RefreshResult:
    connection: Connection | None = None
    references: References | None = None
    error: str | None = None


class BackgroundRefresh:
    """Call start/poll/cancel on the owner thread; the worker never calls the host.

    A refresh already in flight must finish before a new one starts. Cancellation
    discards its result and stops further reference requests; the current request
    can finish within the client's socket timeout. Never join on Orca's UI thread.
    """

    def __init__(self):
        self._worker = None
        self._cancelled = Event()
        self._results = Queue()

    @property
    def busy(self):
        return self._worker is not None and self._worker.is_alive()

    def start(self, settings: Settings) -> bool:
        if self.busy:
            return False
        self._discard_results()
        self._cancelled = Event()
        cancelled = self._cancelled

        def refresh():
            try:
                client = ThemisClient(settings)
                connection = client.test_connection()
                if cancelled.is_set():
                    return
                references = load_references(client, connection, cancelled=cancelled.is_set)
                result = RefreshResult(connection, references)
            except ThemisError as exc:
                result = RefreshResult(error=str(exc))
            except Exception:
                # Do not send arbitrary exception text or credentials to the host.
                result = RefreshResult(error="Could not refresh Themis. Check plugin compatibility and retry.")
            if not cancelled.is_set():
                self._results.put(result)

        self._worker = Thread(target=refresh, name="themis-reference-refresh", daemon=True)
        try:
            self._worker.start()
        except Exception:
            self._worker = None
            self._results.put(RefreshResult(error="Allow thread access for the Themis plugin in Orca, then retry."))
        return True

    def _discard_results(self):
        while True:
            try:
                self._results.get_nowait()
            except Empty:
                return

    def poll(self) -> RefreshResult | None:
        if self._cancelled.is_set():
            self._discard_results()
            return None
        try:
            return self._results.get_nowait()
        except Empty:
            return None

    def cancel(self):
        self._cancelled.set()
        self._discard_results()
