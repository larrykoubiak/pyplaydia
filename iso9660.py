import os
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
from enum import Enum, Flag, auto
from filestream import Imagestream
from sector import Submodes
from playdia_codec.adpcm import XaAudioDecoder
from playdia_codec import Picture
from playdia_codec.video_export import export_scene
from struct import unpack
from tqdm import tqdm
import wave


class VolumeDescriptorType(Enum):
    Boot = 0
    Primary = 1
    Supplementary = 2
    Partition = 3
    SetTerminator = 255


class FileFlags(Flag):
    Existence = auto()
    Directory = auto()
    AssociatedFile = auto()
    Record = auto()
    Protection = auto()
    Reserved1 = auto()
    Reserved2 = auto()
    MultiExtent = auto()


class XAFlags(Flag):
    OwnerRead = 0x0001
    OwnerExecute = 0x0004
    GroupRead = 0x0010
    GroupExecute = 0x0040
    WorldRead = 0x0100
    WorldExecute = 0x0400
    Form1 = 0x0800
    Form2 = 0x1000
    Interleaved = 0x2000
    CDDA = 0x4000
    Directory = 0x8000


def TimeToLBA(minutes, seconds, block):
    return (minutes * 60 * 75) + ((seconds-2) * 75) + block

class ISO9660TextDate():
    def __init__(self, data):
        temp = unpack("4s2s2s2s2s2s2sb", data)
        self.__year = int(temp[0].decode())
        self.__month = int(temp[1].decode())
        self.__day = int(temp[2].decode())
        self.__hour = int(temp[3].decode())
        self.__minute = int(temp[4].decode())
        self.__second = int(temp[5].decode())
        self.__ms = int(temp[6].decode())
        self.__offset = temp[7]
    
    @property
    def Date(self):
        return None if self.__year == 0 else \
               datetime(self.__year, self.__month,self.__day,
                        self.__hour, self.__minute, self.__second, self.__ms * 10,
                        timezone(timedelta(minutes=self.__offset * 15)))


class VolumeDescriptor():
    def __init__(self, data):
        header = unpack("<B5sB2041s", data)
        self.__volumedescriptortype = VolumeDescriptorType(header[0])
        self.__standardidentifier = header[1].decode()
        self.__volumedescriptorversion = header[2]
        self.__data = header[3]

    @property
    def VolumeDescriptorType(self):
        return self.__volumedescriptortype

    @property
    def StandardIdentifier(self):
        return self.__standardidentifier

    @property
    def VolumeDescriptorVersion(self):
        return self.__volumedescriptorversion

    @property
    def Data(self):
        return self.__data
    
    def __repr__(self):
        values = tuple(self.__dict__.values())
        result = "{0} {1} {2}".format(*values)
        return result


class PrimaryVolumeDescriptor(VolumeDescriptor):
    def __init__(self, data):
        super().__init__(data)
        formatstr = "<B32s32s8sII32sHHHHHHIIIIII"
        formatstr += "34s128s128s128s128s37s37s37s17s17s17s17s"
        formatstr += "BB512s653s"
        temp = unpack(formatstr, self.Data)
        self.systemIdentifier = temp[1].decode()
        self.volumeIdentifier = temp[2].decode()
        self.volumeSpaceSize = temp[4]
        self.volumeSetSize = temp[7]
        self.volumeSequenceNumber = temp[9]
        self.logicalBlockSize = temp[11]
        self.pathTableSize = temp[13]
        self.locationPathTable = temp[15]
        self.locationOptionalPathTable = temp[16]
        self.rootDirectoryRecord = DirectoryRecord(temp[19])
        self.volumeSetIdentifier = temp[20].decode()
        self.publisherIdentifier = temp[21].decode()
        self.dataPreparerIdentifier = temp[22].decode()
        self.applicationIdentifier = temp[23].decode()
        self.copyrightFileIdentifier = temp[24].decode()
        self.abstractFileIdentifier = temp[25].decode()
        self.bibliographicFileIdentifier = temp[26].decode()
        self.volumeCreationDateTime = ISO9660TextDate(temp[27]).Date
        self.volumeModificationDateTime = ISO9660TextDate(temp[28]).Date
        self.volumeExpirationDateTime = ISO9660TextDate(temp[29]).Date
        self.volumeEffectiveDateTime = ISO9660TextDate(temp[30]).Date
        self.fileStructureVersion = temp[31]
        self.applicationUse = temp[33]

    def __repr__(self):
        result = super().__repr__()
        values = tuple(self.__dict__.values())
        result += "\n{4} {5} {21}".format(*values)
        return result


