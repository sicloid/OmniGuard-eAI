"""ADR-0003 length-prefixed framing for the Unix domain socket bridge.

Every message is a four-byte big-endian unsigned length followed by exactly that
many bytes. The declared length is checked against `MAX_FRAME` *before* the body
is read, so a fabricated header cannot make the reader allocate.
"""

import struct

HEADER = struct.Struct(">I")
HEADER_SIZE = HEADER.size
MAX_FRAME = 65536


class FrameError(ValueError):
    """A frame could not be produced or consumed; never process a partial record."""


class FrameTooLarge(FrameError):
    """The declared or supplied body exceeds the configured bound."""


class IncompleteFrame(FrameError):
    """The stream ended in the middle of a frame."""


def encode_frame(body: bytes) -> bytes:
    if not isinstance(body, bytes | bytearray):
        raise FrameError("frame body must be bytes")
    if not body:
        raise FrameError("empty frame carries no record")
    if len(body) > MAX_FRAME:
        raise FrameTooLarge(f"{len(body)} bytes exceeds MAX_FRAME {MAX_FRAME}")
    return HEADER.pack(len(body)) + bytes(body)


def _read_exactly(stream, count: int) -> bytes | None:
    """Return `count` bytes, None on a clean boundary EOF, or raise on a partial read."""
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if not chunks and remaining == count:
                return None
            raise IncompleteFrame(f"stream ended {remaining} bytes short of {count}")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream) -> bytes | None:
    """Read one frame, or None at a clean end of stream.

    The size check happens between the header and the body: an oversized frame
    is rejected without reading or buffering its payload.
    """
    header = _read_exactly(stream, HEADER_SIZE)
    if header is None:
        return None
    (length,) = HEADER.unpack(header)
    if length == 0:
        raise FrameError("declared frame length is zero")
    if length > MAX_FRAME:
        raise FrameTooLarge(f"declared {length} bytes exceeds MAX_FRAME {MAX_FRAME}")
    body = _read_exactly(stream, length)
    if body is None:
        raise IncompleteFrame(f"no body after a {length} byte header")
    return body
