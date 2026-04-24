"""
Simple ROIP Client
Press SPACE in window to transmit, release to stop
"""

import sys
import threading
import time
import pyaudio
import socket
import struct
import math
from datetime import datetime
from pynput import keyboard as pynput_keyboard

# Configuration
SERVER_IP = "api.k240.ru"
SERVER_PORT = 1222
BUFFER_SIZE = 808
AUDIO_CHUNK = 800
SAMPLE_RATE = 8000
KEEP_ALIVE_INTERVAL = 15
PACKET_INTERVAL = 0.1
PLAYBACK_BUFFER_SIZE = 2

ROIP_CHANNEL = 1
CODEC_TYPE = 2
D_ROIP_G711HAM = 2

# Audio codec tables
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
    0,0,1,1,2,2,2,2,3,3,3,3,3,3,3,3,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,
    5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,5,
    6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,
    6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,6,
    7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,
    7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,
    7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,
    7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7
]


class AudioCodec:
    @staticmethod
    def linear_to_ulaw(sample):
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
    def ulaw_to_linear(ulawbyte):
        return U2L_TABLE[ulawbyte & 0xFF]
    
    @staticmethod
    def encode_pcm_to_ulaw(pcm_data):
        ulaw_data = bytearray()
        for i in range(0, len(pcm_data), 2):
            sample = struct.unpack('<h', pcm_data[i:i+2])[0]
            ulaw_data.append(AudioCodec.linear_to_ulaw(sample))
        return bytes(ulaw_data)
    
    @staticmethod
    def decode_ulaw_to_pcm(ulaw_data):
        pcm_data = bytearray()
        for byte in ulaw_data:
            sample = AudioCodec.ulaw_to_linear(byte)
            pcm_data.extend(struct.pack('<h', sample))
        return bytes(pcm_data)
    
    @staticmethod
    def xor_encrypt(data, key=0xAA):
        return bytes([b ^ key for b in data])
    
    @staticmethod
    def encode_audio_for_ham(pcm_data):
        ulaw_data = AudioCodec.encode_pcm_to_ulaw(pcm_data)
        return AudioCodec.xor_encrypt(ulaw_data)
    
    @staticmethod
    def decode_audio_from_ham(encrypted_data):
        ulaw_data = AudioCodec.xor_encrypt(encrypted_data)
        return AudioCodec.decode_ulaw_to_pcm(ulaw_data)


class ButterworthHighPass:
    def __init__(self, cutoff_freq=300, sample_rate=8000, gain_db=9.0):
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
    
    def process(self, data):
        if not self.enabled:
            return data
        samples = []
        for i in range(0, len(data), 2):
            x = struct.unpack('<h', data[i:i+2])[0]
            y = (self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2 
                 - self.a1 * self.y1 - self.a2 * self.y2)
            self.x2, self.x1 = self.x1, x
            self.y2, self.y1 = self.y1, y
            y = y * self.gain_linear
            y = max(-32768, min(32767, int(y)))
            samples.append(y)
        result = bytearray()
        for sample in samples:
            result.extend(struct.pack('<h', sample))
        return bytes(result)
    
    def set_cutoff(self, freq):
        self.cutoff_freq = freq
        self._calculate_coefficients()
        self.x1 = self.x2 = self.y1 = self.y2 = 0
    
    def set_gain(self, gain_db):
        self.gain_db = gain_db
        self.gain_linear = 10 ** (gain_db / 20)
    
    def enable(self):
        self.enabled = True
        self.x1 = self.x2 = self.y1 = self.y2 = 0
    
    def disable(self):
        self.enabled = False


