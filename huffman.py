from heapq import heappop, heappush
from graphviz import Graph

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
    def __init__(self, input_string = None):
        self.root = None
        if input_string is not None:
            self.__buildtree(input_string)
    
    def __buildtree(self, input_string):
        frequencies = {}
        heap = []
        for c in input_string:
            if c not in frequencies:
                frequencies[c] = 0
            frequencies[c] += 1
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


if __name__ == "__main__":
    h = Huffman("ADA ATE AN APPLE")
    h.DrawTree()