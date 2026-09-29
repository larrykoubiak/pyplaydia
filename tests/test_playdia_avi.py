"""AVI round trips and scene/audio regressions using synthetic disc sectors."""

from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
from pathlib import Path
from struct import pack, unpack, unpack_from
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from PIL import Image

from iso9660 import ISOImage
from playdia_codec import DecodeError, Picture
from playdia_codec.avi import PngAviWriter
from playdia_codec.video_export import export_scene
from playdia_codec.adpcm import XaAudioDecoder
from sector import Codings, Submodes
from test_playdia_codec import escape, picture_bytes, sectors


def chunks(data, start, end):
    while start < end:
        tag, size = unpack_from("<4sI", data, start)
        stop = start + 8 + size
        if stop > end:
            raise AssertionError("RIFF chunk exceeds its enclosing list")
        yield tag, data[start + 8:stop], start
        start = stop + (size & 1)
    if start != end:
        raise AssertionError("RIFF alignment mismatch")


def read_avi(path):
    data = Path(path).read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"AVI "
    assert unpack_from("<I", data, 4)[0] == len(data) - 8
    top = list(chunks(data, 12, len(data)))
    header = next(payload for tag, payload, _ in top if tag == b"LIST" and payload[:4] == b"hdrl")
    headers = list(chunks(header, 4, len(header)))
    streams = []
    for tag, payload, _ in headers:
        if tag == b"LIST" and payload[:4] == b"strl":
            streams.append({name: value for name, value, _ in chunks(payload, 4, len(payload))})
    movi = next(position + 8 for tag, payload, position in top if tag == b"LIST" and payload[:4] == b"movi")
    payload = next(payload for tag, payload, _ in top if tag == b"LIST" and payload[:4] == b"movi")
    media = list(chunks(data, movi + 4, movi + len(payload)))
    index = next(payload for tag, payload, _ in top if tag == b"idx1")
    assert len(index) == len(media) * 16
    for entry, (tag, payload, position) in zip(range(0, len(index), 16), media):
        name, flags, offset, size = unpack_from("<4sIII", index, entry)
        assert (name, size, movi + offset) == (tag, len(payload), position)
        assert bool(flags & 0x10) == bool(payload)
    return streams, media


def sector(data, submode=Submodes.Data, channel=0, coding=0):
    return SimpleNamespace(Data=data, Submode=submode, Channel=channel, Coding=Codings(coding))


def fake_disc(track):
    stream = SimpleNamespace(Sectors=track, ReadSector=lambda index: track[index])
    disc = ISOImage.__new__(ISOImage)
    disc._ISOImage__imagestream = stream
    return disc, stream


class XaAudioTests(unittest.TestCase):
    def test_native_mono_predictor_history_across_sectors(self):
        group = bytes(4) + bytes([0x18, 0x09, 0x2A, 0x3B] * 2) + bytes(4)
        group += bytes((index * 37 + 19) % 256 for index in range(112))
        data = group * 18
        decoder = XaAudioDecoder(4)
        # Recorded from the original ADPCMBlock with resampling bypassed.
        # Filter 1 at the start makes the second sector depend on the first.
        for expected in (
            "581b81ecaf72fe2a74aed610b3d0ce899e187fc7c4dfe912ef6d4db7e608182c",
            "ce6da689da2e41d3aaea8a493df3241a3a7195506b23880759cd487f10c83bac",
        ):
            pcm = decoder.decode_sector(data)
            self.assertEqual(len(pcm), 4032 * 2)
            self.assertEqual(sha256(pcm).hexdigest(), expected)
        self.assertEqual((decoder.sample_rate, decoder.channels), (18900, 1))

    def test_stereo_units_are_interleaved_and_native_rates_are_preserved(self):
        data = (bytes([12]) * 16 + bytes([0xF1, 0xE2, 0xD3, 0xC4]) * 28) * 18
        expected = [value for amplitude in range(1, 5) for _ in range(28) for value in (amplitude, -amplitude)] * 18
        for coding, rate in [(1, 37800), (5, 18900)]:
            decoder = XaAudioDecoder(coding)
            self.assertEqual((decoder.sample_rate, decoder.channels), (rate, 2))
            self.assertEqual(unpack("<4032h", decoder.decode_sector(data)), tuple(expected))

    def test_unsupported_or_truncated_audio_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "8-bit"):
            XaAudioDecoder(0x10)
        with self.assertRaisesRegex(ValueError, "Truncated"):
            XaAudioDecoder(4).decode_sector(bytes(2303))


