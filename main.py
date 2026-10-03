from iso9660 import ISOImage
from filestream import Imagestream
from control_dump import dump_controls
import argparse
import os

def main(argv=None):
    parser = argparse.ArgumentParser(description="Stream extractor of Playdia games")
    parser.add_argument("-c", "--cue_path", help="Input CUE file path (required for extraction)")
    parser.add_argument("-d", "--destination", default="output", help="Destination folder")
    parser.add_argument("-l", "--limit", default=0, type=int, help="Limit media scenes per disc file (0=no limit; --controls always dumps all F2s)")
    parser.add_argument("-a", "--audio", action="store_true", help="Extract audio tracks (default=False)")
    parser.add_argument("-v", "--video", action="store_true", help="Export lossless PNG/PCM AVI clips (default=False)")
    parser.add_argument("-f", "--frame", action="store_true", help="Decode video frames to PNG (default=False)")
    parser.add_argument("--controls", action="store_true", help="Dump every F2 sector as raw BIN and byte CSV, without interpretation")

    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit must be zero or greater")
    if not (args.audio or args.video or args.frame or args.controls):
        parser.print_help()
        return 0
    if not args.cue_path:
        parser.error("--cue_path is required for extraction")

    if args.controls:
        print(f"Scanning {args.cue_path} for all F2 sectors...", flush=True)
        with Imagestream(args.cue_path) as stream:
            output, count = dump_controls(stream, os.path.join(args.destination, "controls"))
        print(f"Wrote {output / 'f2.csv'} ({count} F2 records)")
        print(f"Wrote {output / 'f2_sectors.bin'} (complete raw sectors)")
    if not (args.audio or args.video or args.frame):
        return 0

    with ISOImage(args.cue_path) as image:
        for record in image.Files:
            print(record)
            if args.audio:
                image.ReadAudio(record, os.path.join(args.destination, "audio"), args.limit)
            if args.video:
                image.ReadVideo(record, os.path.join(args.destination, "video"), args.limit)
            if args.frame:
                image.ReadVideoFrames(record, os.path.join(args.destination, "frames"), args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
