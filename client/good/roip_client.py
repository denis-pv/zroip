"""
ROIP Client for HAM Radio - Minimal version with full duplex support
"""

import socket
import threading
import time
import pyaudio
import struct
import math
import queue

# ========== GLOBAL CONFIGURATION ==========
SERVER_IP = "api.k240.ru"
SERVER_PORT = 1222
BUFFER_SIZE = 808
AUDIO_CHUNK = 800
SAMPLE_RATE = 8000
KEEP_ALIVE_INTERVAL = 15
PACKET_INTERVAL = 0.1

CODEC_TYPE = 2
ROIP_CHANNEL = 1

ENABLE_HIGHPASS_FILTER = True
HIGHPASS_CUTOFF_FREQ = 300
HIGHPASS_GAIN_DB = 9.0

PLAYBACK_BUFFER_SIZE = 2
PLAYBACK_QUEUE_MAX = 1

D_ROIP_G711HAM = 2


# ========== AUDIO CODEC (unchanged) ==========
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


class AudioCodec:
    @staticmethod
    def linear_to_ulaw(sample: int) -> int:
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
        return U2L_TABLE[ulawbyte & 0xFF]
    
    @staticmethod
    def encode_pcm_to_ulaw(pcm_data: bytes) -> bytes:
        ulaw_data = bytearray()
        for i in range(0, len(pcm_data), 2):
            sample = struct.unpack('<h', pcm_data[i:i+2])[0]
            ulaw_data.append(AudioCodec.linear_to_ulaw(sample))
        return bytes(ulaw_data)
    
    @staticmethod
    def decode_ulaw_to_pcm(ulaw_data: bytes) -> bytes:
        pcm_data = bytearray()
        for byte in ulaw_data:
            sample = AudioCodec.ulaw_to_linear(byte)
            pcm_data.extend(struct.pack('<h', sample))
        return bytes(pcm_data)
    
    @staticmethod
    def xor_encrypt(data: bytes, key: int = 0xAA) -> bytes:
        return bytes([b ^ key for b in data])
    
    @staticmethod
    def encode_audio_for_ham(pcm_data: bytes) -> bytes:
        ulaw_data = AudioCodec.encode_pcm_to_ulaw(pcm_data)
        return AudioCodec.xor_encrypt(ulaw_data)
    
    @staticmethod
    def decode_audio_from_ham(encrypted_data: bytes) -> bytes:
        ulaw_data = AudioCodec.xor_encrypt(encrypted_data)
        return AudioCodec.decode_ulaw_to_pcm(ulaw_data)


class ButterworthHighPass:
    def __init__(self, cutoff_freq: int = 200, sample_rate: int = 8000, gain_db: float = 6.0):
        self.cutoff_freq = cutoff_freq
        self.sample_rate = sample_rate
        self.gain_db = gain_db
        self.gain_linear = 10 ** (gain_db / 20)
        self.enabled = True
        self.x1 = self.x2 = self.y1 = self.y2 = 0
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
    
    def set_cutoff(self, cutoff_freq: int):
        if cutoff_freq == self.cutoff_freq:
            return
        self.cutoff_freq = cutoff_freq
        self._calculate_coefficients()
        self.x1 = self.x2 = self.y1 = self.y2 = 0
    
    def set_gain(self, gain_db: float):
        self.gain_db = gain_db
        self.gain_linear = 10 ** (gain_db / 20)
    
    def enable(self):
        self.enabled = True
        self.x1 = self.x2 = self.y1 = self.y2 = 0
    
    def disable(self):
        self.enabled = False
        self.x1 = self.x2 = self.y1 = self.y2 = 0


