class Huffman:
    def __init__(self, input_string = None):
        self.__frequencies = {}
        if input_string is not None:
            self.__calculatefreqs(input_string)
    
    def __calculatefreqs(self, input_string):
        for c in input_string:
            if c not in self.__frequencies:
                self.__frequencies[c] = 0
            self.__frequencies[c] += 1
        self.__frequencies = {k: v for k, v in sorted(self.__frequencies.items(), key=lambda item: item[1])}
    @property
    def Frequencies(self):
        return self.__frequencies


class HuffmanTree:
    def __init__(self, ):
        self.left = None
        self.right = None
        self.value = None

if __name__ == "__main__":
    h = Huffman("ADA ATE AN APPLE")
    print(h.Frequencies)