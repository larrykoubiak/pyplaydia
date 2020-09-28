from iso9660 import ISOImage

if __name__ == "__main__":
    i = ISOImage("input/Dragon Ball Z - Shin Saiyajin Zetsumetsu Keikaku - Chikyuu Hen (Japan).cue")
    for f in i.Files:
        print(f)
        i.ReadAudio(f)