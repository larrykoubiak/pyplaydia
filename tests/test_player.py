"""Synthetic tests for headless playback and the optional CLI frontend."""

from contextlib import redirect_stderr
import io
from struct import pack, unpack
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from main import main
from playdia_codec import ControlInput
from playdia_player.audio import normalize_pcm
from playdia_player.engine import PlaybackEngine, PlaybackState, SegmentReader
from sector import Codings, Submodes
from test_playdia_codec import picture_bytes, sectors


def sector(data, submode=Submodes.Data, channel=0, coding=0):
    return SimpleNamespace(Data=data, Submode=submode, Channel=channel, Coding=Codings(coding))


def controlled_picture(flags, routes=()):
    packet = bytearray(sectors(picture_bytes()))
    f2 = len(packet) - 2048
    packet[f2 + 1] = flags
    for input_value, target_lba, value in routes:
        absolute = target_lba + 150
        minutes, remainder = divmod(absolute, 4500)
        seconds, frames = divmod(remainder, 75)
        if frames % 5:
            raise ValueError("Synthetic route targets must be five-sector aligned")
        offset = f2 + 3 + int(input_value) * 4
        packet[offset:offset + 4] = bytes((minutes, seconds, frames // 5, value))
    return bytes(packet)


def fake_stream(track):
    return SimpleNamespace(Sectors=track, ReadSector=lambda index: track[index])


class AudioNormalizationTests(unittest.TestCase):
    def test_native_rates_and_channels_normalize_to_fixed_stereo(self):
        mono = pack("<2h", 1, -2)
        stereo = pack("<4h", 1, -1, 2, -2)
        self.assertEqual(unpack("<4h", normalize_pcm(mono, 37800, 1)), (1, 1, -2, -2))
        self.assertEqual(
            unpack("<8h", normalize_pcm(mono, 18900, 1)),
            (1, 1, 1, 1, -2, -2, -2, -2),
        )
        self.assertEqual(normalize_pcm(stereo, 37800, 2), stereo)
        self.assertEqual(
            unpack("<8h", normalize_pcm(stereo, 18900, 2)),
            (1, -1, 1, -1, 2, -2, 2, -2),
        )

    def test_invalid_pcm_format_is_rejected(self):
        for arguments in ((b"", 44100, 2), (b"", 37800, 3), (b"\x00", 37800, 1)):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                normalize_pcm(*arguments)


class PlayerEngineTests(unittest.TestCase):
    def make_stream(self):
        first = controlled_picture(0x44, [
            (ControlInput.A, 5, 0x2A),
            (ControlInput.NO_INPUT, 5, 0),
        ])
        second = controlled_picture(0x80)
        return fake_stream([
            sector(first[:2048]),
            sector(first[2048:], Submodes.Data | Submodes.EOR),
            sector(bytes(2048)),
            sector(bytes(2048)),
            sector(bytes(2048)),
            sector(second[:2048]),
            sector(second[2048:], Submodes.Data | Submodes.EOR),
            sector(b"", Submodes.EOF),
        ])

    def test_segment_reader_decodes_timed_picture_and_boundary(self):
        with patch("playdia_player.engine.Picture.from_bytes") as decode:
            segment = SegmentReader(self.make_stream()).read(0)
        decode.assert_not_called()
        self.assertEqual((segment.start_lba, segment.stop_lba), (0, 2))
        self.assertEqual(len(segment.frames), 1)
        self.assertEqual((segment.frames[0].lba, segment.frames[0].tick), (0, 0))
        self.assertEqual(len(segment.frames[0].decode_rgb()), 248 * 216 * 3)
        self.assertEqual(segment.duration, 2 / 75)

    def test_button_route_seeks_and_preserves_route_value(self):
        engine = PlaybackEngine(self.make_stream(), 0)
        self.assertTrue(engine.press(ControlInput.A))
        self.assertEqual(engine.segment.start_lba, 5)
        self.assertEqual(engine.last_transition.target_lba, 5)
        self.assertEqual(engine.last_transition.value, 0x2A)
        self.assertIn("value 2A", engine.message)

    def test_multi_picture_end_auto_routes_and_single_picture_end_holds(self):
        engine = PlaybackEngine(self.make_stream(), 0)
        engine.advance(2 / 75)
        self.assertEqual(engine.segment.start_lba, 5)
        self.assertEqual(engine.last_transition.input, ControlInput.NO_INPUT)
        engine.advance(2 / 75)
        self.assertEqual(engine.state, PlaybackState.HOLDING)
        self.assertEqual(engine.current_frame.lba, 5)

    def test_automatic_destination_can_be_prefetched_and_reused(self):
        engine = PlaybackEngine(self.make_stream(), 0)
        with patch.object(engine.reader, "read", wraps=engine.reader.read) as read:
            self.assertTrue(engine.prefetch_automatic_segment())
            engine._prefetched_segment.result(timeout=1)
            engine.advance(2 / 75)
        self.assertEqual(engine.segment.start_lba, 5)
        self.assertEqual(read.call_count, 1)
        engine.close()

    def test_empty_routes_do_not_restart_or_seek_negative_lba(self):
        engine = PlaybackEngine(self.make_stream(), 5)
        generation = engine.generation
        self.assertFalse(engine.press(ControlInput.B))
        self.assertEqual(engine.generation, generation)
        self.assertIn("empty or special", engine.message)


class PlayerCliTests(unittest.TestCase):
    def test_play_and_gui_alias_lazily_call_frontend(self):
        for option in ("--play", "--gui"):
            with self.subTest(option=option), patch(
                "playdia_player.pygame_frontend.run_player", return_value=7
            ) as run:
                self.assertEqual(main(["-c", "game.cue", option]), 7)
                run.assert_called_once_with("game.cue")

    def test_play_rejects_extraction_mode(self):
        with redirect_stderr(io.StringIO()) as output, self.assertRaises(SystemExit) as error:
            main(["-c", "game.cue", "--play", "-v"])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("cannot be combined", output.getvalue())


if __name__ == "__main__":
    unittest.main()
