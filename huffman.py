from heapq import heappop, heappush
from graphviz import Graph

class BitBuffer:
    def __init__(self):
        self.__values = bytearray()
        self.__buffer = 0
        self.__pos = 0
        self.__index = 0

    def push(self, bit):
        self.__buffer <<= 1
        self.__buffer |= bit
        self.__pos += 1
        if self.__pos == 8:
            self.__values.append(self.__buffer)
            if self.__buffer == 0xFF:
                self.__values.append(0x00)
            self.__buffer = 0
            self.__pos = 0
    
    def pop(self):
        self.__buffer = (self.__values[self.__index] >> (7 - (self.__pos)))
        self.__pos += 1
        if self.__pos > 7:
            self.__pos = 0
            self.__index += 1
            if self.__index < len(self.__values):
                if self.__values[self.__index] == 0xFF:
                    self.__index += 1
                    if self.__values[self.__index] == 0x00:
                        self.__index += 1
                    elif self.__values[self.__index] == 0xD9:
                        return None
                    else:
                        print("error")
            else:
                return None
        return self.__buffer & 0x01
    
    @property
    def Values(self):
        values = self.__values
        if self.__pos > 0:
            buffer = self.__buffer << (8 - self.__pos)
            # buffer |= (0xff >> self.__pos)
            values.append(buffer)
        return values

    @Values.setter
    def Values(self, value):
        self.__values = value

class HuffmanNode:
    def __init__(self, val, freq):
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
    def __init__(self):
        self.root = None
        self.codes = {}
        self.reverse_codes = {}
    
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
    
    def Decode(self, values):
        buffer = BitBuffer()
        buffer.Values = values
        b = buffer.pop()
        node = self.root
        decvals = bytearray()
        while b is not None:
            node = node.left if b == 0 else node.right
            if node.IsLeaf():
                if node.value == 0xFF:
                    break
                decvals.append(node.value)
                node = self.root
            b = buffer.pop()
        return decvals
    
    def DrawTree(self, parent=None, graph=None):
        node = self.root if parent is None else parent
        graph = Graph() if graph is None else graph
        graph.node(node.value, "'" + node.value + "'" if node.IsLeaf() else '')
        if node.left is not None:
            self.DrawTree(node.left, graph)
            graph.edge(node.value, node.left.value, "0")
        if node.right is not None:
            self.DrawTree(node.right, graph)
            graph.edge(node.value, node.right.value, "1")
        if node == self.root:
            graph.render('output/test.gv', format="png",view=True)
    
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
    decoded_message = h.Decode(encoded_message).decode()
    print(decoded_message)