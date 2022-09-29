import os
import re
from sector import Sector, Submodes
from pathlib import Path


class Filestream():
    def __init__(self, filepath=None):
        self.__filename = os.path.basename(filepath)
        self.__stream = open(filepath,'rb')
        self.__stream.seek(0, 2)
        self.__length = self.__stream.tell()
        self.__stream.seek(0,0)

    @property
    def Filename(self):
        return self.__filename

    @property
    def Stream(self):
        return self.__stream

    @property
    def Length(self):
        return self.__length

    def __repr__(self):
        return "Stream: " + str(self.__stream) + " Length: " + str(self.__length)


class Imagestream():
    def __init__(self, filepath=None):
        self.__streams = []
        self.__sectors = []
        self.__position = 0
        if filepath:
            self.__readcue(filepath)
            self.__readsectors()

    def __readcue(self, filepath):
        self.__streams = []
        p = Path(filepath)
        if p.suffix == ".cue":
            with open(filepath, "r") as f:
                rgxCue = re.compile(r'FILE \"(.*)\" BINARY\s+TRACK (\d+) MODE(\d)\/(\d+)\s+INDEX (\d+) (?:(\d+):(\d+):(\d+))')
                strCueSheet = f.read()
                matches = rgxCue.findall(strCueSheet)
                for m in matches:
                    filestream = Filestream(
                        os.path.join(p.parent, m[0])
                    )
                    self.__streams.append(filestream)

    def __writecue(self, path, name, streams):
        filepath = os.path.join(path, "{}.cue".format(name))
        with open(filepath, "w") as f:
            for i in range(len(streams)):
                s = streams[i]
                f.write('FILE "{}" BINARY\n'.format(s["filename"]))
                f.write('  TRACK {:02} MODE2/2352\n'.format(i+1))
                f.write('    INDEX 01 00:00:00\n')


    def __readsectors(self):
        self.__sectors = []
        for filestreamid in range(len(self.__streams)):
            s = self.__streams[filestreamid]
            index = 0
            while index < s.Length:
                s.Stream.seek(index, 0)
                buffer = s.Stream.read(24)
                header = Sector(buffer, filestreamid, index)
                self.__sectors.append(header)
                index += 2352

    def Read(self, buffer, LBA, count):
        bytesread = 0
        lba = LBA
        while bytesread < count:
            sector = self.__sectors[lba]
            sectorlen = 2324 if (sector.Submode & Submodes.Form) else 2048
            fs = self.__streams[sector.FileStreamId]
            fs.Stream.seek(sector.FileStreamOffset + 24, 0)
            sectordata = fs.Stream.read(sectorlen)
            if (count-bytesread) > sectorlen:
                buffer[bytesread:bytesread+sectorlen] = sectordata
                bytesread += sectorlen
                lba += 1
            else:
                remainderlen = count-bytesread
                buffer[bytesread:bytesread+remainderlen] = sectordata[:remainderlen]
                bytesread += remainderlen
        return bytesread

    def ReadSector(self, LBA) -> Sector:
        sector = self.__sectors[LBA]
        fs = self.__streams[sector.FileStreamId]
        sectorlen = 2324 if (sector.Submode & Submodes.Form) else 2048
        ecclen = 2352 - sectorlen - 24
        fs.Stream.seek(sector.FileStreamOffset + 24, 0)
        sector.Data = fs.Stream.read(sectorlen)
        sector.ECC = fs.Stream.read(ecclen)
        return sector

    def Write(self, path, name):
        outputstreams = []
        for i in range(len(self.__streams)):
            s = self.__streams[i]
            filename = "{} (Track {:02}).bin".format(name, i+1)
            of = {"filename": filename, "stream": open(os.path.join(path, filename), "wb")}
            outputstreams.append(of)
        for i in range(len(self.Sectors)):
            if self.Sectors[i].Data is None:
                self.Sectors[i] = self.ReadSector(i)
            s = self.Sectors[i]
            outputstreams[s.FileStreamId]["stream"].write(s.ToBytes())
        self.__writecue(path, name, outputstreams)

    @property
    def Streams(self):
        return self.__streams

    @property
    def Sectors(self):
        return self.__sectors

    @property
    def Length(self):
        return sum(f.Length for f in self.__streams)
