"""Native-rate 4-bit CD-XA ADPCM decoding shared by WAV and AVI exports."""

from struct import pack

# Preserve a separate predictor history for each channel.
K0 = (0, 960, 1840, 1568)
K1 = (0, 0, -832, -880)


class XaAudioDecoder:
    def __init__(self, coding):
        if coding & 0x10:
            raise ValueError("8-bit XA ADPCM is not supported")
        self.coding = coding
        self.sample_rate = 18900 if coding & 4 else 37800
        self.channels = 2 if coding & 1 else 1
        self.previous = [[0, 0] for _ in range(self.channels)]

    def decode_sector(self, data):
        if len(data) < 18 * 128:
            raise ValueError("Truncated XA audio sector")
        pcm = []
        for offset in range(0, 18 * 128, 128):
            group = data[offset:offset + 128]
            units = []
            for unit in range(8):
                parameter = group[4 + unit]
                shift = parameter & 15
                if shift > 12:
                    shift = 9
                filter_index = (parameter >> 4) & 3
                channel = unit % self.channels
                previous, previous2 = self.previous[channel]
                samples = []
                for sample in range(28):
                    value = (group[16 + sample * 4 + unit // 2] >> ((unit & 1) * 4)) & 15
                    value = value - 16 if value & 8 else value
                    residual = (value << 12) >> shift
                    prediction = -previous * K0[filter_index] - previous2 * K1[filter_index]
                    decoded = (residual << 4) - (prediction >> 10)
                    previous2, previous = previous, decoded
                    samples.append(max(-32768, min(32767, decoded >> 4)))
                self.previous[channel] = [previous, previous2]
                units.append(samples)
            if self.channels == 1:
                pcm.extend(value for unit in units for value in unit)
            else:
                for unit in range(0, 8, 2):
                    for left, right in zip(units[unit], units[unit + 1]):
                        pcm.extend((left, right))
        return pack(f"<{len(pcm)}h", *pcm)
