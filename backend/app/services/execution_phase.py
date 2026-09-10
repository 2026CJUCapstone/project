"""Decode an opt-in sandbox phase handshake, not user diagnostic keywords.

The launcher emits a nonce-bound compile frame before invoking any compiler,
and a run frame before executing user code. After run starts, all bytes are
user output, even if they look like control frames. Old images remain readable
without a handshake. Buffer at most one frame across stream boundaries.
"""
import re


class ExecutionPhaseDecoder:
    def __init__(self, token: str, *, terminal: bool = False):
        if not re.fullmatch(r'[0-9a-f]{32}', token):
            raise ValueError('Invalid execution phase token')
        self.phase = None
        newline = '\r\n' if terminal else '\n'
        self._compile = f'\x1ewebcompiler:{token}:compile\x1f{newline}'.encode()
        self._run = f'\x1ewebcompiler:{token}:run\x1f{newline}'.encode()
        self._terminal = terminal
        self._pending = b''
        self._passthrough = False

    def feed(self, chunk: bytes) -> bytes:
        if self._passthrough:
            return chunk
        data = self._pending + chunk
        self._pending = b''
        if self.phase is None:
            if self._terminal:
                # A PTY may echo early stdin before the launcher writes its
                # header. Preserve that prelude, while looking for the nonce
                # not known to the submitting client before execution starts.
                index = data.find(self._compile)
                if index < 0:
                    return self._hold_partial(data, self._compile)
                prelude = data[:index]
                self.phase = 'compile'
                return prelude + self.feed(data[index + len(self._compile):])
            if len(data) < len(self._compile) and self._compile.startswith(data):
                self._pending = data
                return b''
            if not data.startswith(self._compile):
                self._passthrough = True
                return data
            self.phase = 'compile'
            data = data[len(self._compile):]
        index = data.find(self._run)
        if index >= 0:
            self.phase = 'run'
            self._passthrough = True
            return data[:index] + data[index + len(self._run):]
        # Preserve only a possible partial frame, not arbitrary diagnostics.
        return self._hold_partial(data, self._run)

    def _hold_partial(self, data: bytes, marker: bytes) -> bytes:
        for size in range(min(len(data), len(marker) - 1), 0, -1):
            if data.endswith(marker[:size]):
                self._pending = data[-size:]
                return data[:-size]
        return data

    def finish(self) -> bytes:
        pending, self._pending = self._pending, b''
        self._passthrough = True
        return pending
