"""Headless, sector-streamed Playdia playback and navigation."""

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from iso9660 import ISOImage
from playdia_codec import ControlInput, ControlStream, DecodeError, Picture
from playdia_codec.adpcm import XaAudioDecoder
from sector import Submodes

from .audio import OUTPUT_CHANNELS, OUTPUT_RATE, normalize_pcm


SECTORS_PER_SECOND = 75
READ_AHEAD_TICKS = SECTORS_PER_SECOND * 2
AUDIO_CHUNK_FRAMES = OUTPUT_RATE // 4
AUDIO_CHUNK_BYTES = AUDIO_CHUNK_FRAMES * OUTPUT_CHANNELS * 2
PICTURE_START_CODE = 0x400
PICTURE_START_BITS = 19


class PlayerError(RuntimeError):
    pass


def _starts_picture(data: bytes) -> bool:
    """Whether an F1 sector begins with the Playdia picture start code."""
    if len(data) < 4 or data[0] != 0xF1:
        return False
    prefix = int.from_bytes(data[1:4], "big")
    return prefix >> (24 - PICTURE_START_BITS) == PICTURE_START_CODE


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
        """Decode this frame on demand, outside the sector-reading path."""
        try:
            return Picture.from_bytes(self.packet).decode_rgb()
        except DecodeError as exc:
            raise PlayerError(f"Could not decode picture beginning at LBA {self.lba}: {exc}") from exc


@dataclass
class Segment:
    """Mutable state for one scene, bounded by the rolling read horizon."""

    start_lba: int
    cursor_lba: int
    future_frames: deque[PlaybackFrame] = field(default_factory=deque, repr=False)
    current_frame: PlaybackFrame | None = None
    packet: bytearray = field(default_factory=bytearray, repr=False)
    packet_start: int | None = None
    audio_decoder: XaAudioDecoder | None = field(default=None, repr=False)
    audio_channel: int | None = None
    audio_staging: bytearray = field(default_factory=bytearray, repr=False)
    audio_chunks: deque[bytes] = field(default_factory=deque, repr=False)
    audio_frames: int = 0
    stop_lba: int | None = None
    duration: float | None = None

    @property
    def frames(self) -> tuple[PlaybackFrame, ...]:
        """Current and future buffered frames, in presentation order."""
        if self.current_frame is None:
            return tuple(self.future_frames)
        return (self.current_frame, *self.future_frames)

    @property
    def buffered_ticks(self) -> int:
        return self.cursor_lba - self.start_lba


@dataclass(frozen=True)
class Transition:
    source_lba: int
    input: ControlInput
    target_lba: int
    value: int


