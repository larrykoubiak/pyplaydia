from enum import Enum, Flag
from struct import pack, unpack


class JPEGDensityUnit(Enum):
    NONE = 0x00
    INCH = 0x01
    CM = 0x02
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
class QuantizationType(Enum):
    PRECISION8 = 0x00
    PRECISION16 = 0x01
class HuffmanTableType(Enum):
    DC = 0x00
    AC = 0x01
class JPEGComponents(Enum):
    GREYSCALE = 0x01
    RGB = 0x03
    CMYK = 0x04

class JFIFHeader():
    def __init__(self, bytes):
        temp = unpack(">5sBBBHHBB", bytes[0:14])
        self.Version = "%s v%d.%d" % (temp[0][:4].decode(), temp[1], temp[2])
        self.Unit = JPEGDensityUnit(temp[3])
        self.DensityH = temp[4]
        self.DensityV = temp[5]
        self.ThumbW = temp[6]
        self.ThumbH = temp[7]
        self.Thumbdata = None
        thumblen = 3 * self.ThumbH * self.ThumbW
        if thumblen > 0:
            self.Thumbdata = bytes[14:14 + thumblen]

    def __repr__(self):
        return "{} {} {} {} Thumbnail {}x{} {}".format(
            self.Version,
            self.Unit,
            self.DensityH,
            self.DensityV,
            self.ThumbH,
            self.ThumbW,
            self.Thumbdata
        )

class QuantizationTable():
    def __init__(self, bytes):
        self.TableType = QuantizationType(bytes[0] >> 4)
        self.Id = bytes[0] & 0x0F
        self.Data = bytes[1:]

    def __repr__(self):
        result = "Table {:02X} Type {}".format(self.Id, self.TableType)
        return result

class FrameComponent():
    def __init__(self, bytes):
        temp = unpack("BBB", bytes)
        self.Id = temp[0]
        self.SamplingFactorV = temp[1] & 0xF
        self.SamplingFactorH = temp[1] >> 4
        self.QuantizationId = temp[2]

    def __repr__(self):
        return "Id: {} Sampling Factor {}x{} Quantization Table Id {}".format(
            self.Id,
            self.SamplingFactorH,
            self.SamplingFactorV,
            self.QuantizationId
        )

class StartOfFrame():
    def __init__(self, bytes):
        temp = unpack(">BHHB", bytes[:6])
        self.Precision = temp[0]
        self.Height = temp[1]
        self.Width = temp[2]
        nbComponents = temp[3]
        componentkeys = ["Y","Cb","Cr"]
        self.Components = {}
        for i in range(nbComponents):
            data = bytes[6+(3*i):9+(3*i)]
            self.Components[componentkeys[i]] = FrameComponent(data)

    def __repr__(self):
        result = "Precision {} Dimension {}x{}".format(self.Precision, self.Width, self.Height)
        for k, v in self.Components.items():
            result += "\n\tComponent {} {}".format(k, str(v))
        return result

class HuffmanTable():
    def __init__(self, bytes):
        self.Id = bytes[0] & 0x0F
        self.TableType = HuffmanTableType(bytes[0] >> 4)
        self.Codes = {}
        index = 1
        code = 0
        counts = []
        for i in range(16):
            counts.append(bytes[index])
            index += 1
        for i in range(16):
            for _ in range(counts[i]):
                self.Codes[(i+1, code)] = bytes[index]
                code +=1
                index += 1
            code <<= 1
    
    def __repr__(self):
        result = "Table {:02X} Type {}".format(self.Id, self.TableType)
        # for k, v in self.Codes.items():
        #     result += "\n{:02b} at length {} = {:02X}".format(k[1],k[0],v)
        return result

class ScanComponent():
    def __init__(self, bytes):
        temp = unpack("BB", bytes)
        self.Id = temp[0]
        self.HuffmanACTable = temp[1] & 0xF
        self.HuffmanDCTable = temp[1] >> 4

    def __repr__(self):
        return "Id: {} Huffman DC {} AC {}".format(
            self.Id,
            self.HuffmanDCTable,
            self.HuffmanACTable
        )

class StartOfScan():
    def __init__(self, bytes):
        nbcomponents = bytes[0]
        componentkeys = ["Y","Cb","Cr"]
        self.Components = {}
        for i in range(nbcomponents):
            self.Components[componentkeys[i]] = ScanComponent(bytes[1+(2*i):3+(2*i)])
    
    def __repr__(self):
        result = "SOS"
        for k, v in self.Components.items():
            result += " Component: {} {}".format(k, str(v))
        return result

class JPEGFile():
    def __init__(self, filename=None):
        self.__app = None
        self.__sof = None
        self.__sos = None
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
            if segid == JPEGSegment.SOI:
                print("Start of Image")
            elif segid == JPEGSegment.APP:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                data = self.__fs.read(length)
                self.__app = JFIFHeader(data)
                print(self.__app)
            elif segid == JPEGSegment.DQT:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                data = self.__fs.read(length)
                table = QuantizationTable(data)
                print(table)
                self.__quantizationtables.append(table)
            elif segid == JPEGSegment.SOF0:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                data = self.__fs.read(length)
                self.__sof = StartOfFrame(data)
                print(self.__sof)
            elif segid == JPEGSegment.DHT:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                data = self.__fs.read(length)
                table = HuffmanTable(data)
                print(table)
                if table.TableType == HuffmanTableType.DC:
                    self.DCHuffmanTables.append(table)
                elif table.TableType == HuffmanTableType.AC:
                    self.ACHuffmanTables.append(table)
            elif segid == JPEGSegment.SOS:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                data = self.__fs.read(length)
                self.__sos = StartOfScan(data)
                print(self.__sos)
                self.__fs.seek(-2, 2)
            elif segid == JPEGSegment.EOI:
                print("End of Image")
            else:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                print("%s size %d" % (str(segid), length))
                self.__fs.seek(length, 1)
            code = self.__fs.read(2)


if __name__ == "__main__":
    j = JPEGFile("C:\\Temp\\test.jpg")