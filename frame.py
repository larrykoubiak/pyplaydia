from struct import unpack

class FrameComponent():
    def __init__(self, bytes=None, dict=None):
        self.Id = None
        self.SamplingFactorV = None
        self.SamplingFactorH = None
        self.QuantizationId = None
        if bytes is not None:
            self.FromBytes(bytes)
        elif dict is not None:
            self.FromDict(dict)

    def FromBytes(self, bytes):
        temp = unpack("BBB", bytes)
        self.Id = temp[0]
        self.SamplingFactorV = temp[1] & 0xF
        self.SamplingFactorH = temp[1] >> 4
        self.QuantizationId = temp[2]

    def FromDict(self, dict):
        self.Id = dict["Id"]
        self.SamplingFactorH = dict["SamplingFactorH"]
        self.SamplingFactorV = dict["SamplingFactorV"]
        self.QuantizationId = dict["QuantizationId"]

    def ToDict(self):
        return {
            "Id": self.Id,
            "SamplingFactorH": self.SamplingFactorH,
            "SamplingFactorV": self.SamplingFactorV,
            "QuantizationId": self.QuantizationId
        }

    def __repr__(self):
        return "Id: {} Sampling Factor {}x{} Quantization Table Id {}".format(
            self.Id,
            self.SamplingFactorH,
            self.SamplingFactorV,
            self.QuantizationId
        )

class StartOfFrame():
    def __init__(self, bytes=None, filename=None):
        self.Precision = None
        self.Height = None
        self.Width = None
        self.Components = {}
        self.cache = {}
        if bytes is not None:
            self.FromBytes(bytes)

    def FromBytes(self, bytes):
        temp = unpack(">BHHB", bytes[:6])
        self.Precision = temp[0]
        self.Height = temp[1]
        self.Width = temp[2]
        nbComponents = temp[3]
        componentkeys = ["Y","Cb","Cr"]
        for i in range(nbComponents):
            data = bytes[6+(3*i):9+(3*i)]
            self.Components[componentkeys[i]] = FrameComponent(data)

    def FromDict(self, dict):
        self.Precision = dict["Precision"]
        self.Height = dict["Height"]
        self.Width = dict["Width"]
        for k, v in dict["Components"]:
            self.Components[k] = FrameComponent(dict=v)

    def ToDict(self):
        return {
            "Precision": self.Precision,
            "Height": self.Height,
            "Width": self.Width,
            "Components": {k: v.ToDict() for k, v in self.Components.items()}
        }

    @property
    def MaxV(self):
        if "maxv" not in self.cache:
            self.cache["maxv"] = max(c.SamplingFactorV for c in self.Components.values())
        return self.cache["maxv"]

    @property
    def MaxH(self):
        if "maxh" not in self.cache:
            self.cache["maxh"] = max(c.SamplingFactorH for c in self.Components.values())
        return self.cache["maxh"]

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