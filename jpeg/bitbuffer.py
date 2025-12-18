from struct import unpack

class BitBuffer:
    def __init__(self, values=None):
        self.__values = bytearray() if values is None else values
        self.__buffer = 0
        self.pos = 0
        self.index = 0

    def push(self, bit):
        self.__buffer <<= 1
        self.__buffer |= bit
        self.pos += 1
        if self.pos == 8:
            self.__values.append(self.__buffer)
            if self.__buffer == 0xFF:
                self.__values.append(0x00)
            self.__buffer = 0
            self.pos = 0
    
    def pop(self):
        if self.index >= len(self.__values):
            return None
        vals = self.__values
        idx = self.index
        pos = self.pos
        bit = (vals[idx] >> (7 - pos)) & 0x01
        pos += 1
        if pos > 7:
            pos = 0
            idx += 1
            # Skip stuffed 0x00 after a 0xFF marker byte when present.
            if (
                idx < len(vals)
                and vals[idx - 1] == 0xFF
                and vals[idx] == 0x00
            ):
                idx += 1
        self.index = idx
        self.pos = pos
        return bit

    def readbits(self, nbbits):
        vals = self.__values
        idx = self.index
        pos = self.pos
        out = 0
        bits_left = nbbits
        while bits_left > 0:
            if idx >= len(vals):
                return None
            remaining_in_byte = 8 - pos
            take = remaining_in_byte if bits_left >= remaining_in_byte else bits_left
            shift = remaining_in_byte - take
            out = (out << take) | ((vals[idx] >> shift) & ((1 << take) - 1))
            pos += take
            bits_left -= take
            if pos == 8:
                pos = 0
                idx += 1
                if (
                    idx < len(vals)
                    and vals[idx - 1] == 0xFF
                    and vals[idx] == 0x00
                ):
                    idx += 1
        self.index = idx
        self.pos = pos
        return out

    def readint16(self):
        if self.index + 2 > len(self.__values):
            return None
        data = self.__values[self.index:self.index + 2]
        val = unpack(">H", data)[0]
        self.index += 2
        return val

    def gotonextbyte(self):
        if self.pos != 0:
            self.pos = 0
            self.index += 1

    @property
    def EOF(self):
        return self.index >= len(self.__values)
    
    @property
    def Values(self):
        values = self.__values
        if self.pos > 0:
            buffer = self.__buffer << (8 - self.pos)
            # buffer |= (0xff >> self.__pos)
            values.append(buffer)
        return values

    @Values.setter
    def Values(self, value):
        self.__values = value