class AviTests(unittest.TestCase):
    def test_png_pixels_pcm_samples_and_index_round_trip(self):
        rgb = bytes(range(18))
        image = Image.frombytes("RGB", (3, 2), rgb)
        png = io.BytesIO()
        image.save(png, format="PNG")
        pcm = pack("<4h", -32768, -1, 0, 32767)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "video.avi"
            with PngAviWriter(path, 3, 2, sample_rate=18900) as avi:
                avi.write_video(png.getvalue())
                avi.write_audio(pcm)
                avi.write_video()
                avi.write_video(png.getvalue())
            streams, media = read_avi(path)
            self.assertEqual(streams[0][b"strh"][:8], b"vidsMPNG")
            self.assertEqual(unpack_from("<II", streams[0][b"strh"], 20), (1, 75))
            self.assertEqual(unpack_from("<I", streams[0][b"strh"], 32)[0], 3)
            self.assertEqual(unpack_from("<HHI", streams[1][b"strf"]), (1, 1, 18900))
            frames = [payload for tag, payload, _ in media if tag == b"00dc"]
            self.assertEqual(frames[1], b"")
            for payload in (frames[0], frames[-1]):
                self.assertEqual(Image.open(io.BytesIO(payload)).tobytes(), rgb)
            self.assertEqual(b"".join(payload for tag, payload, _ in media if tag == b"01wb"), pcm)

    def test_failure_preserves_existing_file_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "video.avi"
            path.write_bytes(b"existing output")
            with self.assertRaisesRegex(ValueError, "first video"):
                with PngAviWriter(path, 248, 216) as avi:
                    avi.write_video()
            self.assertEqual(path.read_bytes(), b"existing output")
            self.assertEqual(list(Path(directory).iterdir()), [path])


class SceneExportTests(unittest.TestCase):
    def test_sector_timing_audio_tail_and_channel_selection(self):
        first = sectors(picture_bytes())
        second = sectors(picture_bytes(lambda row, block: escape(0, 8) + "01" if block == 0 else "01"))
        audio = (bytes([12]) * 16 + bytes([0x21]) * 112) * 18
        track = [
            sector(bytes(2324)),
            sector(first[:2048]),
            sector(audio, Submodes.Audio | Submodes.EOR, channel=2, coding=4),
            sector(bytes(2324), Submodes.Audio, channel=3, coding=5),
            sector(first[2048:]),
            sector(b"\xf3" + bytes(2047)),
            sector(second[:2048]),
            sector(second[2048:], Submodes.Data | Submodes.EOR),
            sector(b"", Submodes.EOF),
        ]
        disc, _ = fake_disc(track)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            disc.ReadVideo(SimpleNamespace(ExtentLocation=0), directory)
            streams, media = read_avi(Path(directory) / "video_000.avi")
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
            self.assertEqual(unpack_from("<I", streams[0][b"strh"], 32)[0], 16)
            self.assertEqual(unpack_from("<I", streams[1][b"strh"], 32)[0], 4032)
            frames = [payload for tag, payload, _ in media if tag == b"00dc"]
            self.assertEqual([i for i, png in enumerate(frames) if png], [0, 5, 15])
            for index, packet in [(0, first), (5, second), (15, second)]:
                self.assertEqual(Image.open(io.BytesIO(frames[index])).tobytes(), Picture.from_bytes(packet).decode_rgb())
            self.assertEqual(b"".join(payload for tag, payload, _ in media if tag == b"01wb"), XaAudioDecoder(4).decode_sector(audio))
            disc.ReadAudio(SimpleNamespace(ExtentLocation=0), directory)
            with wave.open(str(Path(directory) / "audio_000.wav"), "rb") as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 18900))
                self.assertEqual(wav.readframes(wav.getnframes()), b"".join(payload for tag, payload, _ in media if tag == b"01wb"))

    def test_scene_limit_silent_clip_and_final_scene_at_eof(self):
        packet = sectors(picture_bytes())
        disc, _ = fake_disc([
            sector(packet[:2048]),
            sector(packet[2048:], Submodes.Data | Submodes.EOR),
            sector(packet[:2048]),
            sector(packet[2048:]),
            sector(b"", Submodes.EOF),
        ])
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            disc.ReadVideo(SimpleNamespace(ExtentLocation=0), directory, limit=1)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["video_000.avi"])
            disc.ReadVideo(SimpleNamespace(ExtentLocation=0), directory)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["video_000.avi", "video_001.avi"])
            streams, media = read_avi(Path(directory) / "video_001.avi")
            self.assertEqual(len(streams), 1)
            self.assertEqual(len(media), 2)
            self.assertTrue(all(payload for _, payload, _ in media))

    def test_control_only_scene_is_skipped_and_truncated_picture_fails(self):
        _, stream = fake_disc([sector(bytes(2324))])
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            path = Path(directory) / "video.avi"
            self.assertEqual(export_scene(stream, 0, 1, path), 0)
            self.assertFalse(path.exists())
            stream.Sectors[0].Data = sectors(picture_bytes())[:2048]
            with self.assertRaisesRegex(DecodeError, "incomplete picture"):
                export_scene(stream, 0, 1, path)
            self.assertFalse(path.exists())


