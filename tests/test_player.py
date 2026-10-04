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
from playdia_player.engine import PlaybackEngine, PlaybackState, READ_AHEAD_TICKS
from playdia_player.pygame_frontend import (
    AudioStream,
    GamepadInputMapper,
    STICK_PRESS_THRESHOLD,
)
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


class AudioStreamTests(unittest.TestCase):
    def test_callback_clock_counts_played_pcm_but_not_underrun_silence(self):
        now = [10.0]
        devices = []

        class FakeDevice:
            def __init__(self, *arguments):
                self.callback = arguments[-1]
                self.pauses = []
                self.closed = False
                devices.append(self)

            def pause(self, value):
                self.pauses.append(value)

            def close(self):
                self.closed = True

        audio = AudioStream(FakeDevice, 0, clock=lambda: now[0])
        device = devices[0]
        pcm = bytes(range(24))  # Six stereo sample frames.
        audio.extend((pcm[:12], pcm[12:]))

        first = bytearray(16)
        device.callback(device, first)
        self.assertEqual(first, pcm[:16])
        self.assertEqual(audio.position, 0.0)

        now[0] += 2 / 37800
        self.assertAlmostEqual(audio.position, 2 / 37800)
        now[0] += 2 / 37800

        second = bytearray(16)
        device.callback(device, second)
        self.assertEqual(second, pcm[16:] + bytes(8))
        self.assertAlmostEqual(audio.position, 4 / 37800)

        now[0] += 10 / 37800
        self.assertAlmostEqual(audio.position, 6 / 37800)
        self.assertTrue(audio.drained)
        audio.reset()
        self.assertFalse(audio.has_audio)
        self.assertEqual(audio.position, 0.0)
        audio.close()
        self.assertEqual(device.pauses, [0, 1])
        self.assertTrue(device.closed)


