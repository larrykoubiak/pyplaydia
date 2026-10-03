"""Raw F2 dumps include every marker and preserve complete source sectors."""

from contextlib import redirect_stdout
import csv
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from control_dump import dump_controls
from filestream import Filestream, Imagestream
from main import main


def raw_sector(marker=0xF2, first_byte=0, flags=8, mode=2):
    subheader = bytes([1, 3, flags, 0])
    header = bytes(12) + bytes([0x12, 0x34, 0x56, mode]) + subheader * 2
    payload_size = 2324 if flags & 0x20 else 2048
    payload = bytes([marker, first_byte]) + bytes(payload_size - 2)
    return header + payload + b'\xa5' * (2352 - len(header) - len(payload))


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as file:
        return list(csv.DictReader(file))


class ControlDumpTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.cue = self.root / 'game.cue'
        # No ISO filesystem and no F1 picture are needed to extract these.
        self.first = [
            raw_sector(marker=0xF3),
            raw_sector(),  # All-zero bytes after F2 must remain in the dump.
            raw_sector(first_byte=0xFD, flags=0x8D),  # Audio + EOF + EOR.
            raw_sector(first_byte=0xA7, flags=0x28),  # Form 2, after EOF.
        ]
        unusual = bytearray(raw_sector(first_byte=0xFF))
        unusual[20:24] = b'\xde\xad\xbe\xef'  # Retain the second subheader exactly.
        unusual[100:104] = b'\xfa\xce\xb0\x0c'  # Beyond the CSV prefix.
        self.second = [
            bytes(unusual),
            raw_sector(first_byte=0x44, flags=9),
            raw_sector(first_byte=0x50),
            raw_sector(mode=1),  # Offset 24 is not a Mode 1 payload start.
        ]
        (self.root / 'one.bin').write_bytes(b''.join(self.first))
        (self.root / 'two.bin').write_bytes(b''.join(self.second))
        self.cue.write_text(
            'FILE "one.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n'
            'FILE "two.bin" BINARY\n  TRACK 02 MODE2/2352\n    INDEX 01 00:00:00\n'
        )

    def test_every_marker_is_dumped_in_source_order_with_exact_raw_sectors(self):
        with Imagestream(self.cue) as stream:
            output, count = dump_controls(stream, self.root / 'dump')
        rows = read_csv(output / 'f2.csv')
        binary = (output / 'f2_sectors.bin').read_bytes()
        expected = self.first[1:] + self.second[:3]
        self.assertEqual(count, 6)
        self.assertEqual(binary, b''.join(expected))
        self.assertEqual([row['sector_lba'] for row in rows], ['1', '2', '3', '4', '5', '6'])
        self.assertEqual([row['stream_sector'] for row in rows], ['1', '2', '3', '0', '1', '2'])
        self.assertEqual([row['stream_file'] for row in rows], ['one.bin'] * 3 + ['two.bin'] * 3)
        self.assertEqual(rows[2]['payload_size'], '2324')
        self.assertEqual(rows[3]['subheader_hex'], '01 03 08 00 de ad be ef')
        self.assertEqual(rows[0]['msf_hex'], '12 34 56')
        self.assertFalse(any('candidate' in key or 'slot' in key for key in rows[0]))
        for index, (row, raw) in enumerate(zip(rows, expected)):
            self.assertEqual(row['raw_dump_offset'], str(index * 2352))
            self.assertEqual(int(row['stream_byte_offset']), int(row['stream_sector']) * 2352)
            self.assertEqual(bytes.fromhex(row['prefix_hex']), raw[24:59])
            self.assertEqual(bytes(int(row[f'b{i:02x}'], 16) for i in range(35)), raw[24:59])
        summary = json.loads((output / 'summary.json').read_text())
        self.assertEqual(summary['f2_records'], 6)
        self.assertEqual(summary['sectors_scanned'], 8)
        self.assertEqual([s['f2_records'] for s in summary['streams']], [3, 3])

    def test_cli_dumps_all_sectors_despite_media_limit_and_without_opening_iso(self):
        with patch('main.ISOImage') as iso, redirect_stdout(io.StringIO()) as log:
            result = main(['-c', str(self.cue), '--controls', '-l', '1', '-d', str(self.root)])
        self.assertEqual(result, 0)
        iso.assert_not_called()
        self.assertIn('6 F2 records', log.getvalue())
        self.assertIn(str(self.root / 'controls' / 'f2.csv'), log.getvalue())
        self.assertEqual(len(read_csv(self.root / 'controls' / 'f2.csv')), 6)
        self.assertFalse((self.root / 'controls' / 'GAME.GLB').exists())

    def test_raw_dump_finishes_before_a_combined_video_export_fails(self):
        context = MagicMock()
        context.__enter__.return_value.Files = [object()]
        context.__enter__.return_value.ReadVideo.side_effect = ValueError('bad picture')
        with patch('main.ISOImage', return_value=context), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'bad picture'):
                main(['-c', str(self.cue), '--controls', '-v', '-d', str(self.root)])
        self.assertEqual(len(read_csv(self.root / 'controls' / 'f2.csv')), 6)

    def test_no_tracks_or_truncated_source_fails_before_writing_outputs(self):
        output = self.root / 'dump'
        with self.assertRaisesRegex(ValueError, 'No supported tracks'):
            dump_controls(SimpleNamespace(Streams=[]), output)
        short = self.root / 'short.bin'
        short.write_bytes(raw_sector()[:-1])
        with Filestream(short) as source:
            with self.assertRaisesRegex(ValueError, 'Incomplete 2352-byte sector'):
                dump_controls(SimpleNamespace(Streams=[source]), output)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
