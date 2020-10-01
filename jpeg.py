from enum import Enum, Flag
from struct import pack, unpack


class HuffmanTableType(Enum):
    DC = 0x00
    AC = 0x01


class JPEGSegment(Enum):
    SOF0 = 0x00
    SOF1 = 0x01
    SOF2 = 0x02
    SOF3 = 0x03
    DHT = 0x04
    SOF5 = 0X05
    SOF6 = 0x06
    SOF7 = 0x07
    JPG8 = 0x08
    SOF9 = 0x09
    SOFA = 0x0A
    SOFB = 0X0B
    SOFC = 0x0C
    SOFD = 0x0D
    SOFE = 0x0E
    SOFF = 0x0F
    RST0 = 0x10
    RST1 = 0x11
    RST2 = 0x12
    RST3 = 0x13
    RST4 = 0x14
    RST5 = 0x15
    RST6 = 0x16
    RST7 = 0x17
    SOI = 0x18
    EOI = 0x19
    SOS = 0x1A
    DQT = 0x1B
    DNL = 0x1C
    DRI = 0x1D
    DHP = 0x1E
    EXP = 0x1F
    APP = 0x20


class HuffmanTable():
    def __init__(self, bytes):
        self.Codes = {}
        index = 0
        code = 0
        counts = []
        for i in range(16):
            counts.append(bytes[index])
            index += 1
        for i in range(16):
            for j in range(counts[i]):
                self.Codes[(i+1, code)] = bytes[index]
                code +=1
                index += 1
            code <<= 1


class JPEGFile():
    def __init__(self, filename=None):
        self.__quantizationtables = []
        self.DCHuffmanTables = []
        self.ACHuffmanTables = []
        self.__fs = None
        if filename is not None:
            self.__parseFile(filename)

    def __parseFile(self, filename):
        self.__fs = open(filename, 'rb')
        code = self.__fs.read(2)
        if code[0] != 0xFF:
            print("Invalid segment")
        while code:
            segid = JPEGSegment(unpack(">H",code)[0] - 0xFFC0)
            if segid == JPEGSegment.EOI:
                print("End of Image")
            elif segid == JPEGSegment.SOI:
                print("Start of Image")
            elif segid == JPEGSegment.DHT:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                self.__parseDHT(length)
            elif segid == JPEGSegment.SOS:
                print("Start of Scan")
                self.__fs.seek(-2, 2)
            else:
                length = unpack(">H", self.__fs.read(2))[0]
                print("%s size %d" % (str(segid), length))
                self.__fs.seek(length-2, 1)
            code = self.__fs.read(2)

    def __parseDHT(self, length):
        temp = unpack("B",self.__fs.read(1))[0]
        tableid = temp & 0x0F
        tabletype = HuffmanTableType(temp >> 4)
        data = self.__fs.read(length-1)
        table = HuffmanTable(data)
        if tabletype == HuffmanTableType.DC:
            self.DCHuffmanTables.append(table)
        elif tabletype == HuffmanTableType.AC:
            self.ACHuffmanTables.append(table)
        print("Table {:02X} Type {}".format(tableid,tabletype))
        for k, v in table.Codes.items():
            print("{:02b} at length {} = {:02X}".format(k[1],k[0],v))


if __name__ == "__main__":
    j = JPEGFile("C:\\Temp\\test.jpg")