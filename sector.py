from enum import Enum, Flag, auto
from struct import pack, unpack


class Submodes(Flag):
    EOR = auto()
    Video = auto()
    Audio = auto()
    Data = auto()
    Trigger = auto()
    Form = auto()
    RTS = auto()
    EOF = auto()

class Codings(Flag):
    Stereo = 0x01
    LowSampleRate = 0x04
    EightBit = 0x10

class Sector():
    def __init__(self, data, filestreamid, filestreamoffset):
        self.__filestreamid = filestreamid
        self.__filestreamoffset = filestreamoffset
        header = unpack("<12sBBBBBBBBI", data)
        self.__syncpattern = header[0]
        self.__minute = header[1]
        self.__second = header[2]
        self.__block = header[3]
        self.__mode = header[4]
        self.__filenumber = header[5]
        self.__channel = header[6]
        self.__submode = Submodes(header[7])
        self.__coding = Codings(header[8])
        self.__data = None

    @property
    def FileStreamId(self):
        return self.__filestreamid

    @property
    def FileStreamOffset(self):
        return self.__filestreamoffset

    @property
    def SyncPattern(self):
        return self.__syncpattern

    @property
    def Minute(self):
        return (self.__minute & 0xF + (10 * (self.__minute >> 4)))

    @property
    def Second(self):
        return (self.__second & 0xF + (10 * (self.__second >> 4)))

    @property
    def Block(self):
        return (self.__block & 0xF + (10 * (self.__block >> 4)))

    @property
    def Mode(self):
        return self.__mode

    @property
    def FileNumber(self):
        return self.__filenumber

    @property
    def Channel(self):
        return self.__channel

    @property
    def Submode(self):
        return self.__submode

    @property
    def Coding(self):
        return self.__coding

    @property
    def Data(self):
        return self.__data

    @Data.setter
    def Data(self, value):
        self.__data = value

    def __repr__(self):
        formatstr = '<Sector Mode {} File {} Channel {} {} {}>'
        result = formatstr.format(
            self.__mode,
            self.__filenumber,
            self.__channel,
            self.__submode,
            self.__coding
        )
        return result