class ROIPClient:
    def __init__(self):
        self.sock = None
        self.running = True
        self.transmitting = False
        self.connected = False
        self.packet_counter = 0
        self.channel = ROIP_CHANNEL
        self.audio = pyaudio.PyAudio()
        self.stream_in = None
        self.stream_out = None
        self.codec = AudioCodec()
        self.filter = ButterworthHighPass()
        
        self.playback_queue = []
        self.playback_queue_lock = threading.Lock()
        self.playback_buffer_size = PLAYBACK_BUFFER_SIZE
        
        self.voice_timer_start = None
        self.voice_active = False
        
        self._create_socket()
    
    def _create_socket(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.5)
    
    def init_audio(self):
        try:
            self.stream_in = self.audio.open(
                format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
                input=True, frames_per_buffer=AUDIO_CHUNK
            )
            self.stream_out = self.audio.open(
                format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
                output=True, frames_per_buffer=AUDIO_CHUNK
            )
            return True
        except Exception as e:
            print(f"Audio error: {e}")
            return False
    
    def make_voice_header(self, buffer):
        for i in range(8):
            buffer[i] = 0
        buffer[0] = self.packet_counter & 0xFF
        self.packet_counter = (self.packet_counter + 1) & 0xFF
        buffer[1] = 10
        buffer[3] = 5
        buffer[4] = self.channel * 2 + 1
    
    def send_keep_alive(self):
        while self.running and self.connected:
            try:
                if not self.sock:
                    break
                packet = bytearray(8)
                packet[1] = 10
                packet[4] = self.channel * 2
                self.sock.sendto(bytes(packet), (SERVER_IP, SERVER_PORT))
                time.sleep(KEEP_ALIVE_INTERVAL)
            except:
                time.sleep(5)
    
    def start_transmission(self):
        if not self.transmitting and self.running:
            self.transmitting = True
            threading.Thread(target=self._transmit_loop, daemon=True).start()
    
    def stop_transmission(self):
        self.transmitting = False
    
    def _transmit_loop(self):
        next_send_time = time.time()
        while self.transmitting and self.running:
            try:
                if not self.sock:
                    break
                pcm_data = self.stream_in.read(AUDIO_CHUNK, exception_on_overflow=False)
                pcm_data = self.filter.process(pcm_data)
                encrypted_data = self.codec.encode_audio_for_ham(pcm_data)
                packet = bytearray(BUFFER_SIZE)
                self.make_voice_header(packet)
                packet[8:8+len(encrypted_data)] = encrypted_data[:800]
                self.sock.sendto(bytes(packet), (SERVER_IP, SERVER_PORT))
                
                current_time = time.time()
                sleep_time = next_send_time - current_time
                if sleep_time > 0:
                    time.sleep(sleep_time)
                next_send_time += PACKET_INTERVAL
            except Exception as e:
                print(f"TX error: {e}")
                break
    
    def _log_voice_start(self):
        now = datetime.now()
        print(f"{now.strftime('%H:%M:%S')} VOICE ...", end='', flush=True)
    
    def _log_voice_end(self, duration):
        now = datetime.now()
        print(f"\r{now.strftime('%H:%M:%S')} VOICE {duration:.1f}s")
    
    def receive_audio(self):
        last_voice_time = 0
        voice_duration = 0
        voice_start_time = 0
        voice_active = False
        
        while self.running:
            try:
                if not self.sock:
                    break
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
                
                if len(data) == 808:
                    audio_data = data[8:808]
                    pcm_data = self.codec.decode_audio_from_ham(audio_data)
                    
                    with self.playback_queue_lock:
                        self.playback_queue.append(pcm_data)
                        if len(self.playback_queue) > 50:
                            self.playback_queue.pop(0)
                        if len(self.playback_queue) >= self.playback_buffer_size:
                            to_play = self.playback_queue.pop(0)
                            if self.stream_out and self.stream_out.is_active():
                                self.stream_out.write(to_play)
                    
                    current_time = time.time()
                    if not voice_active:
                        voice_active = True
                        voice_start_time = current_time
                        self._log_voice_start()
                    last_voice_time = current_time
                    
            except socket.timeout:
                if voice_active:
                    current_time = time.time()
                    if current_time - last_voice_time >= 2:
                        voice_active = False
                        duration = last_voice_time - voice_start_time
                        self._log_voice_end(duration)
                continue
            except Exception as e:
                if self.running:
                    print(f"RX error: {e}")
                break
        
        if voice_active:
            duration = last_voice_time - voice_start_time
            self._log_voice_end(duration)
    
    def connect(self):
        try:
            if not self.sock:
                self._create_socket()
            reg_packet = bytearray(8)
            reg_packet[1] = 10
            reg_packet[4] = self.channel * 2
            self.sock.sendto(bytes(reg_packet), (SERVER_IP, SERVER_PORT))
            self.connected = True
            print(f"Connected to {SERVER_IP}:{SERVER_PORT}")
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            return False
    
    def disconnect(self):
        self.running = False
        self.connected = False
        self.transmitting = False
        try:
            if self.sock:
                disc_packet = bytearray(8)
                disc_packet[1] = 255
                self.sock.sendto(bytes(disc_packet), (SERVER_IP, SERVER_PORT))
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
    
    def run(self):
        if not self.init_audio():
            return False
        if not self.connect():
            return False
        
        threading.Thread(target=self.receive_audio, daemon=True).start()
        threading.Thread(target=self.send_keep_alive, daemon=True).start()
        return True


class SimpleController:
    def __init__(self):
        self.client = ROIPClient()
        self.running = True
        self.space_pressed = False
        self.gain = 9.0
    
    def on_press(self, key):
        if key == pynput_keyboard.Key.space:
            if not self.space_pressed:
                self.space_pressed = True
                print("\nTRANSMIT STARTED")
                self.client.start_transmission()
        elif key == pynput_keyboard.KeyCode.from_char('+'):
            self.gain = min(24, self.gain + 1)
            self.client.filter.set_gain(self.gain)
            print(f"Gain: {self.gain:.1f} dB")
        elif key == pynput_keyboard.KeyCode.from_char('-'):
            self.gain = max(0, self.gain - 1)
            self.client.filter.set_gain(self.gain)
            print(f"Gain: {self.gain:.1f} dB")
        elif key == pynput_keyboard.Key.esc:
            self.running = False
            return False
    
    def on_release(self, key):
        if key == pynput_keyboard.Key.space:
            if self.space_pressed:
                self.space_pressed = False
                print("TRANSMIT STOPPED")
                self.client.stop_transmission()
    
    def run(self):
        if not self.client.run():
            print("Failed to start client")
            return
        
        print("\n=== Simple ROIP Client ===")
        print("SPACE - Press and hold to transmit")
        print("+ / - - Adjust gain")
        print("ESC - Exit")
        print("========================\n")
        
        listener = pynput_keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release
        )
        listener.start()
        
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.client.disconnect()
            print("Client stopped")


def main():
    try:
        import pyaudio
        from pynput import keyboard
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("pip install pyaudio pynput")
        sys.exit(1)
    
    controller = SimpleController()
    controller.run()

if __name__ == "__main__":
    main()