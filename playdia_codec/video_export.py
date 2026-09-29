"""Export a physical disc scene as lossless PNG/PCM AVI, with sector timing."""

from pathlib import Path
import tempfile

from tqdm import tqdm

from sector import Submodes

from .avi import PngAviWriter
from .codec import Picture, DecodeError
from .adpcm import XaAudioDecoder

SECTORS_PER_SECOND = 75


def export_scene(stream, start, stop, destination):
    """Export sectors [start, stop), returning the number of source pictures.

    Video packet starts supply 1/75-second timestamps. PCM starts at clip
    time zero, as in the WAV extractor. Extra audio at the record boundary is
    retained by holding the last picture. No interactive jumps are followed.
    """
    with tempfile.TemporaryFile() as images, tempfile.TemporaryFile() as audio:
        frames = []
        packet = bytearray()
        packet_start = None
        previous_packet = None
        png_reference = None
        decoder = None
        audio_channel = None
        for sector_id in tqdm(range(start, stop), desc=Path(destination).name, unit="sector", leave=False):
            header = stream.Sectors[sector_id]
            if header.Submode & Submodes.Audio:
                if audio_channel is not None and header.Channel != audio_channel:
                    continue
                sector = stream.ReadSector(sector_id)
                coding = sector.Coding.value
                if decoder is None:
                    decoder = XaAudioDecoder(coding)
                    audio_channel = sector.Channel
                elif coding != decoder.coding:
                    raise ValueError("XA audio format changes within a scene")
                audio.write(decoder.decode_sector(sector.Data))
                continue

            sector = stream.ReadSector(sector_id)
            data = sector.Data
            if data[0] == 0xF1:
                if not packet:
                    packet_start = sector_id
                packet.extend(data[:2048])
            elif data[0] == 0xF2 and packet:
                packet.extend(data[:2048])
                if packet != previous_packet:
                    try:
                        picture = Picture.from_bytes(packet)
                    except DecodeError as exc:
                        raise DecodeError(f"Sector {sector_id}: {exc}", bit=exc.bit, row=exc.row, block=exc.block) from exc
                    offset = images.tell()
                    picture.to_image().save(images, format="PNG")
                    png_reference = (offset, images.tell() - offset)
                    previous_packet = bytes(packet)
                frames.append((packet_start, *png_reference))
                packet.clear()
        if packet:
            raise DecodeError("Scene ends with an incomplete picture")
        if not frames:
            return 0

        origin = frames[0][0]
        ticks = stop - origin
        audio_size = audio.tell()
        sample_rate = decoder.sample_rate if decoder else None
        channels = decoder.channels if decoder else 1
        sample_count = audio_size // (channels * 2)
        if sample_rate:
            ticks = max(ticks, (sample_count * SECTORS_PER_SECOND + sample_rate - 1) // sample_rate)
        audio.seek(0)
        frame_index = 0
        last_reference = None
        png = None
        with PngAviWriter(
            Path(destination), Picture.width, Picture.height,
            fps=SECTORS_PER_SECOND, sample_rate=sample_rate, channels=channels,
        ) as avi:
            for tick in range(ticks):
                while frame_index + 1 < len(frames) and frames[frame_index + 1][0] - origin <= tick:
                    frame_index += 1
                reference = frames[frame_index][1:]
                changed = reference != last_reference
                if changed:
                    offset, length = reference
                    images.seek(offset)
                    png = images.read(length)
                    last_reference = reference
                # A real final frame anchors the end timestamp, including for
                # silent still-image scenes, when players skip empty chunks.
                avi.write_video(png if changed or tick == ticks - 1 else None)
                if sample_rate:
                    audio_end = min(sample_count, (tick + 1) * sample_rate // SECTORS_PER_SECOND)
                    samples = audio_end - avi.audio_samples
                    avi.write_audio(audio.read(samples * channels * 2))
        return len(frames)