class GamepadInputTests(unittest.TestCase):
    def make_mapper(self):
        constants = SimpleNamespace(
            CONTROLLER_AXIS_LEFTX=0,
            CONTROLLER_AXIS_LEFTY=1,
            CONTROLLER_BUTTON_A=0,
            CONTROLLER_BUTTON_B=1,
            CONTROLLER_BUTTON_DPAD_UP=11,
            CONTROLLER_BUTTON_DPAD_DOWN=12,
            CONTROLLER_BUTTON_DPAD_LEFT=13,
            CONTROLLER_BUTTON_DPAD_RIGHT=14,
        )
        return GamepadInputMapper(constants)

    def test_face_buttons_are_positionally_swapped_and_dpad_maps_directly(self):
        mapper = self.make_mapper()
        self.assertEqual(mapper.button_down(0), ControlInput.B)
        self.assertEqual(mapper.button_down(1), ControlInput.A)
        self.assertEqual(mapper.button_down(11), ControlInput.UP)
        self.assertEqual(mapper.button_down(12), ControlInput.DOWN)
        self.assertEqual(mapper.button_down(13), ControlInput.LEFT)
        self.assertEqual(mapper.button_down(14), ControlInput.RIGHT)
        self.assertIsNone(mapper.button_down(2))

    def test_left_stick_emits_once_per_deflection_with_a_dead_zone(self):
        mapper = self.make_mapper()
        controller = 42
        self.assertIsNone(mapper.axis_motion(controller, 0, STICK_PRESS_THRESHOLD - 1))
        self.assertEqual(
            mapper.axis_motion(controller, 0, STICK_PRESS_THRESHOLD),
            ControlInput.RIGHT,
        )
        self.assertIsNone(mapper.axis_motion(controller, 0, 32767))
        self.assertIsNone(mapper.axis_motion(controller, 0, 0))
        self.assertEqual(
            mapper.axis_motion(controller, 1, -STICK_PRESS_THRESHOLD),
            ControlInput.UP,
        )
        self.assertIsNone(mapper.axis_motion(controller, 1, 0))
        self.assertEqual(
            mapper.axis_motion(controller, 0, -STICK_PRESS_THRESHOLD),
            ControlInput.LEFT,
        )
        mapper.remove(controller)
        self.assertEqual(
            mapper.axis_motion(controller, 1, STICK_PRESS_THRESHOLD),
            ControlInput.DOWN,
        )


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

    def test_initial_buffer_collects_packet_without_decoding_it(self):
        with patch("playdia_player.engine.Picture.from_bytes") as decode:
            engine = PlaybackEngine(self.make_stream(), 0)
        decode.assert_not_called()
        segment = engine.segment
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

    def test_route_can_land_in_an_f1_continuation_and_resynchronize(self):
        first = controlled_picture(0x44, [(ControlInput.A, 5, 0)])
        destination = controlled_picture(0x80)
        track = [
            sector(first[:2048]),
            sector(first[2048:], Submodes.Data | Submodes.EOR),
            sector(bytes(2048)),
            sector(bytes(2048)),
            sector(bytes(2048)),
            sector(bytes((0xF1,)) + bytes(2047)),
            sector(bytes((0xF2,)) + bytes(2047)),
            sector(bytes(2048)),
            sector(destination[:2048]),
            sector(destination[2048:], Submodes.Data | Submodes.EOR),
            sector(b"", Submodes.EOF),
        ]

        engine = PlaybackEngine(fake_stream(track), 0)
        self.assertTrue(engine.press(ControlInput.A))
        self.assertEqual(engine.segment.start_lba, 5)
        self.assertIsNone(engine.current_frame)
        engine.advance_to(3 / 75)
        self.assertEqual(engine.current_frame.lba, 8)
        self.assertEqual(len(engine.current_frame.decode_rgb()), 248 * 216 * 3)

    def test_multi_picture_end_auto_routes_and_single_picture_end_holds(self):
        engine = PlaybackEngine(self.make_stream(), 0)
        engine.advance(2 / 75)
        self.assertEqual(engine.segment.start_lba, 5)
        self.assertEqual(engine.last_transition.input, ControlInput.NO_INPUT)
        engine.advance(2 / 75)
        self.assertEqual(engine.state, PlaybackState.HOLDING)
        self.assertEqual(engine.current_frame.lba, 5)

    def test_reader_keeps_a_two_second_rolling_horizon(self):
        packet = controlled_picture(0)
        track = [sector(packet[:2048]), sector(packet[2048:])]
        track.extend(sector(bytes(2048)) for _ in range(298))
        track.append(sector(b"", Submodes.EOF))
        calls = []
        stream = SimpleNamespace(
            Sectors=track,
            ReadSector=lambda index: calls.append(index) or track[index],
        )
        engine = PlaybackEngine(stream, 0)
        self.assertEqual(engine.segment.cursor_lba, READ_AHEAD_TICKS)
        self.assertIsNone(engine.segment.stop_lba)
        self.assertLess(max(calls), READ_AHEAD_TICKS)
        engine.advance(1)
        self.assertEqual(engine.segment.cursor_lba, READ_AHEAD_TICKS + 75)

    def test_audio_is_emitted_in_normalized_streaming_chunks(self):
        packet = controlled_picture(0x80)
        stream = fake_stream([
            sector(packet[:2048]),
            sector(packet[2048:]),
            sector(bytes(2304), Submodes.Audio, channel=2, coding=4),
            sector(bytes(2304), Submodes.Audio, channel=2, coding=4),
            sector(bytes(2048), Submodes.Data | Submodes.EOR),
            sector(b"", Submodes.EOF),
        ])
        engine = PlaybackEngine(stream, 0)
        chunks = engine.take_audio_chunks()
        self.assertEqual([len(chunk) for chunk in chunks], [37800, 26712])
        self.assertEqual(engine.take_audio_chunks(), ())
        self.assertAlmostEqual(engine.segment.duration, 8064 / 18900)

    def test_frames_follow_sector_timestamps_instead_of_a_fixed_frame_rate(self):
        track = [sector(bytes(2048)) for _ in range(18)]
        for lba in (0, 7, 15):
            packet = controlled_picture(0x80)
            track[lba] = sector(packet[:2048])
            track[lba + 1] = sector(packet[2048:])
        track[16].Submode |= Submodes.EOR
        track[17] = sector(b"", Submodes.EOF)

        engine = PlaybackEngine(fake_stream(track), 0)
        self.assertEqual(engine.current_frame.lba, 0)
        engine.advance_to(7 / 75)
        self.assertEqual(engine.current_frame.lba, 7)
        engine.advance_to(15 / 75)
        self.assertEqual(engine.current_frame.lba, 15)

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
