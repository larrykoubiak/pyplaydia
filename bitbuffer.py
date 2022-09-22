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
        self.__buffer = (self.__values[self.index] >> (7 - (self.pos)))
        self.pos += 1
        if self.pos > 7:
            self.pos = 0
            if self.index < len(self.__values):
                self.index += 1
                if self.__values[self.index -1] == 0xFF and self.__values[self.index] == 0x00:
                    self.index += 1
            else:
                return None
        return self.__buffer & 0x01

    def readbits(self, nbbits):
        val = 0
        for _ in range(nbbits):
            b = self.pop()
            if b is None:
                return None
            val <<= 1
            val |= b
        return val

    def readint16(self):
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