from enum import Enum
from struct import unpack
from huffman import Huffman, BitBuffer
from idct import FIX_PRECISION, FLOAT2FIX, IDCT
from PIL import Image

def clamp(val, minval, maxval):
    return max(minval,min(maxval,val))

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
    APP0 = 0x20 # JFIF
    APP1 = 0x21 # EXIF / XMP
    APP2 = 0x22 # ICC
    APP3 = 0x23 # META
    APPC = 0x2C # Picture info / Ducky
    APPD = 0x2D # Adobe IRB
    APPE = 0x2E # Adobe
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
        self.bytesread = 0
        self.TableType = QuantizationType(bytes[self.bytesread] >> 4)
        self.Id = bytes[0] & 0x0F
        self.bytesread +=1
        self.Data = bytes[self.bytesread:self.bytesread+64]
        self.bytesread +=64
        self.reverse_zigzag = [
            0,  1,  8, 16,  9,  2,  3, 10, 
            17, 24, 32, 25, 18, 11,  4,  5,
            12, 19, 26, 33, 40, 48, 41, 34, 
            27, 20, 13,  6,  7, 14, 21, 28,
            35, 42, 49, 56, 57, 50, 43, 36, 
            29, 22, 15, 23, 30, 37, 44, 51,
            58, 59, 52, 45, 38, 31, 39, 46, 
            53, 60, 61, 54, 47, 55, 62, 63
        ]
        self.Data = self.Unzigzag(self.Data)
        self.IDCT = IDCT(self.Data)

    def Unzigzag(self, input_array):
        uz = [0] * 64
        for i in range(64):
            uz[self.reverse_zigzag[i]] = input_array[i]
        return uz

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

    @property
    def MaxV(self):
        return max(c.SamplingFactorV for c in self.Components.values())

    @property
    def MaxH(self):
        return max(c.SamplingFactorH for c in self.Components.values())

    @property
    def MCUWidth(self):
        return self.MaxH * 8
    
    @property
    def MCUHeight(self):
        return self.MaxV * 8

    @property
    def AlignedWidth(self):
        return int((self.Width + self.MCUWidth -1)/self.MCUWidth) * self.MCUWidth
    
    @property
    def AlignedHeight(self):
        return int((self.Height + self.MCUHeight -1)/self.MCUHeight) * self.MCUHeight

    @property
    def MCUColumns(self):
        return int(self.AlignedWidth / self.MCUWidth)

    @property
    def MCURows(self):
        return int(self.AlignedHeight / self.MCUHeight)

    def __repr__(self):
        result = "Precision {} Dimension {}x{}".format(self.Precision, self.Width, self.Height)
        for k, v in self.Components.items():
            result += "\n\tComponent {} {}".format(k, str(v))
        return result

class HuffmanTable():
    def __init__(self, bytes):
        self.bytesread = 0
        self.Id = bytes[self.bytesread] & 0x0F
        self.TableType = HuffmanTableType(bytes[self.bytesread] >> 4)
        self.Codes = {}
        self.Huffman = Huffman()
        self.bytesread += 1
        code = 0
        counts = []
        for i in range(16):
            counts.append(bytes[self.bytesread])
            self.bytesread += 1
        for i in range(16):
            for _ in range(counts[i]):
                self.Codes[(i+1, code)] = bytes[self.bytesread]
                code +=1
                self.bytesread += 1
            code <<= 1
        self.Huffman.FromTable(self.Codes)

    def DumpCodes(self, parent = None, code="", codes=None):
        node = self.Huffman.Root if parent is None else parent
        if parent is None:
            codes= {}
        if node.IsLeaf():
            codes[code] = node.value
        else:
            if node.left is not None:
                self.DumpCodes(node.left, code+ "0", codes)
            if node.right is not None:
                self.DumpCodes(node.right, code+ "1", codes)
        if parent is None:
            for k,v in codes.items():
                print("{};{};{};{:02X}".format(self.TableType,self.Id,k,v))
    

    def __repr__(self):
        result = "Table {:02X} Type {}".format(self.Id, self.TableType)
        for k, v in self.Codes.items():
            formatstr = "\n{:0" + str(k[0]) + "b} at length {} = {:02X}" 
            result += formatstr.format(k[1],k[0],v)
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

class YUVBuffer:
    def __init__(self, stride, height):
        self.stride = stride
        self.height = height
        self.buffer = [0] * (stride * height)
