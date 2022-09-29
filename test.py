from jpeg import JFIFFile
from bitbuffer import BitBuffer
from json import load
from tqdm import tqdm
from iso9660 import ISOImage, TimeToLBA

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

def test_patch(inputcuepath, inputdatapath,  outputpath, outputname, minute, second, block, offset):
    i = ISOImage(inputcuepath)
    with open(inputdatapath, "rb") as df:
        data = df.read()
    i.PatchFrame(TimeToLBA(minute, second, block), bytes(data), offset)
    i.Write(outputpath, outputname)

if __name__ == '__main__':
    # main("output/001/frame_0015.bin",1, 2, 0x27)
    test_patch("input/Dragon Ball Z - Shin Saiyajin Zetsumetsu Keikaku - Chikyuu Hen (Japan).cue", "input/patch.bin", "output", "DBZ_TEST", 1, 4,60, 0x28)