class WavExportTests(unittest.TestCase):
    def test_scene_limit_numbering_stereo_and_eof_flush(self):
        audio = (bytes([12]) * 16 + bytes([0xF1, 0xE2, 0xD3, 0xC4]) * 28) * 18
        disc, _ = fake_disc([
            sector(b"", Submodes.Data | Submodes.EOR),  # Silent scene 0.
            sector(audio, Submodes.Audio | Submodes.EOR, coding=1),
            sector(b"", Submodes.Data | Submodes.EOR),
            sector(audio, Submodes.Audio, coding=5),  # Scene 2 ends at EOF.
            sector(b"", Submodes.EOF),
        ])
        record = SimpleNamespace(ExtentLocation=0)
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            disc.ReadAudio(record, directory, limit=1)
            self.assertEqual(list(Path(directory).iterdir()), [])
            disc.ReadAudio(record, directory, limit=2)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["audio_001.wav"])
            disc.ReadAudio(record, directory)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["audio_001.wav", "audio_002.wav"])
            expected = tuple(value for amplitude in range(1, 5) for _ in range(28) for value in (amplitude, -amplitude)) * 18
            for scene, rate in [(1, 37800), (2, 18900)]:
                with wave.open(str(Path(directory) / f"audio_{scene:03}.wav"), "rb") as wav:
                    self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getnframes()), (2, rate, 2016))
                    self.assertEqual(unpack("<4032h", wav.readframes(2016)), expected)

    def test_audio_eor_keeps_history_until_scene_end(self):
        group = bytes(4) + bytes([0x18, 0x09, 0x2A, 0x3B] * 2) + bytes(4)
        group += bytes((index * 37 + 19) % 256 for index in range(112))
        audio = group * 18
        disc, _ = fake_disc([
            sector(audio, Submodes.Audio | Submodes.EOR, coding=4),
            sector(audio, Submodes.Audio, coding=4),
            sector(b"", Submodes.Data | Submodes.EOR),
            sector(audio, Submodes.Audio, coding=4),  # End of track without EOF.
        ])
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            disc.ReadAudio(SimpleNamespace(ExtentLocation=0), directory)
            with wave.open(str(Path(directory) / "audio_000.wav"), "rb") as wav:
                self.assertEqual(wav.getnframes(), 8064)
                first = wav.readframes(4032)
                self.assertEqual(sha256(wav.readframes(4032)).hexdigest(), "ce6da689da2e41d3aaea8a493df3241a3a7195506b23880759cd487f10c83bac")
            with wave.open(str(Path(directory) / "audio_001.wav"), "rb") as wav:
                self.assertEqual(wav.readframes(wav.getnframes()), first)

    def test_format_change_closes_wav_even_when_export_fails(self):
        disc, _ = fake_disc([
            sector(bytes(2304), Submodes.Audio, coding=4),
            sector(bytes(2304), Submodes.Audio, coding=5),
        ])
        opened = []
        wave_open = wave.open

        def open_wav(path, mode):
            wav = wave_open(path, mode)
            opened.append(wav._file)
            return wav

        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            with patch("iso9660.wave.open", side_effect=open_wav), self.assertRaisesRegex(ValueError, "format changes"):
                disc.ReadAudio(SimpleNamespace(ExtentLocation=0), directory)
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].closed)
            with wave.open(str(Path(directory) / "audio_000.wav"), "rb") as wav:
                self.assertEqual(wav.getnframes(), 4032)


if __name__ == "__main__":
    unittest.main()
