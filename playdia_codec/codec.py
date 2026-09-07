from dataclasses import dataclass, asdict
from pathlib import Path
from bitstring import BitStream, BitArray, Bits
from typing import ClassVar
from enum import IntEnum
import re

class StreamType(IntEnum):
    VIDEO = 0xF1
    TIMING = 0xF2

SECTOR_SIZE = 0x800
F2_PAYLOAD_SIZE = 0x22
ROW_TERMINATOR = Bits(int=33, length=14)
FRAME_RE = re.compile(r"^frame_(\d+)\.bin$")

@dataclass
class PictureHeader:
    PSC: ClassVar[Bits] = Bits(uint=0x400, length=19)
    ptype: int
    qbs: int
    factor: int
    quant_y: bytes
    quant_c: bytes
    pos: int

    @classmethod
    def read(cls, stream: BitStream) -> "PictureHeader":
        pos = stream.pos
        psc = stream.read(19)
        if psc != cls.PSC:
            raise ValueError(f"Invalid picture start code: {psc.bin}")
        return cls(
            ptype=stream.read(3).uint,
            qbs=stream.read(2).uint,
            factor=stream.read(8).uint,
            quant_y=stream.read(128).bytes,
            quant_c=stream.read(128).bytes,
            pos = pos
        )

    def __repr__(self):
        return f"{self.ptype=} {self.qbs=} {self.factor=}\n{list(self.quant_y)=}\n{list(self.quant_c)=}"

@dataclass
class LMB:
    LMBSC: ClassVar[Bits] = Bits(uint=0x20, length=14)
    DCSC: ClassVar[Bits] = Bits(uint=0x80, length=10)
    lmbn: int
    dcseed: int
    pos: int
    data: Bits

    @classmethod
    def read(cls, stream: BitStream) -> "LMB":
        pos = stream.pos
        lmbsc = stream.read(14)
        if lmbsc != cls.LMBSC:
            raise ValueError(f"Invalid LMB start code. {lmbsc.bin}")
        lmbn = stream.read(5).uint
        dcsc = stream.read(10)
        if dcsc != cls.DCSC:
            raise ValueError(f"Invalid DCSC found {dcsc.bin}")
        dcseed = stream.read(10).int
        data_start = stream.pos
        find_next_row = cls.LMBSC + Bits(uint=lmbn+1, length=5) + cls.DCSC
        next_offset = stream.find(find_next_row, start=data_start+ (186*2))
        if next_offset:
            next_pos = next_offset[0]
        else:
            terminator = stream.find(ROW_TERMINATOR,start=data_start+ (186*2))
            if not terminator:
                raise ValueError(f"Couldn't find end of row {row_id}")
            next_pos = terminator[0]
        data = stream[data_start:next_pos]
        stream.pos = next_pos
        return cls(
            lmbn= lmbn,
            dcseed=dcseed,
            pos=pos,
            data=data
        )

    @property
    def byte_offset(self):
        return self.pos // 8

    @property
    def bit_offset(self):
        return self.pos % 8

    def __repr__(self):
        return f"{self.lmbn=} {self.byte_offset=:04X} {self.bit_offset=} {len(self.data.bin)=}\n{self.data.bin}"

class VideoStream:
    def __init__(self):
        self.stream = BitStream()
        self.header: PictureHeader = None
        self.rows = []

    def __repr__(self):
        return f"{self.stream.bin}"

    def parse_rows(self):
        self.stream.pos = 0
        self.header = PictureHeader.read(self.stream)
        for _ in range(26):
            self.rows.append(LMB.read(self.stream))


class TimingStream:
    def __init__(self):
        self.stream = BitStream()
    def __repr__(self):
        return f"{self.stream.bin}"

class Picture:
    file: Path
    video_stream: VideoStream
    timing_stream: TimingStream
    def __init__(self, path_str):
        self.file = Path(path_str)
        self.video_stream = VideoStream()
        self.timing_stream = TimingStream()
        self.read_sectors()
        self.video_stream.parse_rows()
    
    def read_sectors(self):
        data = self.file.read_bytes()
        nb_sectors = len(data) // SECTOR_SIZE
        for sector_id in range(nb_sectors):
            start = sector_id * SECTOR_SIZE
            sector_type = StreamType(data[start])
            if sector_type == StreamType.VIDEO:
                sector_data = data[start+1:start + SECTOR_SIZE]
                self.video_stream.stream.append(bytearray(sector_data))
            elif sector_type == StreamType.TIMING:
                timing_data = data[start+1:start+F2_PAYLOAD_SIZE+1]
                video_data = data[start+F2_PAYLOAD_SIZE+1:start + SECTOR_SIZE]
                self.timing_stream.stream.append(bytearray(timing_data))
                self.video_stream.stream.append(bytearray(video_data))

    def to_dict(self)->dict:
        return {
            "frame_id": self.frame_id,
            "ptype": self.video_stream.header.ptype,
            "qbs": self.video_stream.header.qbs,
            "factor": self.video_stream.header.factor
        }

    @property
    def frame_id(self):
        match = FRAME_RE.match(self.file.name)
        if not match:
            return None
        return int(match.group(1))

    def __repr__(self):
        return f"video:{self.file.parent.name} frame: {self.file.stem}"

if  __name__ == '__main__':
    f = Picture('output/frames/001/frame_0013.bin')
    print(asdict(f.video_stream.header))
    # for r in f.video_stream.rows:
    #     print(r)