class PlaybackEngine:
    """Small streaming state machine independent from the output toolkit."""

    def __init__(self, stream, entry_lba: int):
        self.stream = stream
        self.segment = None
        self.state = PlaybackState.STOPPED
        self.playhead = 0.0
        self.generation = 0
        self.last_transition = None
        self.message = ""
        self.seek(entry_lba)

    @property
    def current_frame(self) -> PlaybackFrame | None:
        return None if self.segment is None else self.segment.current_frame

    def seek(self, lba: int):
        if not self._is_picture_target(lba):
            raise PlayerError(f"LBA {lba} is not a picture target")
        self.segment = Segment(start_lba=lba, cursor_lba=lba)
        self.playhead = 0.0
        self.state = PlaybackState.PLAYING
        self.generation += 1
        self.message = f"Playing LBA {lba}"
        self._fill_buffer()
        self._select_frame()

    def advance(self, seconds: float):
        if self.state is not PlaybackState.PLAYING or self.segment is None:
            return
        self.advance_to(self.playhead + max(0.0, seconds))

    def advance_to(self, position: float):
        """Advance to an absolute scene time, normally supplied by audio."""
        if self.state is not PlaybackState.PLAYING or self.segment is None:
            return
        self.playhead = max(self.playhead, position)
        self._fill_buffer()
        self._select_frame()
        if self.segment.duration is not None and self.playhead >= self.segment.duration:
            self._finish_segment()

    def press(self, input_value: ControlInput) -> bool:
        frame = self.current_frame
        if frame is None:
            self.message = f"Ignored {input_value.name}: no active control record"
            return False
        route = frame.control.candidate_addresses[int(input_value)]
        return self._follow(route, input_value)

    def take_audio_chunks(self) -> tuple[bytes, ...]:
        """Remove normalized output chunks produced by the rolling reader."""
        if self.segment is None:
            return ()
        chunks = tuple(self.segment.audio_chunks)
        self.segment.audio_chunks.clear()
        return chunks

    def stop(self):
        self.state = PlaybackState.STOPPED
        self.message = "Stopped"

    def close(self):
        pass

    def _fill_buffer(self):
        segment = self.segment
        if segment.stop_lba is not None:
            return
        playhead_tick = int(self.playhead * SECTORS_PER_SECOND)
        target = min(len(self.stream.Sectors), segment.start_lba + playhead_tick + READ_AHEAD_TICKS)
        while segment.cursor_lba < target and segment.stop_lba is None:
            self._read_sector(segment.cursor_lba)

    def _read_sector(self, lba: int):
        segment = self.segment
        header = self.stream.Sectors[lba]
        if header.Submode & Submodes.EOF:
            self._end_segment(lba)
            return

        if header.Submode & Submodes.Audio:
            self._read_audio_sector(lba, header)
            segment.cursor_lba += 1
            return

        sector = self.stream.ReadSector(lba)
        data = sector.Data
        if data and data[0] == 0xF1:
            if segment.packet:
                # Once synchronized, F2 terminates the picture. Compressed
                # continuation data can coincidentally match the start code.
                segment.packet.extend(data[:2048])
            elif _starts_picture(data):
                segment.packet_start = lba
                segment.packet.extend(data[:2048])
        elif data and data[0] == 0xF2 and segment.packet:
            segment.packet.extend(data[:2048])
            segment.future_frames.append(PlaybackFrame(
                lba=segment.packet_start,
                tick=segment.packet_start - segment.start_lba,
                packet=bytes(segment.packet),
                control=ControlStream.from_bytes(data[1:ControlStream.SIZE + 1]),
            ))
            segment.packet.clear()
            segment.packet_start = None

        segment.cursor_lba += 1
        if header.Submode & Submodes.EOR:
            self._end_segment(segment.cursor_lba)

    def _read_audio_sector(self, lba, header):
        segment = self.segment
        if segment.audio_channel is not None and header.Channel != segment.audio_channel:
            return
        sector = self.stream.ReadSector(lba)
        coding = sector.Coding.value
        if segment.audio_decoder is None:
            segment.audio_decoder = XaAudioDecoder(coding)
            segment.audio_channel = sector.Channel
        elif coding != segment.audio_decoder.coding:
            raise PlayerError("XA audio format changes within a playback segment")

        pcm = segment.audio_decoder.decode_sector(sector.Data)
        normalized = normalize_pcm(
            pcm, segment.audio_decoder.sample_rate, segment.audio_decoder.channels
        )
        segment.audio_frames += len(normalized) // (OUTPUT_CHANNELS * 2)
        segment.audio_staging.extend(normalized)
        while len(segment.audio_staging) >= AUDIO_CHUNK_BYTES:
            segment.audio_chunks.append(bytes(segment.audio_staging[:AUDIO_CHUNK_BYTES]))
            del segment.audio_staging[:AUDIO_CHUNK_BYTES]

    def _end_segment(self, stop_lba: int):
        segment = self.segment
        if segment.packet:
            raise PlayerError(
                f"Playback segment at LBA {segment.start_lba} ends with an incomplete picture"
            )
        if segment.audio_staging:
            segment.audio_chunks.append(bytes(segment.audio_staging))
            segment.audio_staging.clear()
        segment.stop_lba = stop_lba
        physical_duration = (stop_lba - segment.start_lba) / SECTORS_PER_SECOND
        audio_duration = segment.audio_frames / OUTPUT_RATE
        segment.duration = max(physical_duration, audio_duration)

    def _select_frame(self):
        segment = self.segment
        tick = self.playhead * SECTORS_PER_SECOND
        while segment.future_frames and segment.future_frames[0].tick <= tick:
            segment.current_frame = segment.future_frames.popleft()

    def _finish_segment(self):
        frame = self.current_frame
        if frame is None:
            self.state = PlaybackState.HOLDING
            self.message = "Holding: segment has no control record"
            return

        control = frame.control
        if control.single_picture_scene_end:
            routes = control.candidate_addresses
            route = routes[int(ControlInput.NO_INPUT)]
            # A single-picture ending does not necessarily wait for input:
            # DRAGON2's opening logo has only an onward no-input route.
            # Keep interactive/timed waits unresolved, including button slots
            # containing special values, and do not restart a self-reference.
            has_button_data = any(
                any(candidate.raw) for candidate in routes[:int(ControlInput.NO_INPUT)]
            )
            self_reference = self.segment.start_lba <= route.lba < self.segment.stop_lba
            if not has_button_data and not self_reference:
                if self._follow(route, ControlInput.NO_INPUT):
                    return
            self.state = PlaybackState.HOLDING
            self.message = "Holding final picture"
            return
        if control.multiple_picture_scene_end:
            route = control.candidate_addresses[int(ControlInput.NO_INPUT)]
            if self._follow(route, ControlInput.NO_INPUT):
                return

        self.state = PlaybackState.HOLDING
        self.message = "Holding: no automatic route"

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
        # Candidate addresses have five-sector precision and frequently land
        # on audio or in the middle of an F1...F2 packet. Match the hardware's
        # resynchronization behavior by accepting a nearby real picture start.
        stop = min(len(headers), lba + READ_AHEAD_TICKS)
        for candidate in range(lba, stop):
            header = headers[candidate]
            if header.Submode & Submodes.EOF:
                return False
            if header.Submode & Submodes.Audio:
                continue
            if _starts_picture(self.stream.ReadSector(candidate).Data):
                return True
        return False


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
