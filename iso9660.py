from enum import Enum, Flag, auto
from filestream import Imagestream
from sector import Submodes
from adpcm import ADPCMBlock
from struct import pack, unpack
from datetime import datetime, timezone, timedelta
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
        self.__readVolumeDescriptors()
        if len(self.__volumedescriptors) > 1:
            self.__readDirectoryRecord(self.__rootDirectory.ExtentLocation)
    
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

    def ReadAudio(self, record: DirectoryRecord, destination=None):
        sectorId = record.ExtentLocation
        filecounter = 0
        prev1 = 0
        prev2 = 0
        pcms = []
        sh = self.__imagestream.Sectors[sectorId]
        while not (sh.Submode & Submodes.EOF):
            if (sh.Submode & Submodes.Audio):
                s = self.__imagestream.ReadSector(sectorId)
                for sg in range(18):
                    data = s.Data[sg * 128:(sg * 128) + 128]
                    block = ADPCMBlock(data)
                    result,prev1,prev2 = block.ReadPCM(prev1, prev2) 
                    pcms.extend(result)
                if (sh.Submode & Submodes.EOR):
                    filename = destination + '/' if destination else ''
                    filename += "track" + "%02d" % filecounter + ".wav" 
                    wavefile = wave.open(filename, "wb")
                    wavefile.setparams((1, 2, 44100, len(pcms),"NONE","not compressed"))
                    frames = pack(str(len(pcms)) + "h", *pcms)
                    wavefile.writeframes(frames)
                    wavefile.close()
                    pcms = []
                    prev1 = 0
                    prev2 = 0
                    filecounter +=1
            sectorId +=1
            sh = self.__imagestream.Sectors[sectorId]

    @property
    def VolumeDescriptors(self):
        return self.__volumedescriptors

    @property
    def Files(self):
        return [f for f in self.__rootDirectory.Children if not (f.FileFlags & FileFlags.Directory)] 
