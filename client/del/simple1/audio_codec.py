"""
Audio codec for ROIP protocol
Supports µ-law encoding/decoding with XOR encryption (HAM protocol)
Includes RC and Butterworth high-pass filters
"""

import struct
import math

# ========== µ-law tables ==========
# µ-law to Linear conversion table (from Java TConversionTool)
U2L_TABLE = [
    -32124, -31100, -30076, -29052, -28028, -27004, -25980, -24956,
    -23932, -22908, -21884, -20860, -19836, -18812, -17788, -16764,
    -15996, -15484, -14972, -14460, -13948, -13436, -12924, -12412,
    -11900, -11388, -10876, -10364, -9852, -9340, -8828, -8316,
    -7932, -7676, -7420, -7164, -6908, -6652, -6396, -6140,
    -5884, -5628, -5372, -5116, -4860, -4604, -4348, -4092,
    -3900, -3772, -3644, -3516, -3388, -3260, -3132, -3004,
    -2876, -2748, -2620, -2492, -2364, -2236, -2108, -1980,
    -1884, -1820, -1756, -1692, -1628, -1564, -1500, -1436,
    -1372, -1308, -1244, -1180, -1116, -1052, -988, -924,
    -876, -844, -812, -780, -748, -716, -684, -652,
    -620, -588, -556, -524, -492, -460, -428, -396,
    -372, -356, -340, -324, -308, -292, -276, -260,
    -244, -228, -212, -196, -180, -164, -148, -132,
    -120, -112, -104, -96, -88, -80, -72, -64,
    -56, -48, -40, -32, -24, -16, -8, 0,
    32124, 31100, 30076, 29052, 28028, 27004, 25980, 24956,
    23932, 22908, 21884, 20860, 19836, 18812, 17788, 16764,
    15996, 15484, 14972, 14460, 13948, 13436, 12924, 12412,
    11900, 11388, 10876, 10364, 9852, 9340, 8828, 8316,
    7932, 7676, 7420, 7164, 6908, 6652, 6396, 6140,
    5884, 5628, 5372, 5116, 4860, 4604, 4348, 4092,
    3900, 3772, 3644, 3516, 3388, 3260, 3132, 3004,
    2876, 2748, 2620, 2492, 2364, 2236, 2108, 1980,
    1884, 1820, 1756, 1692, 1628, 1564, 1500, 1436,
    1372, 1308, 1244, 1180, 1116, 1052, 988, 924,
    876, 844, 812, 780, 748, 716, 684, 652,
    620, 588, 556, 524, 492, 460, 428, 396,
    372, 356, 340, 324, 308, 292, 276, 260,
    244, 228, 212, 196, 180, 164, 148, 132,
    120, 112, 104, 96, 88, 80, 72, 64,
    56, 48, 40, 32, 24, 16, 8, 0
]

# Exponent lookup table for µ-law encoding
EXP_LUT = [
    0, 0, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3,
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7
]


# ========== Audio Codec ==========
class AudioCodec:
    """Audio codec for ROIP protocol with µ-law and XOR encryption"""
    
    @staticmethod
    def linear_to_ulaw(sample: int) -> int:
        """Convert 16-bit PCM sample to µ-law (8-bit)"""
        if sample > 32767:
            sample = 32767
        elif sample < -32768:
            sample = -32768
        
        sign = (sample >> 8) & 0x80
        if sign != 0:
            sample = -sample
        
        if sample > 32635:
            sample = 32635
        
        sample += 132
        exponent = EXP_LUT[(sample >> 7) & 0xFF]
        mantissa = (sample >> (exponent + 3)) & 0x0F
        
        ulawbyte = ~(sign | (exponent << 4) | mantissa)
        if ulawbyte == 0:
            ulawbyte = 2
        
        return ulawbyte & 0xFF
    
    @staticmethod
    def ulaw_to_linear(ulawbyte: int) -> int:
        """Convert µ-law (8-bit) to 16-bit PCM sample"""
        return U2L_TABLE[ulawbyte & 0xFF]
    
    @staticmethod
    def encode_pcm_to_ulaw(pcm_data: bytes) -> bytes:
        """Encode 16-bit PCM data to µ-law"""
        ulaw_data = bytearray()
        for i in range(0, len(pcm_data), 2):
            sample = struct.unpack('<h', pcm_data[i:i+2])[0]
            ulaw_data.append(AudioCodec.linear_to_ulaw(sample))
        return bytes(ulaw_data)
    
    @staticmethod
    def decode_ulaw_to_pcm(ulaw_data: bytes) -> bytes:
        """Decode µ-law to 16-bit PCM"""
        pcm_data = bytearray()
        for byte in ulaw_data:
            sample = AudioCodec.ulaw_to_linear(byte)
            pcm_data.extend(struct.pack('<h', sample))
        return bytes(pcm_data)
    
    @staticmethod
    def xor_encrypt(data: bytes, key: int = 0xAA) -> bytes:
        """XOR encryption/decryption (HAM protocol)"""
        return bytes([b ^ key for b in data])
    
    @staticmethod
    def encode_audio_for_ham(pcm_data: bytes) -> bytes:
        """Full HAM encoding: PCM -> µ-law -> XOR"""
        ulaw_data = AudioCodec.encode_pcm_to_ulaw(pcm_data)
        return AudioCodec.xor_encrypt(ulaw_data)
    
    @staticmethod
    def decode_audio_from_ham(encrypted_data: bytes) -> bytes:
        """Full HAM decoding: XOR -> µ-law -> PCM"""
        ulaw_data = AudioCodec.xor_encrypt(encrypted_data)
        return AudioCodec.decode_ulaw_to_pcm(ulaw_data)


