from jpeg.idct import IDCT
from enum import Enum

class QuantizationType(Enum):
    PRECISION8 = 0x00
    PRECISION16 = 0x01

class QuantizationTable():
    def __init__(self, bytes=None, dict=None):
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
        self.TableType = None
        self.Id = 0
        self.Data = []
        self.IDCT = None
        if bytes is not None:
            self.FromBytes(bytes)
        elif dict is not None:
            self.FromDict(dict)

    def Unzigzag(self, input_array):
        uz = [0] * 64
        for i in range(64):
            uz[self.reverse_zigzag[i]] = input_array[i]
        return uz

    def FromBytes(self, data):
        self.bytesread = 0
        self.TableType = QuantizationType(data[self.bytesread] >> 4)
        self.Id = data[0] & 0x0F
        self.bytesread +=1
        self.Data = data[self.bytesread:self.bytesread+64]
        self.bytesread +=64
        self.Data = self.Unzigzag(self.Data)
        self.IDCT = IDCT(self.Data)

    def FromDict(self, dict):
        self.Id = dict["Id"]
        self.TableType = QuantizationType(dict["TableType"])
        self.Data = dict["Table"]
        self.IDCT = IDCT(self.Data)

    def ToDict(self):
        return {
            "Id": self.Id,
            "TableType": self.TableType.value,
            "Table": self.Data
        }
 
    def __repr__(self):
        result = "Table {:02X} Type {}".format(self.Id, self.TableType) + "\n"
        for i in range(8):
            result += "".join("{: <4d}".format(b) for b in self.Data[i*8:(i*8)+8]) + "\n"
        return result