class DirectoryRecord():
    def __init__(self, data):
        header = unpack("<BBIIII7sBBBHHBb", data[:34])
        self.LengthDR = header[0]
        self.LengthAR = header[1]
        self.ExtentLocation = header[2]
        self.DataLength = header[4]
        tempdate = unpack("BBBBBBb",header[6])
        self.RecordingDate = None if tempdate[0] == 0 else \
            datetime(
            1900 + tempdate[0],
            tempdate[1],
            tempdate[2],
            tempdate[3],
            tempdate[4],
            tempdate[5],
            tzinfo=timezone(timedelta(minutes = tempdate[6] * 15))
        )
        self.FileFlags = FileFlags(header[7])
        self.FileUnitSize = header[8]
        self.InterleaveGapSize = header[9]
        self.VolumeSequenceNumber = header[10]
        self.LengthFI = header[12]
        self.FileIdentifier = ""
        self.Children = []
        self.GroupID = 0
        self.XAFlags = XAFlags(0)
        self.XAFileId = 0
    
    def __repr__(self):
        formatstring = "<File {} Size {:04X} Date {} {} {} XAFileId {}>"
        return formatstring.format(
            self.FileIdentifier,
            self.DataLength,
            self.RecordingDate,
            self.FileFlags,
            self.XAFlags,
            self.XAFileId
        )


