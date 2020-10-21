from enum import Enum, Flag
from struct import pack, unpack
from huffman import Huffman, BitBuffer
import numpy as np
from scipy.fftpack import idct
from PIL import Image
from math import cos, pi, sqrt

REVERSE_ZIGZAG = [
    0,  1,  8, 16,  9,  2,  3, 10, 
    17, 24, 32, 25, 18, 11,  4,  5,
    12, 19, 26, 33, 40, 48, 41, 34, 
    27, 20, 13,  6,  7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36, 
    29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46, 
    53, 60, 61, 54, 47, 55, 62, 63
]

REVERSE_ZIGZAG_M = [
    (0,0),
    (0,1), (1,0),         
    (2,0), (1,1), (0,2),
    (0,3), (1,2), (2,1), (3,0),
    (4,0), (3,1), (2,2), (1,3), (0,4),
    (0,5), (1,4), (2,3), (3,2), (4,1), (5,0),
    (6,0), (5,1), (4,2), (3,3), (2,4), (1,5), (0,6),
    (0,7), (1,6), (2,5), (3,4), (4,3), (5,2), (6,1), (7,0),
    (7,1), (6,2), (5,3), (4,4), (3,5), (2,6), (1,7),
    (2,7), (3,6), (4,5), (5,4), (6,3), (7,2),
    (7,3), (6,4), (5,5), (4,6), (3,7),
    (4,7), (5,6), (6,5), (7,4),
    (7,5), (6,6), (5,7),
    (6,7), (7,6),
    (7,7)
]

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
    COM = 0x3E
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

    def Unquantize(self, input_array):
        for i in range(64):
            input_array[i] *= self.Data[i]
        return input_array

    def __repr__(self):
        result = "Table {:02X} Type {}".format(self.Id, self.TableType) + "\n"
        for i in range(8):
            result += "".join("{: <4d}".format(b) for b in self.Data[i*8:(i*8)+8]) + "\n"
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
        self.Huffman = Huffman()
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
        self.Huffman.FromTable(self.Codes)
        # self.Huffman.DrawTree(filename="{}_{}".format(self.TableType, self.Id))
    
    def __repr__(self):
        result = "Table {:02X} Type {}".format(self.Id, self.TableType)
        # for k, v in self.Codes.items():
        #     formatstr = "\n{:0" + str(k[0]) + "b} at length {} = {:02X}" 
        #     result += formatstr.format(k[1],k[0],v)
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
        self.__flen = 0
        if filename is not None:
            self.__parseFile(filename)

    def __parseFile(self, filename):
        self.__fs = open(filename, 'rb')
        self.__fs.seek(0,2)
        self.__flen = self.__fs.tell()
        self.__fs.seek(0,0)
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
                self.Decode()                
            elif segid == JPEGSegment.EOI:
                print("End of Image")
            else:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                print("%s size %d" % (str(segid), length))
                self.__fs.seek(length, 1)
            code = self.__fs.read(2)
    
    def Decode(self):
        datalength = self.__flen - self.__fs.tell() - 2
        data = self.__fs.read(datalength)
        buffer = BitBuffer(data)
        prevDCs = {t: 0 for t in self.__sos.Components}
        MCUs = []
        while not buffer.EOF:
            MCU = {}
            for ctype, component in self.__sos.Components.items():
                ## Huffman DC Decoding
                DCTable = self.DCHuffmanTables[component.HuffmanDCTable]
                lnDC = DCTable.Huffman.DecodeChar(buffer)
                if lnDC is None:
                    break
                temp_array = [0] * 64
                if lnDC == 0:
                    valDC = 0
                else:
                    valDC = buffer.readbits(lnDC)
                    if valDC & (1 << (lnDC-1)) == 0:
                        valDC = valDC - (1 << lnDC)
                valDC += prevDCs[ctype]
                temp_array[0] = valDC
                prevDCs[ctype] = valDC
                ## Huffman AC Decoding
                ACTable = self.ACHuffmanTables[component.HuffmanACTable]
                lnAC = ACTable.Huffman.DecodeChar(buffer)
                index = 0
                while lnAC != 0 and lnAC is not None:
                    ## RLE decoding
                    lnZero = lnAC >> 4
                    lnVal = lnAC & 0xF
                    index += lnZero
                    if index > 62:
                        break
                    if lnVal != 0:
                        valAC = buffer.readbits(lnVal)
                        temp_array[index+1] = valAC
                    index += 1
                    lnAC = ACTable.Huffman.DecodeChar(buffer)
                qtable = self.__quantizationtables[self.__sof.Components[ctype].QuantizationId]
                unquantized = qtable.Unquantize(temp_array)
                m = np.array([0] * 64).reshape(8, 8)
                for i in range(64):
                    coords = REVERSE_ZIGZAG_M[i]
                    m[coords[0]][coords[1]] = unquantized[i]
                idct_coeffs = np.array([0] * 64).reshape(8, 8)
                for y in range(8):
                    for x in range(8):
                        sum = 0.0
                        for u in range(8):
                            for v in range(8):
                                Cu = (1.0 / sqrt(2.0)) if u == 0 else 1.0
                                Cv =  (1.0 / sqrt(2.0)) if v == 0 else 1.0
                                sum += Cu * Cv * m[u][v] * cos(
                                    (2 * x + 1) * u * pi / 16.0) * cos(
                                    (2 * y + 1) * v * pi / 16.0)
                        idct_coeffs[y][x] = 0.25 * sum
                idct_coeffs += 128
                MCU[ctype] = idct_coeffs
            if MCU:
                MCUs.append(MCU)
        imagedata = bytearray()
        for y in range(self.__sof.Height):
            for x in range(self.__sof.Width):
                mx = x // 8
                my = y // 8
                mcuID = int((my * (self.__sof.Width / 8)) + mx)
                m = MCUs[mcuID]
                dx = x % 8
                dy = y % 8
                i = (dy * 8) + dx
                Y, Cb, Cr = (m['Y'][dy][dx], m['Cb'][dy][dx], m['Cr'][dy][dx])
                r = max(0,min(int(Y + 1.402 * (1.0 * Cr - 128.0)),255))
                g = max(0,min(int(Y - 0.344136 * ( 1.0 * Cb  - 128.0) - 0.714136 * ( 1.0 * Cr - 128.0)),255))
                b = max(0,min(int(Y + 1.772 * ( 1.0 * Cb  - 128.0)),255))
                imagedata.append(r)
                imagedata.append(g)
                imagedata.append(b)
        image = Image.frombytes("RGB", (self.__sof.Width, self.__sof.Height), bytes(imagedata))
        image.save('output/test.bmp', format="BMP")
        image.show()

        self.__fs.seek(-2, 2)


if __name__ == "__main__":
    j = JPEGFile("input/test2.jpg")