"""Dump every F2-marked Mode 2 sector without interpreting its payload."""

import csv
import json
from pathlib import Path


RAW_SECTOR_SIZE = 2352
PAYLOAD_OFFSET = 24
PREFIX_SIZE = 35  # F2 plus the next 34 bytes, for convenient spreadsheet viewing.
BYTE_COLUMNS = [f"b{offset:02x}" for offset in range(PREFIX_SIZE)]
RECORD_COLUMNS = [
    "record", "sector_lba", "stream_file", "stream_id", "stream_sector",
    "stream_byte_offset", "raw_dump_offset", "payload_size", "msf_hex",
    "subheader_hex", "prefix_hex",
] + BYTE_COLUMNS


def dump_controls(stream, destination):
    """Write f2.csv and exact 2352-byte source sectors to f2_sectors.bin.

    Scan every loaded track, ignoring directory extents, EOR/EOF, audio flags,
    picture assembly and command values. Match only raw Mode 2 sectors whose
    first payload byte is F2. Byte columns are a preview, not a record schema;
    the binary retains the entire sector, including both XA subheader copies.
    """
    if not stream.Streams:
        raise ValueError("No supported tracks found in CUE")
    for source in stream.Streams:
        if source.Length % RAW_SECTOR_SIZE:
            raise ValueError(f"Incomplete 2352-byte sector in {source.Filename}")

    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    total = sector_lba = 0
    sources = []
    with (output / "f2.csv").open("w", newline="", encoding="utf-8") as csv_file, \
            (output / "f2_sectors.bin").open("wb") as binary:
        writer = csv.DictWriter(csv_file, fieldnames=RECORD_COLUMNS)
        writer.writeheader()
        for stream_id, source in enumerate(stream.Streams):
            source.Stream.seek(0)
            count = 0
            sector_count = source.Length // RAW_SECTOR_SIZE
            for stream_sector in range(sector_count):
                raw = source.Stream.read(RAW_SECTOR_SIZE)
                if len(raw) != RAW_SECTOR_SIZE:
                    raise ValueError(f"Incomplete sector {stream_sector} in {source.Filename}")
                lba = sector_lba
                sector_lba += 1
                if raw[15] != 2 or raw[PAYLOAD_OFFSET] != 0xF2:
                    continue
                prefix = raw[PAYLOAD_OFFSET:PAYLOAD_OFFSET + PREFIX_SIZE]
                row = {
                    "record": total, "sector_lba": lba,
                    "stream_file": source.Filename, "stream_id": stream_id,
                    "stream_sector": stream_sector,
                    "stream_byte_offset": stream_sector * RAW_SECTOR_SIZE,
                    "raw_dump_offset": binary.tell(),
                    "payload_size": 2324 if raw[18] & 0x20 else 2048,
                    "msf_hex": raw[12:15].hex(" "),
                    "subheader_hex": raw[16:24].hex(" "),
                    "prefix_hex": prefix.hex(" "),
                }
                row.update(zip(BYTE_COLUMNS, (f"0x{byte:02X}" for byte in prefix)))
                binary.write(raw)
                writer.writerow(row)
                total += 1
                count += 1
            sources.append({
                "stream_id": stream_id, "file": source.Filename,
                "sectors_scanned": sector_count, "f2_records": count,
            })

    summary = {
        "selection": "Every Mode 2 sector with F2 at payload offset 0 (raw offset 24)",
        "sectors_scanned": sector_lba,
        "f2_records": total,
        "raw_sector_size": RAW_SECTOR_SIZE,
        "csv_prefix_size": PREFIX_SIZE,
        "streams": sources,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return output, total
