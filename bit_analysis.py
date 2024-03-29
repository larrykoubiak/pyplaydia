from PIL import Image, ImageDraw, ImageFont
import os
from tqdm import tqdm

def bytes_to_binary(byte_data):
    return ''.join(format(byte, '08b') for byte in byte_data)

def find_repeating_patterns(binary_str, min_pattern_length=8, max_pattern_length=64,cutoff_count=32):
    # Create a dictionary to store patterns and their counts
    pattern_length_counts = {}
    
    # Iterate through the binary string to find repeating patterns
    for i in range(len(binary_str) - min_pattern_length):
        for j in range(i + min_pattern_length, i + max_pattern_length + 1):
            pattern_length = str(j-i)
            if pattern_length not in pattern_length_counts:
                pattern_length_counts[pattern_length] = {}
            pattern_counts = pattern_length_counts[pattern_length]
            pattern = binary_str[i:j]
            if pattern in pattern_counts:
                pattern_counts[pattern] += 1
            else:
                pattern_counts[pattern] = 1

    for pattern_length, pattern_counts in pattern_length_counts.items():
        # Filter out patterns that appear only once
        repeating_patterns = {key: val for key, val in pattern_counts.items() if val >= cutoff_count}
        
        # Sort patterns by frequency
        sorted_patterns = sorted(repeating_patterns.items(), key=lambda item: item[1], reverse=True)
        pattern_length_counts[pattern_length] = sorted_patterns

    return pattern_length_counts

def binary_file_to_text(file_path, columns):
    result = ""
    with open(file_path, "rb") as f:
        byte_data = f.read()
    dest_path = file_path.replace('.bin','_bitmap.txt')
    binary_str = ''.join([format(byte, '08b') for byte in byte_data])
    rowlength = columns * 8
    # Convert to binary
    for row in range(0,int(len(binary_str)/rowlength)):
        offset = row * columns
        rowstr = "{:08x} ".format(offset)
        for col in range(columns):
            start = (offset * 8) + (col * 8)
            if start <len(binary_str):
                rowstr += binary_str[start: start + 8]
        result += rowstr + "\n"
    return result

def binary_file_to_image(file_path, columns):
    with open(file_path, "rb") as f:
        byte_data = f.read()
    # Convert to binary
    binary_str = ''.join([format(byte, '08b') for byte in byte_data])
    img_width = columns * 8
    # Calculate rows and create a blank image with space for text at the bottom
    rows = len(binary_str) // img_width
    img_height = rows + 30  # 30 pixels for text
    img = Image.new('1', (img_width, img_height), color=1)
    draw = ImageDraw.Draw(img)

    # Render binary data
    for y in range(rows):
        for x in range(img_width):
            bit_index = y * img_width + x
            if bit_index < len(binary_str) and binary_str[bit_index] == '0':
                draw.point((x, y), fill=0)

    # Render the file name at the bottom
    file_name = os.path.basename(file_path)
    font = ImageFont.truetype("arial.ttf", 15)  # Adjust path and size as needed
    text_width = draw.textlength(file_name, font=font)
    draw.text(((img_width - text_width) / 2, rows + 5), file_name, font=font, fill=0)

    return img

if __name__ == "__main__":
    folder = 'output/frames/001'
    files = [os.path.join(folder,f) for f in os.listdir(folder) if f.endswith('.bin')]
    images = []
    for f in tqdm(files):
        txt = binary_file_to_text(f, 16)
        img = binary_file_to_image(f, 16)
        with open(f.replace('.bin','_bitmap.txt'),'w') as o:
            o.write(txt)
        img.save(f.replace('.bin','_bitmap.png'))
        images.append(img)
    images[0].save(folder + ".gif", save_all=True, append_images=images[1:], duration=100, loop=0)

    # patterns = find_repeating_patterns(binary_str,20,64)

    # # for pattern_length in sorted(patterns, reverse=True):
    # #     for pattern, count in patterns[pattern_length]:
    # #         print(f"Length {pattern_length} Pattern {pattern} repeats {count} times")
