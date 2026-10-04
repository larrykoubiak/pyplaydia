"""Audio conversion for the player's fixed pygame mixer format."""

from array import array
import sys


OUTPUT_RATE = 37800
OUTPUT_CHANNELS = 2


def normalize_pcm(pcm: bytes, sample_rate: int, channels: int) -> bytes:
    """Convert supported native XA PCM to 37.8 kHz signed stereo PCM.

    Playdia's two native rates have an exact 2:1 relationship, so low-rate
    samples can be repeated without interpolation. Mono samples are duplicated
    into the left and right output channels.
    """
    if sample_rate not in (18900, OUTPUT_RATE):
        raise ValueError(f"Unsupported player sample rate: {sample_rate}")
    if channels not in (1, OUTPUT_CHANNELS):
        raise ValueError(f"Unsupported player channel count: {channels}")
    if len(pcm) % (channels * 2):
        raise ValueError("PCM does not contain complete sample frames")
    if not pcm:
        return b""

    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()

    if channels == 1 and sample_rate == OUTPUT_RATE:
        output = array("h", [0]) * (len(samples) * 2)
        output[0::2] = samples
        output[1::2] = samples
    elif channels == 1:
        output = array("h", [0]) * (len(samples) * 4)
        output[0::4] = samples
        output[1::4] = samples
        output[2::4] = samples
        output[3::4] = samples
    elif sample_rate == OUTPUT_RATE:
        output = samples
    else:
        left = samples[0::2]
        right = samples[1::2]
        output = array("h", [0]) * (len(samples) * 2)
        output[0::4] = left
        output[1::4] = right
        output[2::4] = left
        output[3::4] = right

    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()
