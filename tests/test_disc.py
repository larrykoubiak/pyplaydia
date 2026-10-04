"""Disc timestamps, file ownership and extraction CLI regressions."""

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from filestream import Filestream, Imagestream
from iso9660 import ISOImage
from main import main
from sector import Sector


def sector_bytes():
    subheader = bytes([1, 0, 8, 0])
    return bytes(12) + bytes([0x12, 0x34, 0x56, 2]) + subheader * 2 + bytes(2328)


class SectorTests(unittest.TestCase):
    def test_bcd_timestamps_do_not_change_serialized_header(self):
        raw = sector_bytes()
        sector = Sector(raw[:24], 0, 0)
        self.assertEqual((sector.Minute, sector.Second, sector.Block), (12, 34, 56))
        sector.Data, sector.ECC = raw[24:2072], raw[2072:]
        self.assertEqual(sector.ToBytes(), raw)


class DiscResourceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.track = self.root / "track.bin"
        self.track.write_bytes(sector_bytes())
        self.cue = self.root / "game.cue"
        self.cue.write_text('FILE "track.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
        self.opened = []

    def open_file(self, *args, **kwargs):
        stream = open(*args, **kwargs)
        self.opened.append(stream)
        return stream

    def test_contexts_close_tracks_and_close_is_idempotent(self):
        with Filestream(self.track) as file:
            self.assertEqual(file.Length, 2352)
        self.assertTrue(file.Stream.closed)
        file.close()
        with Imagestream(self.cue) as image:
            self.assertEqual(image.ReadSector(0).ToBytes(), sector_bytes())
        self.assertTrue(image.Streams[0].Stream.closed)
        image.close()

    def test_iso_context_closes_tracks_on_exit_and_exception(self):
        # The fixture tests file ownership, without needing a full ISO volume.
        with patch.object(ISOImage, "_ISOImage__readVolumeDescriptors"), patch("filestream.open", side_effect=self.open_file, create=True):
            with ISOImage(self.cue) as image:
                pass
            image.close()
            with self.assertRaisesRegex(RuntimeError, "export failed"):
                with ISOImage(self.cue):
                    raise RuntimeError("export failed")
        self.assertTrue(all(stream.closed for stream in self.opened))

    def test_partial_cue_and_invalid_iso_close_already_open_tracks(self):
        with patch("filestream.open", side_effect=self.open_file, create=True):
            with self.assertRaises(IndexError):
                ISOImage(self.cue)  # No volume descriptor at sector 16.
            self.assertTrue(all(stream.closed for stream in self.opened))
            self.cue.write_text(self.cue.read_text() + 'FILE "missing.bin" BINARY\n  TRACK 02 MODE2/2352\n    INDEX 01 00:00:00\n')
            with self.assertRaises(FileNotFoundError):
                Imagestream(self.cue)
            self.assertTrue(all(stream.closed for stream in self.opened))

    def test_disc_write_flushes_output_and_closes_it_on_failure(self):
        with patch("filestream.open", side_effect=self.open_file, create=True):
            with Imagestream(self.cue) as image:
                image.Write(self.root, "copy")
                self.assertEqual((self.root / "copy (Track 01).bin").read_bytes(), sector_bytes())
                self.assertTrue(all(stream.closed for stream in self.opened if stream.mode == "wb"))
                with patch.object(Sector, "ToBytes", side_effect=OSError("write failed")):
                    with self.assertRaisesRegex(OSError, "write failed"):
                        image.Write(self.root, "failed")
                self.assertFalse((self.root / "failed.cue").exists())
        self.assertTrue(all(stream.closed for stream in self.opened))


class CliTests(unittest.TestCase):
    def test_no_export_mode_prints_help_without_opening_a_disc(self):
        for args in ([], ["-c", "missing.cue"]):
            with self.subTest(args=args), patch("main.ISOImage") as image, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args), 0)
                self.assertIn("usage:", output.getvalue())
                image.assert_not_called()

    def test_missing_cue_and_negative_limit_fail_before_opening_a_disc(self):
        for args, message in ((["-a"], "--cue_path is required"), (["--controls"], "--cue_path is required"), (["--play"], "--cue_path is required"), (["-v", "-c", "missing.cue", "-l", "-1"], "--limit must be zero or greater")):
            with self.subTest(args=args), patch("main.ISOImage") as image, redirect_stderr(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as error:
                    main(args)
                self.assertEqual(error.exception.code, 2)
                self.assertIn(message, output.getvalue())
                image.assert_not_called()

    def test_export_error_exits_the_disc_context(self):
        context = MagicMock()
        context.__enter__.return_value.Files = [object()]
        context.__enter__.return_value.ReadVideo.side_effect = ValueError("bad picture")
        with patch("main.ISOImage", return_value=context), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "bad picture"):
                main(["-c", "game.cue", "-v", "-l", "1"])
        context.__exit__.assert_called_once()
        self.assertIs(context.__exit__.call_args.args[0], ValueError)


if __name__ == "__main__":
    unittest.main()