class JPEGFile():
    def __init__(self, filename=None):
        self.__app = None
        self.__sof = None
        self.__sos = None
        self.__dri = 0
        self.__quantizationtables = []
        self.DCHuffmanTables = []
        self.ACHuffmanTables = []
        self.__fs = None
        self.__flen = 0
        self.__buffers = {}
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
            elif segid == JPEGSegment.APP0:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                data = self.__fs.read(length)
                self.__app = JFIFHeader(data)
                print(self.__app)
            elif segid == JPEGSegment.DQT:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                data = self.__fs.read(length)
                bytesread = 0
                while bytesread < length:
                    table = QuantizationTable(data)
                    print(table)
                    self.__quantizationtables.append(table)
                    bytesread += table.bytesread
            elif segid == JPEGSegment.SOF0:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                data = self.__fs.read(length)
                self.__sof = StartOfFrame(data)
                print(self.__sof)
            elif segid == JPEGSegment.DHT:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                data = self.__fs.read(length)
                bytesread = 0
                while bytesread < length:
                    table = HuffmanTable(data[bytesread:])
                    if table.TableType == HuffmanTableType.DC:
                        self.DCHuffmanTables.append(table)
                    elif table.TableType == HuffmanTableType.AC:
                        self.ACHuffmanTables.append(table)
                    bytesread += table.bytesread
            elif segid == JPEGSegment.DRI:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                data = self.__fs.read(length)
                self.__dri = unpack(">H", data)[0]
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
        sof = self.__sof
        sos = self.__sos
        ## create buffers
        c: FrameComponent
        for ctype, c in self.__sof.Components.items():
            stride = int(self.__sof.AlignedWidth * c.SamplingFactorH / self.__sof.MaxH)
            height = int(self.__sof.AlignedHeight * c.SamplingFactorV / self.__sof.MaxV)
            self.__buffers[ctype] = YUVBuffer(stride, height)
        # for mcui in range(8):
        for mcui in range(sof.MCUColumns * sof.MCURows):
            component : FrameComponent
            if self.__dri > 0 and (mcui % self.__dri) == 0 and buffer.index > 0:
                for k, v in prevDCs.items():
                    prevDCs[k] = 0
                buffer.gotonextbyte()
                code = buffer.readint16()
                if (code - 0xFFD0) < 8:
                    print("hit reset {}".format(code - 0xFFD0))
                
            for ctype, sc  in sos.Components.items():
                fc : FrameComponent = sof.Components[ctype]
                for v in range(fc.SamplingFactorV):
                    for h in range(fc.SamplingFactorH):
                        ## Huffman DC Decoding
                        DCTable = self.DCHuffmanTables[sc.HuffmanDCTable]
                        lnDC = DCTable.Huffman.DecodeChar(buffer)
                        if lnDC is None:
                            break
                        temp_array = [0] * 64
                        if lnDC == 0:
                            valDC = 0
                        else:
                            valDC = buffer.readbits(lnDC)
                            if valDC < (1 << (lnDC-1)):
                                valDC = valDC - (1 << lnDC) + 1
                        valDC += prevDCs[ctype]
                        temp_array[0] = valDC
                        prevDCs[ctype] = valDC
                        ## Huffman AC Decoding
                        ACTable = self.ACHuffmanTables[sc.HuffmanACTable]
                        index = 1
                        while index < 64:
                            ## RLE decoding
                            lnAC = ACTable.Huffman.DecodeChar(buffer)
                            if lnAC is None or lnAC == 0:
                                break
                            else:
                                lnZero = lnAC >> 4
                                lnVal = lnAC & 0xF
                                valAC = buffer.readbits(lnVal)
                                if lnVal <= 0:
                                    valAC = 0
                                else:
                                    index += lnZero
                                    if valAC < (1 << (lnVal-1)):
                                        valAC = valAC - (1 << lnVal) + 1
                                    if index < 64:
                                        temp_array[index] = valAC
                            index += 1
                        qtable = self.__quantizationtables[fc.QuantizationId]
                        temp_array = qtable.Unzigzag(temp_array)
                        du = qtable.IDCT.idct2d8x8(temp_array)
                        yuvbuf: YUVBuffer = self.__buffers[ctype]
                        x = int(((mcui % sof.MCUColumns) * sof.MCUWidth + h * 8) * fc.SamplingFactorH / sof.MaxH)
                        y = int((int(mcui / sof.MCUColumns) * sof.MCUHeight + v * 8) * fc.SamplingFactorV / sof.MaxV)
                        idst = y * yuvbuf.stride + x
                        isrc = 0
                        for _ in range(8):
                            yuvbuf.buffer[idst:idst + 8] = du[isrc:isrc + 8]
                            idst += yuvbuf.stride
                            isrc += 8
        imagedata = bytearray(self.__sof.Height * self.__sof.Width * 3)
        ySrc = 0
        iDst = 0
        yBuf : YUVBuffer = self.__buffers['Y']
        cbBuf : YUVBuffer = self.__buffers['Cb']
        crBuf : YUVBuffer = self.__buffers['Cr']
        for i in range(sof.Height):
            cbY = int(i * sof.Components['Cb'].SamplingFactorV / sof.MaxV)
            crY = int(i * sof.Components['Cr'].SamplingFactorV / sof.MaxV)
            for j in range(sof.Width):
                cbX = int(j * sof.Components['Cb'].SamplingFactorH / sof.MaxH)
                crX = int(j * sof.Components['Cr'].SamplingFactorH / sof.MaxH)
                cbSrc = int(cbY * cbBuf.stride + cbX)
                crSrc = int(crY * crBuf.stride + crX)
                Y = yBuf.buffer[ySrc]
                Cb = cbBuf.buffer[cbSrc]
                Cr = crBuf.buffer[crSrc]
                Y += 128 << FIX_PRECISION
                r = clamp(int(Y + (FLOAT2FIX(1.402) * Cr >> FIX_PRECISION) >> FIX_PRECISION),0,255)
                g = clamp(int(
                        Y -(FLOAT2FIX(0.34414) * Cb >> FIX_PRECISION) - 
                        (FLOAT2FIX(0.71414) * Cr >> FIX_PRECISION) >> FIX_PRECISION)
                        ,0,255)
                b = clamp(int(Y + (FLOAT2FIX(1.772) * Cb >> FIX_PRECISION) >> FIX_PRECISION),0,255)
                imagedata[iDst] = r
                imagedata[iDst+1] = g
                imagedata[iDst+2] = b
                iDst +=3
                ySrc +=1
            ySrc -= sof.Width
            ySrc += yBuf.stride
        image = Image.frombytes("RGB", (self.__sof.Width, self.__sof.Height), bytes(imagedata))
        image.save('output/test.bmp', format="BMP")
        image.show()

        self.__fs.seek(-2, 2)


if __name__ == "__main__":
    # j = JPEGFile("input/berserk.jpg")
    j = JPEGFile("T:\\Drawings\\Aah Megami Sama\\Belldandy 01.JPG")