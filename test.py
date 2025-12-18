import os
import subprocess
from json import load

import pandas as pd
from tqdm import tqdm

from iso9660 import ISOImage, TimeToLBA
from jpeg.bitbuffer import BitBuffer
from jpeg.jpeg import JFIFFile

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

def read_headers(frames_dir):
    binfiles = []
    for root, dirs, files in os.walk(frames_dir):
        for f in files:
            if f.endswith('.bin'):
                binfiles.append(os.path.join(root, f))
    headers = []
    for bf in tqdm(binfiles):
        with open(bf, 'rb') as f:
            f.seek(0x28)
            h = f.read(1)
            header = {'file': bf, 'header_28': f"0x{h[0]:02x}"}
            headers.append(header)
    df = pd.DataFrame(headers)
    outputpath = os.path.join(frames_dir, "headers_28.xlsx")
    df.to_excel(outputpath, header=True, index=False)

def view_input_test_jpeg():
    """Decode input/test.jpg with the custom JPEG decoder and open the result."""
    jpg_path = os.path.join("input", "test.jpg")
    if not os.path.exists(jpg_path):
        print(f"JPEG not found at {jpg_path}")
        return
    j = JFIFFile(jpg_path)
    if j.scandata is None:
        print("No scan data found in the JPEG file.")
        return
    output_png = os.path.join("output", "test", "test_view.png")
    os.makedirs(os.path.dirname(output_png), exist_ok=True)
    try:
        j.Decode(BitBuffer(j.scandata), output_png)
        try:
            if os.name == "nt":
                subprocess.run(["cmd", "/c", "start", "", output_png], check=False, shell=False)
            elif sys.platform == "darwin":
                subprocess.run(["open", output_png], check=False)
            else:
                subprocess.run(["xdg-open", output_png], check=False)
        except Exception:
            print(f"Decoded JPEG to {output_png}. Open it manually to view.")
        else:
            print(f"Decoded and opened {jpg_path} -> {output_png}")
    except Exception as err:
        print(f"Failed to decode/display JPEG: {err}")


if __name__ == '__main__':
    # main("output/001/frame_0015.bin",1, 2, 0x27)
    # test_patch("input/Dragon Ball Z - Shin Saiyajin Zetsumetsu Keikaku - Chikyuu Hen (Japan).cue", "input/patch.bin", "output", "DBZ_TEST", 1, 4,60, 0x28)
    # read_headers("output/MOON/frames")
    # view_input_test_jpeg()
    view_input_test_jpeg()
