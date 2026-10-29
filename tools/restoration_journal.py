"""Lossless bounded transport for the original restoration JSONL byte stream."""

from contextlib import contextmanager
import gzip
from pathlib import Path


class Journal:
    def __init__(self, stream, limit):
        self.stream, self.limit, self.count = stream, limit, 0

    def write(self, value):
        if self.count + len(value) > self.limit:
            raise ValueError("restoration logical journal byte ceiling exhausted")
        result = self.stream.write(value)
        self.count += result
        return result

    def read(self, size):
        if not 0 <= size <= 128 * 1024 + 1:
            raise ValueError("bounded restoration journal read required")
        return self._account(self.stream.read(size))

    def readline(self, size):
        if not 0 < size <= 128 * 1024 + 1:
            raise ValueError("bounded restoration journal line required")
        return self._account(self.stream.readline(size))

    def _account(self, value):
        self.count += len(value)
        if self.count > self.limit:
            raise ValueError("restoration decoded journal byte ceiling exhausted")
        return value

    def tell(self):
        return self.count

    def flush(self):
        return self.stream.flush()

    def fileno(self):
        return self.stream.fileno()


@contextmanager
def open_journal(path, mode, *, compressed=False, maximum_bytes):
    if mode not in {"xb", "rb"} or type(maximum_bytes) is not int or maximum_bytes <= 0:
        raise ValueError("invalid restoration journal transport")
    path = Path(path)
    if compressed and path.suffix != ".gz":
        raise ValueError("compressed restoration journal needs explicit .gz suffix")
    with path.open(mode) as raw:
        if compressed:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb" if mode == "xb" else "rb", compresslevel=9, mtime=0) as stream:
                yield Journal(stream, maximum_bytes)
        else:
            yield Journal(raw, maximum_bytes)
