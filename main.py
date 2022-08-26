from iso9660 import ISOImage
import sys

DEFAULT_PATH = "input/Dragon Ball Z - Shin Saiyajin Zetsumetsu Keikaku - Chikyuu Hen (Japan).cue"

if __name__ == "__main__":
    cue_path = DEFAULT_PATH
    if len(sys.argv) >= 2:
        cue_path = sys.argv[1] # TODO: use optparse instead
    i = ISOImage(cue_path)
    for f in i.Files:
        print(f)
        i.ReadVideoFrames(f)
