from struct import unpack
from json import load

class ScanComponent():
    def __init__(self, bytes=None, dict=None):
        self.Id = None
        self.HuffmanACTable = None
        self.HuffmanDCTable = None
        if bytes is not None:
            self.FromBytes(bytes)
        elif dict is not None:
            self.FromDict(dict)

    def FromBytes(self, bytes):
        temp = unpack("BB", bytes)
        self.Id = temp[0]
        self.HuffmanACTable = temp[1] & 0xF
        self.HuffmanDCTable = temp[1] >> 4

    def FromDict(self, dict):
        self.Id = dict["Id"]
        self.HuffmanACTable = dict["HuffmanACTable"]
        self.HuffmanDCTable = dict["HuffmanDCTable"]

    def __repr__(self):
        return "Id: {} Huffman DC {} AC {}".format(
            self.Id,
            self.HuffmanDCTable,
            self.HuffmanACTable
        )

class StartOfScan():
    def __init__(self, bytes=None, filename=None):
        self.Components = {}
        if bytes is not None:
            self.FromBytes(bytes)

    def FromBytes(self, bytes):
        nbcomponents = bytes[0]
        componentkeys = ["Y","Cb","Cr"]
        for i in range(nbcomponents):
            self.Components[componentkeys[i]] = ScanComponent(bytes[1+(2*i):3+(2*i)])

    def FromJSON(self, filename):
        with open(filename, "r") as f:
            jsondic = load(f)
        for k, v in jsondic.items():
            self.Components[k] = ScanComponent(dict=v)

    def __repr__(self):
        result = "SOS"
        for k, v in self.Components.items():
            result += " Component: {} {}".format(k, str(v))
        return result