# ========== RC High-Pass Filter ==========
class SimpleHighPassFilter:
    """
    Simple high-pass filter (RC filter) with gain compensation
    First order filter, 6 dB/octave slope
    """
    
    def __init__(self, cutoff_freq: int = 200, sample_rate: int = 8000, gain_db: float = 6.0):
        self.cutoff_freq = cutoff_freq
        self.sample_rate = sample_rate
        self.prev_input = 0
        self.prev_output = 0
        self.enabled = True
        self.gain_db = gain_db
        self.gain_linear = 10 ** (gain_db / 20)
        
        RC = 1.0 / (2 * 3.14159265359 * cutoff_freq)
        dt = 1.0 / sample_rate
        self.alpha = dt / (RC + dt)
    
    def process(self, data: bytes) -> bytes:
        if not self.enabled:
            return data
        
        samples = []
        for i in range(0, len(data), 2):
            sample = struct.unpack('<h', data[i:i+2])[0]
            filtered = self.alpha * (self.prev_output + sample - self.prev_input)
            filtered = filtered * self.gain_linear
            filtered = max(-32768, min(32767, int(filtered)))
            self.prev_input = sample
            self.prev_output = filtered
            samples.append(filtered)
        
        result = bytearray()
        for sample in samples:
            result.extend(struct.pack('<h', sample))
        return bytes(result)
    
    def reset(self):
        self.prev_input = 0
        self.prev_output = 0
    
    def set_cutoff(self, cutoff_freq: int):
        self.cutoff_freq = cutoff_freq
        RC = 1.0 / (2 * 3.14159265359 * cutoff_freq)
        dt = 1.0 / self.sample_rate
        self.alpha = dt / (RC + dt)
        self.reset()
    
    def set_gain(self, gain_db: float):
        self.gain_db = gain_db
        self.gain_linear = 10 ** (gain_db / 20)
    
    def enable(self):
        self.enabled = True
        self.reset()
    
    def disable(self):
        self.enabled = False
        self.reset()


# ========== Butterworth High-Pass Filter ==========
class ButterworthHighPass:
    """
    Butterworth high-pass filter 2nd order
    Steeper rolloff (12 dB/octave), no ripple in passband
    """
    
    def __init__(self, cutoff_freq: int = 200, sample_rate: int = 8000, gain_db: float = 6.0):
        self.cutoff_freq = cutoff_freq
        self.sample_rate = sample_rate
        self.gain_db = gain_db
        self.gain_linear = 10 ** (gain_db / 20)
        self.enabled = True
        
        self.x1 = 0
        self.x2 = 0
        self.y1 = 0
        self.y2 = 0
        
        self._calculate_coefficients()
    
    def _calculate_coefficients(self):
        w0 = 2 * math.pi * self.cutoff_freq / self.sample_rate
        cos_w0 = math.cos(w0)
        sin_w0 = math.sin(w0)
        
        Q = 0.7071067811865476
        alpha = sin_w0 / (2 * Q)
        
        b0 = (1 + cos_w0) / 2
        b1 = -(1 + cos_w0)
        b2 = (1 + cos_w0) / 2
        a0 = 1 + alpha
        a1 = -2 * cos_w0
        a2 = 1 - alpha
        
        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0
    
    def process(self, data: bytes) -> bytes:
        if not self.enabled:
            return data
        
        samples = []
        for i in range(0, len(data), 2):
            x = struct.unpack('<h', data[i:i+2])[0]
            
            y = (self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2 
                 - self.a1 * self.y1 - self.a2 * self.y2)
            
            self.x2 = self.x1
            self.x1 = x
            self.y2 = self.y1
            self.y1 = y
            
            y = y * self.gain_linear
            y = max(-32768, min(32767, int(y)))
            samples.append(y)
        
        result = bytearray()
        for sample in samples:
            result.extend(struct.pack('<h', sample))
        return bytes(result)
    
    def reset(self):
        self.x1 = self.x2 = self.y1 = self.y2 = 0
    
    def set_cutoff(self, cutoff_freq: int):
        if cutoff_freq == self.cutoff_freq:
            return
        self.cutoff_freq = cutoff_freq
        self._calculate_coefficients()
        self.reset()
    
    def set_gain(self, gain_db: float):
        self.gain_db = gain_db
        self.gain_linear = 10 ** (gain_db / 20)
    
    def enable(self):
        self.enabled = True
        self.reset()
    
    def disable(self):
        self.enabled = False
        self.reset()