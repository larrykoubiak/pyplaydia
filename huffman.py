from heapq import heappop, heappush
from graphviz import Graph, Digraph
from bitbuffer import BitBuffer
import os
from json import load, dump
from enum import Enum

class HuffmanTableType(Enum):
    DC = 0x00
    AC = 0x01

class HuffmanNode:
    def __init__(self, val = None, freq = None):
        self.value = val
        self.freq = freq
        self.left = None
        self.right = None
    def IsLeaf(self):
        return (self.left is None and self.right is None)
    def __lt__(self, other):
        return False  if other is None or not isinstance(other, HuffmanNode) else self.freq < other.freq
    def __le__(self, other):
        return False  if other is None or not isinstance(other, HuffmanNode) else self.freq <= other.freq
    def __eq__(self, other):
        return False  if other is None or not isinstance(other, HuffmanNode) else self.freq == other.freq
    def __ne__(self, other):
        return False  if other is None or not isinstance(other, HuffmanNode) else self.freq != other.freq
    def __ge__(self, other):
        return False  if other is None or not isinstance(other, HuffmanNode) else self.freq >= other.freq
    def __gt__(self, other):
        return False  if other is None or not isinstance(other, HuffmanNode) else self.freq > other.freq
    def __repr__(self):
        return "'%s': %d" % (self.value, self.freq)

class Huffman:
    def __init__(self, bytes=None, filename = None):
        self.Id = None
        self.TableType = None
        self.bytesread = 0
        self.root = None
        self.codes = {}
        self.reverse_codes = {}
        if bytes is not None:
            self.FromBytes(bytes)
        elif filename is not None:
            self.FromJSON(filename)
    
    def FromString(self, input_string):
        frequencies = {}
        heap = []
        input = bytearray()
        input.extend(map(ord, input_string))
        for c in input:
            if c not in frequencies:
                frequencies[c] = 0
            frequencies[c] += 1
        frequencies[0xFF] = 0
        for k, v in frequencies.items():
            node = HuffmanNode(k, v)
            heappush(heap, node)
        while len(heap) > 1:
            node1 = heappop(heap)
            node2 = heappop(heap)
            merged = HuffmanNode(node1.value + node2.value, node1.freq + node2.freq)
            merged.left = node1
            merged.right = node2
            heappush(heap, merged)
        self.root = heap[0]
        code = ""
        self.__traversetree(self.root, code)

    def FromBytes(self, bytes):
        self.bytesread = 0
        self.Id = bytes[self.bytesread] & 0x0F
        self.TableType = HuffmanTableType(bytes[self.bytesread] >> 4)
        self.bytesread += 1
        codes = {}
        code = 0
        counts = []
        for i in range(16):
            counts.append(bytes[self.bytesread])
            self.bytesread += 1
        for i in range(16):
            for _ in range(counts[i]):
                codes[(i+1, code)] = bytes[self.bytesread]
                code +=1
                self.bytesread += 1
            code <<= 1
        self.root = HuffmanNode(0)
        for k, v in codes.items():
            node = self.root
            ln = k[0]
            code = "{:0" + str(ln) +"b}"
            code = code.format(k[1])
            for i in range(ln):
                b = code[i]
                if b == "0":
                    if node.left is None:
                        node.left = HuffmanNode()
                    node = node.left
                elif b == "1":
                    if node.right is None:
                        node.right = HuffmanNode()
                    node = node.right
            node.value = v

    def FromJSON(self, filename):
        self.root = HuffmanNode(0)
        with open(filename, "r") as f:
            jsondic = load(f)
        for entry in jsondic:
            node = self.root
            for i in range(entry["len"]):
                b =  entry["binary"][i]
                if b == "0":
                    if node.left is None:
                        node.left = HuffmanNode()
                    node = node.left
                elif b == "1":
                    if node.right is None:
                        node.right = HuffmanNode()
                    node = node.right
            node.value = entry["value"]

    def ToJSON(self, filename):
        jsondic = []
        self.__traversetree(self.root, "")
        for k, v in self.reverse_codes.items():
            jsondic.append({"len":len(k), "code": int(k,2), "binary": k, "value": v, "hex": "{:02X}".format(v)})
        with open(filename, "w") as f:
            dump(jsondic, f, indent=4)

    def __traversetree(self, node, code):
        if node is None:
            return
        if node.IsLeaf():
            self.codes[node.value] = code
            self.reverse_codes[code] = node.value
            return
        self.__traversetree(node.left, code + "0")
        self.__traversetree(node.right, code + "1")
            

    def Encode(self, string):
        buffer = BitBuffer()
        input = bytearray()
        input.extend(map(ord, string))
        input.append(0xFF)
        for c in input:
            code = self.codes[c]
            for d in code:
                buffer.push(int(d))
        return buffer.Values
    
    def DecodeString(self, buffer):
        decvals = bytearray()
        val = self.DecodeChar(buffer)
        while val is not None:
            decvals.append(val)
            val = self.DecodeChar(buffer)
        return decvals
    
    def DecodeChar(self, buffer):
        node = self.root
        while node is not None and not node.IsLeaf() and not buffer.EOF:
            b = buffer.pop()
            node = node.left if b == 0 else node.right
        return None if node is None or node.value == 0xFF else node.value

    
    def DrawTree(self, parent=None, graph=None, code = "", filename="test.gv"):
        node = self.root if parent is None else parent
        if graph is None:
            graph = Graph(engine="dot")
        else:
            graph = graph
        graph.node("Root" if code =="" else code, '%02X' % node.value if node.IsLeaf() else '')
        if node.left is not None:
            self.DrawTree(node.left, graph, code + "0")
            graph.edge(("Root" if code =="" else code), code + "0", "0")
        if node.left is not None and node.right is not None:
            graph.node(code + "_","",style="invis",width=".1")
            graph.edge(("Root" if code =="" else code), code + "_",style="invis")
        if node.right is not None:
            self.DrawTree(node.right, graph, code + "1")
            graph.edge(("Root" if code =="" else code), code + "1", "1")
        if parent is None:
            if not os.path.exists("output"):
                os.mkdir("output")
            graph.render('output/' + filename, format="png")

    def __repr__(self):
        result = "Table {:02X} Type {}".format(self.Id, self.TableType)
        for k, v in self.Codes.items():
            formatstr = "\n{:0" + str(k[0]) + "b} at length {} = {:02X}" 
            result += formatstr.format(k[1],k[0],v)
        return result

    @property
    def Root(self):
        return self.root

    @property
    def Codes(self):
        return self.codes

    @property
    def ReverseCodes(self):
        return self.reverse_codes

if __name__ == "__main__":
    message = "ADA ATE AN APPLE"
    t = int()
    print(message)
    h = Huffman()
    h.FromString(message)
    print(h.codes)
    encoded_message = h.Encode(message)
    print(' '.join(format(b, '08b') for b in encoded_message))
    print(' '.join(format(b, '02X') for b in encoded_message))
    decoded_message = h.DecodeString(BitBuffer(encoded_message)).decode()
    print(decoded_message)
    h.DrawTree()
