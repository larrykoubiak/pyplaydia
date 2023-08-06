from enum import Enum
from struct import unpack
from jpeg.bitbuffer import BitBuffer
from jpeg.idct import FIX_PRECISION, FLOAT2FIX
from jpeg.quantization import QuantizationTable, QuantizationType
from jpeg.huffman import Huffman, HuffmanTableType
from jpeg.frame import StartOfFrame, FrameComponent
from jpeg.scan import StartOfScan, ScanComponent
from PIL import Image
import logging
import os

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

class JPEGComponents(Enum):
    GREYSCALE = 0x01
    RGB = 0x03
    CMYK = 0x04

class JFIFHeader():
    def __init__(self, bytes=None, dict=None):
        self.Version = None
        self.Unit = None
        self.DensityH = None
        self.DensityV = None
        self.ThumbW = None
        self.ThumbH = None
        self.Thumbdata = None
        if bytes is not None:
            self.FromBytes(bytes)

    def FromBytes(self, bytes):
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

    def FromDict(self, dict):
        self.Version = dict["Version"]
        self.Unit = JPEGDensityUnit(dict["Unit"])
        self.DensityH = dict["DensityH"]
        self.DensityV = dict["DensityV"]
        self.ThumbW = dict["ThumbW"]
        self.ThumbH = dict["ThumbH"]
        self.Thumbdata = dict["ThumbData"]

    def ToDict(self):
        return {
            "Version": self.Version,
            "Unit": self.Unit.value,
            "DensityH": self.DensityH,
            "DensityV": self.DensityV,
            "ThumbW": self.ThumbW,
            "ThumbH": self.ThumbH,
            "Thumbdata": self.Thumbdata
        }

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

class YUVBuffer:
    def __init__(self, stride, height):
        self.stride = stride
        self.height = height
        self.buffer = [0] * (stride * height)