# ========== ROIP CLIENT ==========
class ROIPClient:
    def __init__(self):
        self.sock = None
        self.transmitting = False
        self.running = True
        self.connected = False
        self.packet_counter = 0
        self.channel = ROIP_CHANNEL
        
        self.audio = pyaudio.PyAudio()
        self.stream_in = None
        self.stream_out = None
        
        self.receive_thread = None
        self.keep_alive_thread = None
        self.transmit_thread = None
        
        self.packets_sent = 0
        self.packets_received = 0
        
        # Playback queue for incoming audio
        self.playback_queue = queue.Queue(maxsize=PLAYBACK_QUEUE_MAX)
        self.playback_buffer_size = PLAYBACK_BUFFER_SIZE
        self.playback_running = True
        
        self.codec = AudioCodec()
        
        self.highpass_filter = ButterworthHighPass(
            cutoff_freq=HIGHPASS_CUTOFF_FREQ,
            sample_rate=SAMPLE_RATE,
            gain_db=HIGHPASS_GAIN_DB
        )
        
        if not ENABLE_HIGHPASS_FILTER:
            self.highpass_filter.disable()
        
        self._create_socket()
    
    def _create_socket(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.5)
    
    def set_gain(self, gain_db: float):
        self.highpass_filter.set_gain(gain_db)
    
    def get_filter_info(self):
        return {
            'type': 'BUTTERWORTH',
            'enabled': self.highpass_filter.enabled,
            'cutoff': self.highpass_filter.cutoff_freq,
            'gain': self.highpass_filter.gain_db
        }
    
    def init_audio(self) -> bool:
        try:
            self.stream_in = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=SAMPLE_RATE,
                input=True,
                frames_per_buffer=AUDIO_CHUNK
            )
            self.stream_out = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=SAMPLE_RATE,
                output=True,
                frames_per_buffer=AUDIO_CHUNK
            )
            return True
        except Exception as e:
            print(f"Audio init error: {e}")
            return False
    
    def make_voice_header(self, buffer: bytearray):
        for i in range(8):
            buffer[i] = 0
        buffer[0] = self.packet_counter & 0xFF
        self.packet_counter = (self.packet_counter + 1) & 0xFF
        buffer[1] = 10
        buffer[3] = 5
        buffer[4] = self.channel * 2 + 1
        buffer[6] = 0
    
    def send_keep_alive(self):
        while self.running and self.connected:
            try:
                if not self.sock:
                    break
                packet = bytearray(8)
                packet[0] = 0
                packet[1] = 10
                packet[2] = 0
                packet[3] = 0
                packet[4] = self.channel * 2
                packet[5] = 0
                packet[6] = 0
                packet[7] = 0
                self.sock.sendto(bytes(packet), (SERVER_IP, SERVER_PORT))
                for _ in range(KEEP_ALIVE_INTERVAL):
                    if not self.running or not self.connected:
                        break
                    time.sleep(1)
            except Exception as e:
                if self.running:
                    print(f"Keep-alive error: {e}")
                time.sleep(5)
    
    def start_transmission(self):
        if not self.transmitting and self.running:
            self.transmitting = True
            self.transmit_thread = threading.Thread(target=self.transmit_audio, daemon=True)
            self.transmit_thread.start()
    
    def stop_transmission(self):
        if self.transmitting:
            self.transmitting = False
            if self.transmit_thread:
                self.transmit_thread.join(timeout=2)
    
    def transmit_audio(self):
        next_send_time = time.time()
        while self.transmitting and self.running:
            try:
                if not self.sock:
                    break
                pcm_data = self.stream_in.read(AUDIO_CHUNK, exception_on_overflow=False)
                pcm_data = self.highpass_filter.process(pcm_data)
                encrypted_data = self.codec.encode_audio_for_ham(pcm_data)
                packet = bytearray(BUFFER_SIZE)
                self.make_voice_header(packet)
                packet[8:8+len(encrypted_data)] = encrypted_data[:800]
                self.sock.sendto(bytes(packet), (SERVER_IP, SERVER_PORT))
                self.packets_sent += 1
                current_time = time.time()
                sleep_time = next_send_time - current_time
                if sleep_time > 0:
                    time.sleep(sleep_time)
                elif sleep_time < -PACKET_INTERVAL:
                    next_send_time = current_time
                next_send_time += PACKET_INTERVAL
            except Exception as e:
                if self.running and self.transmitting:
                    print(f"Transmission error: {e}")
                break
    
    def playback_worker(self):
        """Separate thread for playing audio from queue"""
        buffer_accumulator = []
        
        while self.playback_running and self.running:
            try:
                # Try to get packet from queue with timeout
                try:
                    pcm_data = self.playback_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                # Accumulate packets if buffer size > 1
                if self.playback_buffer_size > 1:
                    buffer_accumulator.append(pcm_data)
                    if len(buffer_accumulator) >= self.playback_buffer_size:
                        # Play all accumulated packets
                        for data in buffer_accumulator:
                            if self.stream_out and self.stream_out.is_active():
                                self.stream_out.write(data)
                        buffer_accumulator = []
                else:
                    # Play immediately
                    if self.stream_out and self.stream_out.is_active():
                        self.stream_out.write(pcm_data)
                        
            except Exception as e:
                print(f"Playback error: {e}")
        
        # Play remaining packets before exit
        for data in buffer_accumulator:
            try:
                if self.stream_out and self.stream_out.is_active():
                    self.stream_out.write(data)
            except:
                pass
    
    def receive_audio(self):
        """Receive audio from server and add to queue"""
        voice_start_time = None
        voice_active = False
        
        # Start playback worker thread
        playback_thread = threading.Thread(target=self.playback_worker, daemon=True)
        playback_thread.start()
        
        while self.running:
            try:
                if not self.sock:
                    break
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
                if not self.running:
                    break
                    
                if len(data) == 808:
                    if not voice_active:
                        voice_start_time = time.time()
                        voice_active = True
                        print(f"{time.strftime('%H:%M:%S')} RECEIVE ...", end='', flush=True)
                    
                    audio_data = data[8:808]
                    pcm_data = self.codec.decode_audio_from_ham(audio_data)
                    
                    # Add to queue for playback (non-blocking)
                    try:
                        self.playback_queue.put_nowait(pcm_data)
                    except queue.Full:
                        # Queue is full, remove oldest and add new
                        try:
                            self.playback_queue.get_nowait()
                            self.playback_queue.put_nowait(pcm_data)
                        except:
                            pass
                    
                    self.packets_received += 1
                    
            except socket.timeout:
                if voice_active:
                    elapsed = time.time() - voice_start_time
                    print(f" {elapsed:.1f}s")
                    voice_active = False
                continue
            except OSError as e:
                if self.running and hasattr(e, 'winerror') and e.winerror != 10038:
                    print(f"Receive error: {e}")
                break
            except Exception as e:
                if self.running:
                    print(f"Receive error: {e}")
                break
        
        if voice_active:
            elapsed = time.time() - voice_start_time
            print(f" {elapsed:.1f}s")
        
        self.playback_running = False
        playback_thread.join(timeout=2)
    
    def connect(self) -> bool:
        try:
            if not self.sock:
                self._create_socket()
            reg_packet = bytearray(8)
            reg_packet[0] = 0
            reg_packet[1] = 10
            reg_packet[2] = 0
            reg_packet[3] = 0
            reg_packet[4] = self.channel * 2
            reg_packet[5] = 0
            reg_packet[6] = 0
            reg_packet[7] = 0
            self.sock.sendto(bytes(reg_packet), (SERVER_IP, SERVER_PORT))
            self.connected = True
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            return False
    
    def disconnect(self):
        self.running = False
        self.connected = False
        self.transmitting = False
        self.playback_running = False
        
        try:
            if self.sock:
                disc_packet = bytearray(8)
                disc_packet[1] = 255
                self.sock.sendto(bytes(disc_packet), (SERVER_IP, SERVER_PORT))
        except:
            pass
        try:
            if self.sock:
                self.sock.close()
                self.sock = None
        except:
            pass
        try:
            if self.stream_in:
                self.stream_in.stop_stream()
                self.stream_in.close()
        except:
            pass
        try:
            if self.stream_out:
                self.stream_out.stop_stream()
                self.stream_out.close()
        except:
            pass
        try:
            self.audio.terminate()
        except:
            pass




    def set_channel(self, channel: int):
        """Change channel (1-8)"""
        if 0 <= channel <= 9:
            self.channel = channel
            self.packet_counter = 0
            print(f"Channel changed to {channel}")
        else:
            print(f"Invalid channel: {channel}. Use 1-8")
         
    
    def run(self) -> bool:
        print("=== ROIP Client ===")
        print(f"Server: {SERVER_IP}:{SERVER_PORT}")
        print(f"Channel: {self.channel}")
        
        if not self.init_audio():
            return False
        if not self.connect():
            return False
        
        self.receive_thread = threading.Thread(target=self.receive_audio, daemon=True)
        self.keep_alive_thread = threading.Thread(target=self.send_keep_alive, daemon=True)
        self.receive_thread.start()
        self.keep_alive_thread.start()
        
        return True