"""Reintentos de COMMIT sin repetir inferencia ni sentencias de escritura.

Se mantiene DELETE/FULL: no se introduce WAL en la carpeta OneDrive.
"""
import sqlite3
import time


class RetryingConnection(sqlite3.Connection):
    retry_seconds = 180.0
    retry_delay = 0.25
    on_commit_wait = None

    def commit(self):
        deadline = time.monotonic() + self.retry_seconds
        attempts = 0
        while True:
            try:
                result = super().commit()
                if attempts:
                    self._notify('RESUELTO', attempts)
                return result
            except sqlite3.OperationalError as exc:
                code = getattr(exc, 'sqlite_errorcode', None)
                busy = ((code & 255) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                        if code is not None else 'locked' in str(exc).lower())
                if not busy:
                    raise
                if time.monotonic() >= deadline:
                    self._notify('AGOTADO', attempts)
                    raise
                attempts += 1
                self._notify('ESPERANDO_LECTOR', attempts)
                time.sleep(min(self.retry_delay * attempts, 2.0,
                               max(0, deadline - time.monotonic())))

    def _notify(self, state, attempts):
        if self.on_commit_wait:
            self.on_commit_wait(state, attempts)
