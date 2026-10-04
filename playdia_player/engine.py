"""Headless, LBA-addressed Playdia playback and navigation."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum

from iso9660 import ISOImage
from playdia_codec import ControlInput, ControlStream, DecodeError, Picture
from playdia_codec.adpcm import XaAudioDecoder
from sector import Submodes


SECTORS_PER_SECOND = 75


class PlayerError(RuntimeError):
    pass


class PlaybackState(Enum):
    PLAYING = "playing"
    HOLDING = "holding"
    STOPPED = "stopped"


@dataclass(frozen=True)
class PlaybackFrame:
    lba: int
    tick: int
    packet: bytes
    control: ControlStream

    def decode_rgb(self) -> bytes:
        """Decode this frame on demand, outside the scene-scanning path."""
        try:
            return Picture.from_bytes(self.packet).decode_rgb()
        except DecodeError as exc:
            raise PlayerError(f"Could not decode picture ending near LBA {self.lba}: {exc}") from exc


@dataclass(frozen=True)
class Segment:
    start_lba: int
    stop_lba: int
    frames: tuple[PlaybackFrame, ...]
    pcm: bytes
    sample_rate: int | None
    channels: int

    @property
    def duration(self) -> float:
        disc_duration = (self.stop_lba - self.start_lba) / SECTORS_PER_SECOND
        if self.sample_rate is None:
            return disc_duration
        sample_count = len(self.pcm) // (self.channels * 2)
        return max(disc_duration, sample_count / self.sample_rate)


@dataclass(frozen=True)
class Transition:
    source_lba: int
    input: ControlInput
    target_lba: int
    value: int


class SegmentReader:
    """Decode one physical scene beginning at an arbitrary sector."""

    def __init__(self, stream):
        self.stream = stream

    def read(self, start_lba: int) -> Segment:
        headers = self.stream.Sectors
        if not 0 <= start_lba < len(headers):
            raise PlayerError(f"LBA {start_lba} is outside the disc")

        frames = []
        packet = bytearray()
        packet_start = None
        pcm = bytearray()
        decoder = None
        audio_channel = None
        stop_lba = len(headers)

        for lba in range(start_lba, len(headers)):
            header = headers[lba]
            if header.Submode & Submodes.EOF:
                stop_lba = lba
                break

            if header.Submode & Submodes.Audio:
                if audio_channel is None or header.Channel == audio_channel:
                    sector = self.stream.ReadSector(lba)
                    coding = sector.Coding.value
                    if decoder is None:
                        decoder = XaAudioDecoder(coding)
                        audio_channel = sector.Channel
                    elif coding != decoder.coding:
                        raise PlayerError("XA audio format changes within a playback segment")
                    pcm.extend(decoder.decode_sector(sector.Data))
                continue

            sector = self.stream.ReadSector(lba)
            data = sector.Data
            if data and data[0] == 0xF1:
                if not packet:
                    packet_start = lba
                packet.extend(data[:2048])
            elif data and data[0] == 0xF2 and packet:
                packet.extend(data[:2048])
                frames.append(PlaybackFrame(
                    lba=packet_start,
                    tick=packet_start - start_lba,
                    packet=bytes(packet),
                    control=ControlStream.from_bytes(data[1:ControlStream.SIZE + 1]),
                ))
                packet.clear()
                packet_start = None

            if header.Submode & Submodes.EOR:
                stop_lba = lba + 1
                break
        else:
            stop_lba = len(headers)

        if packet:
            raise PlayerError(f"Playback segment at LBA {start_lba} ends with an incomplete picture")

        return Segment(
            start_lba=start_lba,
            stop_lba=stop_lba,
            frames=tuple(frames),
            pcm=bytes(pcm),
            sample_rate=decoder.sample_rate if decoder else None,
            channels=decoder.channels if decoder else 1,
        )


class PlaybackEngine:
    """Small state machine independent from any window or audio toolkit."""

    def __init__(self, stream, entry_lba: int):
        self.stream = stream
        self.reader = SegmentReader(stream)
        self.segment = None
        self.state = PlaybackState.STOPPED
        self.playhead = 0.0
        self.frame_index = -1
        self.generation = 0
        self.last_transition = None
        self.message = ""
        self._prefetch_executor = None
        self._prefetched_lba = None
        self._prefetched_segment = None
        self.seek(entry_lba)

    @property
    def current_frame(self) -> PlaybackFrame | None:
        if self.segment is None or self.frame_index < 0:
            return None
        return self.segment.frames[self.frame_index]

    def seek(self, lba: int):
        if self._prefetched_lba == lba and self._prefetched_segment is not None:
            segment = self._prefetched_segment.result()
        else:
            segment = self.reader.read(lba)
        self._discard_prefetch()
        self.segment = segment
        self.playhead = 0.0
        self.frame_index = -1
        self.state = PlaybackState.PLAYING
        self.generation += 1
        self.message = f"Playing LBA {lba}"
        self._select_frame()

    def advance(self, seconds: float):
        if self.state is not PlaybackState.PLAYING or self.segment is None:
            return
        self.playhead += max(0.0, seconds)
        self._select_frame()
        if self.playhead >= self.segment.duration:
            self._finish_segment()

    def press(self, input_value: ControlInput) -> bool:
        frame = self.current_frame
        if frame is None:
            self.message = f"Ignored {input_value.name}: no active control record"
            return False
        route = frame.control.candidate_addresses[int(input_value)]
        return self._follow(route, input_value)

    def stop(self):
        self.state = PlaybackState.STOPPED
        self.message = "Stopped"

    def prefetch_automatic_segment(self) -> bool:
        """Prepare a known no-input destination before the current audio ends."""
        target = self._automatic_target()
        if target is None or target == self.segment.start_lba:
            return False
        if self._prefetched_lba == target and self._prefetched_segment is not None:
            return True
        if not self._is_picture_target(target):
            return False
        self._discard_prefetch()
        if self._prefetch_executor is None:
            self._prefetch_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="playdia-segment"
            )
        self._prefetched_lba = target
        self._prefetched_segment = self._prefetch_executor.submit(self.reader.read, target)
        return True

    def close(self):
        self._discard_prefetch()
        if self._prefetch_executor is not None:
            self._prefetch_executor.shutdown(wait=True, cancel_futures=True)
            self._prefetch_executor = None

    def _select_frame(self):
        if self.segment is None:
            return
        tick = self.playhead * SECTORS_PER_SECOND
        while (
            self.frame_index + 1 < len(self.segment.frames)
            and self.segment.frames[self.frame_index + 1].tick <= tick
        ):
            self.frame_index += 1

    def _finish_segment(self):
        frame = self.current_frame
        if frame is None:
            self.state = PlaybackState.HOLDING
            self.message = "Holding: segment has no control record"
            return

        control = frame.control
        if control.single_picture_scene_end:
            self.state = PlaybackState.HOLDING
            self.message = "Holding final picture"
            return
        if control.multiple_picture_scene_end:
            route = control.candidate_addresses[int(ControlInput.NO_INPUT)]
            if self._follow(route, ControlInput.NO_INPUT):
                return

        self.state = PlaybackState.HOLDING
        self.message = "Holding: no automatic route"

    def _automatic_target(self) -> int | None:
        if self.segment is None or not self.segment.frames:
            return None
        control = self.segment.frames[-1].control
        if not control.multiple_picture_scene_end:
            return None
        route = control.candidate_addresses[int(ControlInput.NO_INPUT)]
        if route.m == route.s == route.u == 0:
            return None
        return route.lba

    def _discard_prefetch(self):
        if self._prefetched_segment is not None:
            self._prefetched_segment.cancel()
        self._prefetched_lba = None
        self._prefetched_segment = None

    def _follow(self, route, input_value: ControlInput) -> bool:
        if route.m == route.s == route.u == 0:
            self.message = f"Ignored {input_value.name}: empty or special route"
            return False
        target = route.lba
        if not self._is_picture_target(target):
            self.message = f"Ignored {input_value.name}: unresolved target LBA {target}"
            return False

        source = self.current_frame.lba if self.current_frame else self.segment.start_lba
        self.last_transition = Transition(source, input_value, target, route.fourth)
        self.seek(target)
        self.message = (
            f"{input_value.name}: LBA {source} -> {target}, value {route.fourth:02X}"
        )
        return True

    def _is_picture_target(self, lba: int) -> bool:
        headers = self.stream.Sectors
        if not 0 <= lba < len(headers):
            return False
        header = headers[lba]
        if header.Submode & (Submodes.Audio | Submodes.EOF):
            return False
        data = self.stream.ReadSector(lba).Data
        return bool(data) and data[0] == 0xF1


class DiscPlayer(PlaybackEngine):
    """Playback engine that owns an ISO image and its open track files."""

    def __init__(self, cue_path):
        self.disc = ISOImage(cue_path)
        try:
            entry_lba = self._find_entry_lba()
            super().__init__(self.disc.ImageStream, entry_lba)
        except BaseException:
            self.disc.close()
            raise

    def _find_entry_lba(self) -> int:
        stream = self.disc.ImageStream
        for record in self.disc.Files:
            lba = record.ExtentLocation
            if not 0 <= lba < len(stream.Sectors):
                continue
            header = stream.Sectors[lba]
            if header.Submode & (Submodes.Audio | Submodes.EOF):
                continue
            data = stream.ReadSector(lba).Data
            if data and data[0] == 0xF1:
                return lba
        raise PlayerError("No playable F1 stream was found in the ISO file table")

    def close(self):
        super().close()
        self.disc.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
