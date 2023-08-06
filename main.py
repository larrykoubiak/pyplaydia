from iso9660 import ISOImage
import argparse
import os

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stream extractor of Playdia games")
    parser.add_argument("-c", "--cue_path", default="input/Dragon Ball Z - Shin Saiyajin Zetsumetsu Keikaku - Chikyuu Hen (Japan).cue",help="Input CUE file path")
    parser.add_argument("-d", "--destination", default="output", help="Destination folder")
    parser.add_argument("-l", "--limit", default=0, type=int, help="Limit number of files to extract (0=no limit)")
    parser.add_argument("-a", "--audio", action="store_true", help="Extract audio tracks (default=False)")
    parser.add_argument("-v", "--video", action="store_true", help="Extract video tracks (default=False)")
    parser.add_argument("-f", "--frame", action="store_true", help="Extract video frames (default=False)")

    args = parser.parse_args()
    i = ISOImage(args.cue_path)
    for f in i.Files:
        print(f)
        if args.audio:
            i.ReadAudio(f, os.path.join(args.destination,"audio"), args.limit)
        if args.video:
            i.ReadVideo(f, os.path.join(args.destination,"video"), args.limit)
        if args.frame:
            i.ReadVideoFrames(f, os.path.join(args.destination,"frames"), args.limit)
