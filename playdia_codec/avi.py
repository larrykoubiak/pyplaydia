"""Small RIFF AVI writer for lossless PNG video and optional 16-bit PCM.

Uses the MPNG codec tag. Empty video chunks hold the previous image for one
clock tick, so disc timing does not require storing duplicate PNG payloads.
Format: https://learn.microsoft.com/en-us/windows/win32/directshow/avi-riff-file-reference
"""

import os
from pathlib import Path
from struct import pack
import tempfile


def _chunk(tag, data):
    return tag + pack("<I", len(data)) + data + (b"\0" if len(data) & 1 else b"")


def _stream_header(kind, codec, rate, length, buffer_size, sample_size, width=0, height=0):
    return pack(
        "<4s4sIHHIIIIIIIIhhhh",
        kind, codec, 0, 0, 0, 0, 1, rate, 0, length,
        buffer_size, 0xFFFFFFFF, sample_size, 0, 0, width, height,
    )


class PngAviWriter:
    """Stream an indexed AVI, replacing the destination only after success.

    Each write_video call advances 1/fps seconds. Passing None holds the
    previous picture. The caller supplies PCM in chronological order and
    repeats the last PNG at the final tick for players that skip empty chunks.
    """

    def __init__(self, path, width, height, *, fps=75, sample_rate=None, channels=1):
        if not (0 < width < 32768 and 0 < height < 32768 and fps > 0):
            raise ValueError("Invalid AVI dimensions or frame rate")
        if sample_rate is not None and (sample_rate <= 0 or channels not in (1, 2)):
            raise ValueError("Invalid PCM format")
        self.path = Path(path)
        self.width, self.height, self.fps = width, height, fps
        self.sample_rate, self.channels = sample_rate, channels
        self.block_align = channels * 2
        self.video_ticks = self.audio_samples = 0
        self.video_buffer = self.audio_buffer = 0
        self.index = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = tempfile.NamedTemporaryFile(
            mode="w+b", prefix=self.path.name + ".", suffix=".tmp",
            dir=self.path.parent, delete=False,
        )
        self.file.write(self._header(0, 4))
        self.movi_start = self.file.tell() - 4

    def _header(self, riff_size, movi_size):
        main = pack(
            "<14I", round(1_000_000 / self.fps), 0, 0, 0x10,
            self.video_ticks, 0, 2 if self.sample_rate else 1,
            max(self.video_buffer, self.audio_buffer), self.width, self.height,
            0, 0, 0, 0,
        )
        video = _chunk(b"strh", _stream_header(
            b"vids", b"MPNG", self.fps, self.video_ticks, self.video_buffer,
            0, self.width, self.height,
        ))
        video += _chunk(b"strf", pack(
            "<IiiHH4sIiiII", 40, self.width, self.height, 1, 24,
            b"MPNG", self.width * self.height * 3, 0, 0, 0, 0,
        ))
        streams = _chunk(b"LIST", b"strl" + video)
        if self.sample_rate:
            audio = _chunk(b"strh", _stream_header(
                b"auds", bytes(4), self.sample_rate, self.audio_samples,
                self.audio_buffer, self.block_align,
            ))
            audio += _chunk(b"strf", pack(
                "<HHIIHHH", 1, self.channels, self.sample_rate,
                self.sample_rate * self.block_align, self.block_align, 16, 0,
            ))
            streams += _chunk(b"LIST", b"strl" + audio)
        return (
            b"RIFF" + pack("<I", riff_size) + b"AVI "
            + _chunk(b"LIST", b"hdrl" + _chunk(b"avih", main) + streams)
            + b"LIST" + pack("<I", movi_size) + b"movi"
        )

    def _write(self, tag, data, flags):
        offset = self.file.tell() - self.movi_start
        # Classic RIFF uses 32-bit sizes; never silently wrap an index/length.
        if self.file.tell() + len(data) + 16 * (len(self.index) + 1) + 24 > 0xFFFFFFFF:
            raise ValueError("AVI exceeds the 4 GiB RIFF limit; split the clip")
        self.file.write(_chunk(tag, data))
        self.index.append((tag, flags, offset, len(data)))

    def write_video(self, png=None):
        if png is None and not self.video_ticks:
            raise ValueError("The first video tick needs a PNG image")
        if png is not None and not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Expected a PNG image")
        self._write(b"00dc", png or b"", 0x10 if png else 0)
        self.video_buffer = max(self.video_buffer, len(png or b""))
        self.video_ticks += 1

    def write_audio(self, pcm):
        if self.sample_rate is None:
            raise ValueError("This AVI has no audio stream")
        if len(pcm) % self.block_align:
            raise ValueError("PCM data must contain complete sample frames")
        if pcm:
            self._write(b"01wb", pcm, 0x10)
            self.audio_samples += len(pcm) // self.block_align
            self.audio_buffer = max(self.audio_buffer, len(pcm))

    def close(self):
        if self.file.closed:
            return
        try:
            if not self.video_ticks:
                raise ValueError("Cannot write an AVI without video")
            movi_size = self.file.tell() - self.movi_start
            self.file.write(_chunk(b"idx1", b"".join(pack("<4sIII", *entry) for entry in self.index)))
            end = self.file.tell()
            self.file.seek(0)
            self.file.write(self._header(end - 8, movi_size))
            self.file.close()
            os.replace(self.file.name, self.path)
        except BaseException:
            self.abort()
            raise

    def abort(self):
        self.file.close()
        Path(self.file.name).unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.close()
        else:
            self.abort()
