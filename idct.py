from math import cos, pi, sqrt

from sqlalchemy import table

FIX_PRECISION = 11
FLOAT2FIX = lambda x: int(x * (1 << FIX_PRECISION))

FIX_2COS_PI_4_16 = FLOAT2FIX(  2.0 * cos(pi * 4 / 16) ) ##  1.4142135623730951
FIX_2COS_PI_2_16 = FLOAT2FIX(  2.0 * cos(pi * 2 / 16) ) ##  1.8477590650225735
FIX_1COS_PI_2_16 = FLOAT2FIX(  1.0 / cos(pi * 2 / 16) ) ##  1.082392200292394
FIX_1COS_PI_6_16 = FLOAT2FIX(-(1.0 / cos(pi * 6 / 16))) ## -2.613125929752753

AAN_DCT_FACTOR = [
    1.0, 1.387039845, 1.306562965, 1.175875602,
    1.0, 0.785694958, 0.541196100, 0.275899379
]

DCT_SIZE = 8

class IDCT:
    def __init__(self, qtab):
        self.factor = [0.0] * 64
        self.qtab = [0] * 64
        for i in range(8):
            for j in range(8):
                self.factor[i * 8 + j] = 1.0 * (AAN_DCT_FACTOR[i] * AAN_DCT_FACTOR[j] / 8)
        for i in range(64):
            self.qtab[i] = FLOAT2FIX(self.factor[i] * qtab[i])

    def idct2d8x8(self, data):
        index = 0
        # unquantize
        for i in range(64):
            data[i] *= self.qtab[i]
        # pass 1 : process rows
        for _ in range(DCT_SIZE):
            if sum([b for b in data[index+1: index+7]]) == 0:
                data[index+1] = data[index]
                data[index+2] = data[index]
                data[index+3] = data[index]
                data[index+4] = data[index]
                data[index+5] = data[index]
                data[index+6] = data[index]
                data[index+7] = data[index]
                index += DCT_SIZE
                continue
            # even part
            tmp0 = data[index]
            tmp1 = data[index+2]
            tmp2 = data[index+4]
            tmp3 = data[index+6]
            
            tmp10 = tmp0 + tmp2 # phase 3
            tmp11 = tmp0 - tmp2
            
            tmp13 = tmp1 + tmp3 #phase 5 - 3
            tmp12 = tmp1 - tmp3 # 2 * c4
            tmp12 *= FIX_2COS_PI_4_16
            tmp12 >>= FIX_PRECISION
            tmp12 -= tmp13
            
            tmp0 = tmp10 + tmp13 # phase 2
            tmp3 = tmp10 - tmp13
            tmp1 = tmp11 + tmp12
            tmp2 = tmp11 - tmp12
            # odd part
            tmp4 = data[index+1]
            tmp5 = data[index+3]
            tmp6 = data[index+5]
            tmp7 = data[index+7]

            z13 = tmp6 + tmp5 # phase 6
            z10 = tmp6 - tmp5
            z11 = tmp4 + tmp7
            z12 = tmp4 - tmp7
            
            tmp7 = z11 + z13 #phase 5
            tmp11 = z11 - z13 # 2 * c4
            tmp11 *= FIX_2COS_PI_4_16
            tmp11 >>= FIX_PRECISION

            z5 = (z10 + z12) * FIX_2COS_PI_2_16 >> FIX_PRECISION   #  2 * c2
            tmp10 = (FIX_1COS_PI_2_16 * z12 >> FIX_PRECISION) - z5 #  2 * (c2 - c6)
            tmp12 = (FIX_1COS_PI_6_16 * z10 >> FIX_PRECISION) + z5 # -2 * (c2 + c6)

            tmp6 = tmp12 - tmp7 # phase 2
            tmp5 = tmp11 - tmp6
            tmp4 = tmp10 + tmp5

            data[index] = tmp0 + tmp7
            data[index+7] = tmp0 - tmp7
            data[index+1] = tmp1 + tmp6
            data[index+6] = tmp1 - tmp6
            data[index+2] = tmp2 + tmp5
            data[index+5] = tmp2 - tmp5
            data[index+4] = tmp3 + tmp4
            data[index+3] = tmp3 - tmp4

            index +=DCT_SIZE
        # pass 2 : process columns
        index = 0
        for _ in range(DCT_SIZE):
            # even part
            tmp0 = data[index + (DCT_SIZE * 0)]
            tmp1 = data[index + (DCT_SIZE * 2)]
            tmp2 = data[index + (DCT_SIZE * 4)]
            tmp3 = data[index + (DCT_SIZE * 6)]
            
            tmp10 = tmp0 + tmp2 # phase 3
            tmp11 = tmp0 - tmp2
            
            tmp13 = tmp1 + tmp3 #phase 5 - 3
            tmp12 = tmp1 - tmp3 # 2 * c4
            tmp12 *= FIX_2COS_PI_4_16
            tmp12 >>= FIX_PRECISION
            tmp12 -= tmp13
            
            tmp0 = tmp10 + tmp13 # phase 2
            tmp3 = tmp10 - tmp13
            tmp1 = tmp11 + tmp12
            tmp2 = tmp11 - tmp12
            # odd part
            tmp4 = data[index + (DCT_SIZE * 1)]
            tmp5 = data[index + (DCT_SIZE * 3)]
            tmp6 = data[index + (DCT_SIZE * 5)]
            tmp7 = data[index + (DCT_SIZE * 7)]

            z13 = tmp6 + tmp5 # phase 6
            z10 = tmp6 - tmp5
            z11 = tmp4 + tmp7
            z12 = tmp4 - tmp7
            
            tmp7 = z11 + z13 #phase 5
            tmp11 = z11 - z13 # 2 * c4
            tmp11 *= FIX_2COS_PI_4_16
            tmp11 >>= FIX_PRECISION

            z5 = (z10 + z12) * FIX_2COS_PI_2_16 >> FIX_PRECISION   #  2 * c2
            tmp10 = (FIX_1COS_PI_2_16 * z12 >> FIX_PRECISION) - z5 #  2 * (c2 - c6)
            tmp12 = (FIX_1COS_PI_6_16 * z10 >> FIX_PRECISION) + z5 # -2 * (c2 + c6)

            tmp6 = tmp12 - tmp7 # phase 2
            tmp5 = tmp11 - tmp6
            tmp4 = tmp10 + tmp5

            data[index + (DCT_SIZE * 0)] = tmp0 + tmp7
            data[index + (DCT_SIZE * 7)] = tmp0 - tmp7
            data[index + (DCT_SIZE * 1)] = tmp1 + tmp6
            data[index + (DCT_SIZE * 6)] = tmp1 - tmp6
            data[index + (DCT_SIZE * 2)] = tmp2 + tmp5
            data[index + (DCT_SIZE * 5)] = tmp2 - tmp5
            data[index + (DCT_SIZE * 4)] = tmp3 + tmp4
            data[index + (DCT_SIZE * 3)] = tmp3 - tmp4

            index +=1
        return data

if __name__ == '__main__':
    print(FIX_1COS_PI_6_16)