class ISOImage():
    def __init__(self, filepath):
        self.__imagestream = Imagestream(filepath)
        self.__volumedescriptors = []
        self.__rootDirectory = None
        self.__nbSectors = self.__imagestream.Length / 2352
        try:
            self.__readVolumeDescriptors()
            if len(self.__volumedescriptors) > 1:
                self.__readDirectoryRecord(self.__rootDirectory.ExtentLocation)
        except BaseException:
            self.close()
            raise

    def close(self):
        self.__imagestream.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
    
    def __readVolumeDescriptors(self):
        sectorId = 16
        sector = self.__imagestream.ReadSector(sectorId)
        vd = VolumeDescriptor(sector.Data)
        while vd.VolumeDescriptorType != VolumeDescriptorType.SetTerminator and \
              sectorId < self.__nbSectors:
            if vd.StandardIdentifier == "CD001":
                if vd.VolumeDescriptorType == VolumeDescriptorType.Primary:
                    pvd = PrimaryVolumeDescriptor(sector.Data)
                    self.__volumedescriptors.append(pvd)
                    self.__rootDirectory = pvd.rootDirectoryRecord
            sectorId += 1
            sector = self.__imagestream.ReadSector(sectorId)
            vd = VolumeDescriptor(sector.Data)
        if vd.StandardIdentifier == "CD001":
            self.__volumedescriptors.append(vd)

    def __readDirectoryRecord(self, sectorId):
        sector = self.__imagestream.ReadSector(sectorId)
        offset = 0
        while sector.Data[offset] != 0:
            length = sector.Data[offset]
            data = sector.Data[offset:offset+length]
            dr = DirectoryRecord(data)
            pos = 33
            if dr.LengthFI > 1:
                dr.FileIdentifier = data[pos:pos+dr.LengthFI-2].decode().rstrip()
            else:
                if data[pos] == 0:
                    dr.FileIdentifier = "."
                elif data[pos] == 1:
                    dr.FileIdentifier = ".."
                else:
                    dr.FileIdentifier = ""
                pos -= 1
            pos += dr.LengthFI + 1
            if data[pos+6:pos+8].decode() == "XA":
                dr.GroupID = unpack(">I",data[pos:pos+4])[0]
                dr.XAFlags = XAFlags(unpack(">H", data[pos+4:pos+6])[0])
                dr.XAFileId = data[pos+8]
            self.__rootDirectory.Children.append(dr)
            offset += length
    
    def ReadFile(self, record: DirectoryRecord, destination=None):
        size = record.DataLength
        buffer = bytearray(size)
        self.__imagestream.Read(buffer, record.ExtentLocation, size)
        if destination is None:
            return buffer
        else:
            with open(destination,'wb') as o:
                o.write(buffer)

    def ReadAudio(self, record: DirectoryRecord, destination, limit=0):
        """Export the first XA channel in each scene to native-rate PCM WAV."""
        for filecounter, start, stop in self.__scene_ranges(record, limit):
            filename = os.path.join(destination, "audio_{:03}.wav".format(filecounter))
            decoder = None
            audio_channel = None
            with ExitStack() as outputs, tqdm(
                range(start, stop), desc=os.path.basename(filename), unit="sector", leave=False
            ) as sectors:
                for sectorId in sectors:
                    header = self.__imagestream.Sectors[sectorId]
                    if not (header.Submode & Submodes.Audio):
                        continue
                    if audio_channel is not None and header.Channel != audio_channel:
                        continue
                    sector = self.__imagestream.ReadSector(sectorId)
                    coding = sector.Coding.value
                    if decoder is None:
                        decoder = XaAudioDecoder(coding)
                        audio_channel = sector.Channel
                        os.makedirs(destination, exist_ok=True)
                        wavefile = outputs.enter_context(wave.open(filename, "wb"))
                        wavefile.setparams((decoder.channels, 2, decoder.sample_rate, 0, "NONE", "not compressed"))
                    elif coding != decoder.coding:
                        raise ValueError("XA audio format changes within a scene")
                    wavefile.writeframesraw(decoder.decode_sector(sector.Data))

    def __scene_ranges(self, record, limit):
        """Yield (scene number, start, stop); audio EOR does not end a scene."""
        sectorId = record.ExtentLocation
        scene_start = sectorId
        filecounter = 0
        headers = self.__imagestream.Sectors
        while sectorId < len(headers):
            sh = headers[sectorId]
            if sh.Submode & Submodes.EOF:
                break
            if not (sh.Submode & Submodes.Audio) and sh.Submode & Submodes.EOR:
                yield filecounter, scene_start, sectorId + 1
                scene_start = sectorId + 1
                filecounter += 1
                if limit > 0 and filecounter >= limit:
                    return
            sectorId += 1
        if scene_start < sectorId:
            yield filecounter, scene_start, sectorId

    def ReadVideo(self, record: DirectoryRecord, destination, limit=0):
        """Export each physical scene as lossless PNG video with PCM audio."""
        for filecounter, start, stop in self.__scene_ranges(record, limit):
            filename = os.path.join(destination, "video_{:03}.avi".format(filecounter))
            count = export_scene(self.__imagestream, start, stop, filename)
            if count:
                print(f"Wrote {filename} ({count} pictures)")

    def ReadVideoFrames(self, record: DirectoryRecord, destination, limit=0):
        """Decode complete F1/F2 pictures directly to PNG files."""
        sectorId = record.ExtentLocation
        filecounter = 0
        framecounter = 0
        packet = bytearray()
        sh = self.__imagestream.Sectors[sectorId]
        while not (sh.Submode & Submodes.EOF):
            if not (sh.Submode & Submodes.Audio):
                s = self.__imagestream.ReadSector(sectorId)
                if s.Data[0] == 0xF1:
                    packet += s.Data[:2048]
                elif s.Data[0] == 0xF2 and packet:
                    packet += s.Data[:2048]
                    filename = os.path.join(destination, "{:03}/frame_{:04}.png".format(filecounter, framecounter))
                    Picture.from_bytes(packet).save(filename)
                    packet = bytearray()
                    framecounter += 1
                # F3 padding and non-video sectors contribute no picture data.
                # In particular, scene boundaries can contain 2324-byte Form2
                # sectors which used to corrupt the next extracted frame.
                if (sh.Submode & Submodes.EOR):
                    filecounter += 1
                    framecounter = 0
                    if limit > 0 and filecounter >= limit:
                        break
            sectorId += 1
            sh = self.__imagestream.Sectors[sectorId]

    def PatchFrame(self, sectorId, data, offset=0x28):
        o = offset
        sid = sectorId
        shiftdata = data
        s = self.__imagestream.ReadSector(sectorId)
        while s.Data[0] != 0xF2:
            if not(s.Submode & Submodes.Audio) and s.Data[0] == 0xF1:
                shiftdata = s.insertData(shiftdata, o)
                o = 1
            sid += 1
            # skip audio sectors
            while (self.__imagestream.Sectors[sid].Submode & Submodes.Audio):
                sid +=1
            s = self.__imagestream.ReadSector(sid)
        # F2 picture payload follows its marker and 34 control bytes.
        s.insertData(shiftdata, 0x23)
        
    def Write(self, path, name):
        self.__imagestream.Write(path, name)

    @property
    def VolumeDescriptors(self):
        return self.__volumedescriptors

    @property
    def ImageStream(self):
        """Underlying sector stream for interactive, LBA-addressed readers."""
        return self.__imagestream

    @property
    def Files(self):
        return [f for f in self.__rootDirectory.Children if not (f.FileFlags & FileFlags.Directory)]
