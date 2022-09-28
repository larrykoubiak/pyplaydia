from jpeg import JFIFFile
from bitbuffer import BitBuffer
from json import load
from tqdm import tqdm

def main(inputfile, ysamplingfactorv, ysamplingfactorh, index):
    with open(inputfile, "rb") as f:
        scandata = f.read()
    with open("config.json", "r") as f:
        config = load(f)
    lstdata = [scandata[idx] for idx in range(len(scandata)) if (idx % 0x800) != 0]
    buffer = BitBuffer(bytearray(lstdata))
    j = JFIFFile(dict=config)
    j.SOF.cache = {}
    j.SOF.Components["Y"].SamplingFactorV = ysamplingfactorv
    j.SOF.Components["Y"].SamplingFactorH = ysamplingfactorh
    buffer.index = index
    buffer.pos = 0
    filename = "output/test/factor_v{}_h{}/index_{:04}.png".format(ysamplingfactorv, ysamplingfactorh, index)
    try:
        j.Decode(buffer, filename)
    except Exception as err:
        print(err)

if __name__ == '__main__':
    main("output/001/frame_0015.bin",1, 2, 0x27)