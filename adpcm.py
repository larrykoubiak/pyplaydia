from struct import unpack

K0 = [0, 960, 1840, 1568]
K1 = [0, 0, -832, -880]
sign16 = 1 << 15

class ADPCMBlock():
    def __init__(self, data):
        temp = unpack("16s112s", data)
        self.soundParameters = temp[0]
        self.soundSamples = temp[1]

    def __signExtend16(self, value):
        return (value & (sign16 - 1)) - (value & sign16)


    def ReadPCM(self, prev1, prev2):
        pcms = []
        for blk in range(4):
            for nibble in range(2):
                for sd in range(28):
                    shift = self.soundParameters[4 + (blk * 2) + nibble] & 0xF
                    if shift > 12:
                        shift = 9
                    filter = (self.soundParameters[4 + (blk * 2) + nibble] & 0x30) >> 4
                    f0 = -K0[filter]
                    f1 = -K1[filter]
                    idx = ((sd * 4) + blk)
                    adpcmsample = (self.soundSamples[idx] >> (nibble * 4)) & 0xF
                    extendedsample = self.__signExtend16(adpcmsample << 0xC) >> shift
                    result = (extendedsample << 4) - (((prev1 * f0) + (prev2 * f1)) >> 10)
                    prev2 = prev1
                    prev1 = result
                    result = result >> 4
                    result = max(-32768, min(result, 32767))
                    pcms.append(result)
        return self.UpsampleLinear(pcms), prev1, prev2
    
    def UpsampleLinear(self, pcms):
        step = 1.0 / (7.0 / 3.0)
        result = []
        stepidx = 0.0
        idx = 0
        while idx < (len(pcms)-1):
            cursample = pcms[idx]
            nextsample = pcms[idx + 1]
            sample = int(cursample + ((nextsample - cursample) * stepidx))
            result.append(sample)
            stepidx += step
            if stepidx > 1.0:
                stepidx -= 1.0
                idx += 1
        result.append(pcms[idx])
        return result