class JFIFFile():
    def __init__(self, filename=None, dict=None):
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
        self.__scandata = None
        if filename is not None:
            self.FromFile(filename)
        elif dict is not None:
            self.FromDict(dict)

    @property
    def APP(self):
        return self.__app

    @property
    def DQT(self):
        return self.__quantizationtables

    @property
    def SOF(self):
        return self.__sof

    @property
    def SOS(self):
        return self.__sos

    def FromFile(self, filename):
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
            elif segid == JPEGSegment.DQT:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                data = self.__fs.read(length)
                bytesread = 0
                while bytesread < length:
                    table = QuantizationTable(data)
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
                    table = Huffman(data[bytesread:])
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
                scanlength = self.__flen - self.__fs.tell() - 2
                self.scandata = self.__fs.read(scanlength)
            elif segid == JPEGSegment.EOI:
                print("End of Image")
            else:
                length = unpack(">H", self.__fs.read(2))[0] - 2
                print("%s size %d" % (str(segid), length))
                self.__fs.seek(length, 1)
            code = self.__fs.read(2)
    
    def FromDict(self, dict):
        self.__app = JFIFHeader(dict=dict["APP0"])
        for h in dict["DHT"]["DC"]:
            self.DCHuffmanTables.append(Huffman(dict=h))
        for h in dict["DHT"]["AC"]:
            self.ACHuffmanTables.append(Huffman(dict=h))
        for q in dict["DQT"]:
            self.__quantizationtables.append(QuantizationTable(dict=q))
        self.__dri = dict["DRI"]
        self.__sof = StartOfFrame(dict=dict["SOF"])
        self.__sos = StartOfScan(dict=dict["SOS"])

    def ToDict(self):
        return {
            "APP0": self.__app.ToDict(),
            "DHT": {
                "DC": [h.ToDict() for h in self.DCHuffmanTables],
                "AC": [h.ToDict() for h in self.ACHuffmanTables]
            },
            "DQT": [q.ToDict() for q in self.__quantizationtables],
            "DRI": self.__dri,
            "SOF": self.__sof.ToDict(),
            "SOS": self.__sos.ToDict()
        }

    def Decode(self, buffer, filename=None):
        outputfolder = os.path.dirname(filename)
        if not os.path.exists(outputfolder):
            os.makedirs(outputfolder, exist_ok=True)
        log = logging.getLogger()
        log.setLevel(logging.DEBUG)
        logpath = filename.replace(".png",".log")
        filelog = logging.FileHandler(logpath, "w", encoding="utf-8")
        filelog.setLevel(logging.DEBUG)
        log.addHandler(filelog)
        prevDCs = {t: 0 for t in self.__sos.Components}
        sof = self.__sof
        sos = self.__sos
        maxh = self.__sof.MaxH
        maxv = self.__sof.MaxV
        ## create buffers
        c: FrameComponent
        for ctype, c in self.__sof.Components.items():
            stride = int(self.__sof.AlignedWidth * c.SamplingFactorH / maxh)
            height = int(self.__sof.AlignedHeight * c.SamplingFactorV / maxv)
            self.__buffers[ctype] = YUVBuffer(stride, height)
        totalmcu = sof.MCUColumns * sof.MCURows
        for mcui in range(totalmcu):
            log.info("*" * 48 + "\nMCU {}".format(mcui))
            if self.__dri > 0 and (mcui % self.__dri) == 0 and buffer.index > 0:
                for k, v in prevDCs.items():
                    prevDCs[k] = 0
                buffer.gotonextbyte()
                code = buffer.readint16()
                if (code - 0xFFD0) < 8:
                    log.info("hit reset {}".format(code - 0xFFD0))
            for ctype, sc  in sos.Components.items():
                log.info("\t" + "-" * 40 + "\n\tComponent {}".format(ctype))
                fc : FrameComponent = sof.Components[ctype]
                for v in range(fc.SamplingFactorV):
                    for h in range(fc.SamplingFactorH):
                        log.info("\t\t" + "v: {} h: {} start index: {:04X} bit: {}".format(v, h, buffer.index, buffer.pos))
                        ## Huffman DC Decoding
                        DCTable = self.DCHuffmanTables[sc.HuffmanDCTable]
                        fmtstr = "\t\t\tlnDC code: {:>16} val: {:6} prevDC: {:5} DCVal: {:5} DCbits: {:>16} DC: {:6}"
                        lnDC, code = DCTable.DecodeChar(buffer)
                        if lnDC is None:
                            break
                        temp_array = [0] * 64
                        if lnDC == 0:
                            valDC = 0
                            unsignedDC ="0"
                        else:
                            valDC = buffer.readbits(lnDC)
                            unsignedDC = "{:016b}".format(valDC)[-lnDC:]
                            if valDC < (1 << (lnDC-1)):
                                valDC = valDC - (1 << lnDC) + 1
                        log.debug(fmtstr.format(code, lnDC, prevDCs[ctype], valDC, unsignedDC , valDC + prevDCs[ctype]))
                        valDC += prevDCs[ctype]
                        temp_array[0] = valDC
                        prevDCs[ctype] = valDC
                        ## Huffman AC Decoding
                        ACTable = self.ACHuffmanTables[sc.HuffmanACTable]
                        index = 1
                        fmtstr = "\t\t\tlnAC code: {:>16} val: {:6} lnZero: {:5} lnVal: {:5} ACbits: {:>16} AC: {:6}"
                        while index < 64:
                            ## RLE decoding
                            lnAC, code = ACTable.DecodeChar(buffer)
                            if lnAC is None or lnAC == 0:
                                log.debug(fmtstr.format(code, 0, 0, 0, "0", 0))
                                break
                            else:
                                lnZero = lnAC >> 4
                                lnVal = lnAC & 0xF
                                if lnVal <= 0:
                                    valAC = 0
                                else:
                                    valAC = buffer.readbits(lnVal)
                                    unsignedAC = "{:016b}".format(valAC)[-lnVal:]
                                    index += lnZero
                                    if valAC < (1 << (lnVal-1)):
                                        valAC = valAC - (1 << lnVal) + 1
                                    if index < 64:
                                        temp_array[index] = valAC
                                log.debug(fmtstr.format(code, lnAC, lnZero, lnVal, unsignedAC, valAC))
                            index += 1
                        qtable = self.__quantizationtables[fc.QuantizationId]
                        uz = qtable.Unzigzag(temp_array)
                        qu = uz[:]
                        for i in range(64):
                            qu[i] = (qu[i] * qtable.IDCT.qtab[i]) >> FIX_PRECISION
                        du = qtable.IDCT.idct2d8x8(uz[:])
                        logstr= "\t\t\t " + "_" * 171 + " \n"
                        logstr+= "\t\t\t| {:40} | {:40} | {:40} | {:40} |\n".format("before zigzag","after zigzag", "unquantized", "idct")
                        logstr+= "\t\t\t|{:42}|{:42}|{:42}|{:42}|\n".format("-" * 42,"-" * 42,"-" * 42,"-" * 42)
                        for y in range(8):
                            logstr+= "\t\t\t| {:40} | {:40} | {:40} | {:40} |\n".format(
                                "".join(["{:5}".format(temp_array[(y * 8) + x]) for x in range(8)]),
                                "".join(["{:5}".format(uz[(y * 8) + x]) for x in range(8)]),
                                "".join(["{:5}".format(qu[(y * 8) + x]) for x in range(8)]),
                                "".join(["{:5}".format(du[(y * 8) + x] >> FIX_PRECISION) for x in range(8)]),
                            )
                        logstr+= "\t\t\t|{:42}|{:42}|{:42}|{:42}|\n".format("_" * 41,"_" * 42,"_" * 42,"_" * 42)
                        log.info(logstr)
                        yuvbuf: YUVBuffer = self.__buffers[ctype]
                        x = int(((mcui % sof.MCUColumns) * sof.MCUWidth + h * 8) * fc.SamplingFactorH / maxh)
                        y = int((int(mcui / sof.MCUColumns) * sof.MCUHeight + v * 8) * fc.SamplingFactorV / maxv)
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
            cbY = int(i * sof.Components['Cb'].SamplingFactorV / maxv)
            crY = int(i * sof.Components['Cr'].SamplingFactorV / maxv)
            for j in range(sof.Width):
                cbX = int(j * sof.Components['Cb'].SamplingFactorH / maxh)
                crX = int(j * sof.Components['Cr'].SamplingFactorH / maxh)
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
        image.save(filename)
        for handler in log.handlers[:]:
            log.removeHandler(handler)

if __name__ == "__main__":
    from json import dump
    j = JFIFFile("input/test.jpg")
    j.Decode(BitBuffer(j.scandata),"output/test.png")
    with open("input/config.json", "w") as f:
        dump(j.ToDict(), f, indent=4)
