"""
Simple ROIP Client
Space - PTT, +/- for gain
"""

import sys
import threading
import time
import pyaudio
import socket
import struct
from datetime import datetime
from audio_codec import AudioCodec, ButterworthHighPass

# ========== CONFIGURATION ==========
SERVER_IP = "api.k240.ru"
SERVER_PORT = 1222
BUFFER_SIZE = 808
AUDIO_CHUNK = 800
SAMPLE_RATE = 8000
PACKET_INTERVAL = 0.1

CODEC_TYPE = 2
D_ROIP_G711HAM = 2

PLAYBACK_BUFFER_SIZE = 2


class SimpleROIPClient:
    def __init__(self):
        self.sock = None
        self.running = True
        self.transmitting = False
        self.packet_counter = 0
        self.channel = 1
        
        self.audio = pyaudio.PyAudio()
        self.stream_in = None
        self.stream_out = None
        
        self.playback_queue = []
        self.playback_queue_lock = threading.Lock()
        
        self.codec = AudioCodec()
        self.filter = ButterworthHighPass(cutoff_freq=300, sample_rate=SAMPLE_RATE, gain_db=9.0)
        
        # Voice activity tracking
        self.voice_active = False
        self.voice_start_time = None
        self.last_voice_time = None
        
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
            print(f"Audio init error: {e}")
            return False
    
    def set_gain(self, gain_db):
        self.filter.set_gain(gain_db)
        print(f"Gain: {gain_db:.1f} dB")
    
    def send_keep_alive(self):
        while self.running:
            try:
                if self.sock:
                    packet = bytearray(8)
                    packet[1] = 10
                    packet[4] = self.channel * 2
                    self.sock.sendto(bytes(packet), (SERVER_IP, SERVER_PORT))
                time.sleep(15)
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
                pcm_data = self.stream_in.read(AUDIO_CHUNK, exception_on_overflow=False)
                pcm_data = self.filter.process(pcm_data)
                
                ulaw_data = self.codec.encode_audio_for_ham(pcm_data)
                
                packet = bytearray(BUFFER_SIZE)
                packet[0] = self.packet_counter & 0xFF
                self.packet_counter = (self.packet_counter + 1) & 0xFF
                packet[1] = 10
                packet[3] = 5
                packet[4] = self.channel * 2 + 1
                packet[8:8+len(ulaw_data)] = ulaw_data[:800]
                
                self.sock.sendto(bytes(packet), (SERVER_IP, SERVER_PORT))
                
                current_time = time.time()
                sleep_time = next_send_time - current_time
                if sleep_time > 0:
                    time.sleep(sleep_time)
                next_send_time += PACKET_INTERVAL
                
            except Exception as e:
                print(f"Transmit error: {e}")
                break
    
    def _update_voice_status(self):
        current_time = datetime.now()
        if self.voice_active:
            elapsed = (current_time - self.voice_start_time).total_seconds()
            print(f"\r{current_time.strftime('%H:%M:%S')} VOICE ... {elapsed:.1f}s", end='', flush=True)
    
    def receive_audio(self):
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
                        if len(self.playback_queue) >= PLAYBACK_BUFFER_SIZE:
                            to_play = self.playback_queue.pop(0)
                            if self.stream_out and self.stream_out.is_active():
                                self.stream_out.write(to_play)
                    
                    # Voice activity tracking
                    now = datetime.now()
                    if not self.voice_active:
                        self.voice_active = True
                        self.voice_start_time = now
                        print(f"\n{now.strftime('%H:%M:%S')} VOICE ...", end='', flush=True)
                    else:
                        self.last_voice_time = now
                        self._update_voice_status()
                    
            except socket.timeout:
                # Check for voice timeout
                if self.voice_active and self.last_voice_time:
                    if (datetime.now() - self.last_voice_time).total_seconds() >= 2:
                        elapsed = (self.last_voice_time - self.voice_start_time).total_seconds()
                        print(f" {elapsed:.1f}s")
                        self.voice_active = False
                        self.voice_start_time = None
                        self.last_voice_time = None
                continue
            except OSError:
                break
            except Exception as e:
                print(f"Receive error: {e}")
                break
    
    def connect(self):
        try:
            reg_packet = bytearray(8)
            reg_packet[1] = 10
            reg_packet[4] = self.channel * 2
            self.sock.sendto(bytes(reg_packet), (SERVER_IP, SERVER_PORT))
            print(f"Connected to {SERVER_IP}:{SERVER_PORT}")
            return True
        except Exception as e:
            print(f"Connection error: {e}")
            return False
    
    def disconnect(self):
        self.running = False
        self.transmitting = False
        try:
            if self.sock:
                disc_packet = bytearray(8)
                disc_packet[1] = 255
                self.sock.sendto(bytes(disc_packet), (SERVER_IP, SERVER_PORT))
                self.sock.close()
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
        print("Disconnected")
    
    def run(self):
        if not self.init_audio():
            return False
        if not self.connect():
            return False
        
        threading.Thread(target=self.receive_audio, daemon=True).start()
        threading.Thread(target=self.send_keep_alive, daemon=True).start()
        
        print("\n=== Simple ROIP Client ===")
        print("SPACE - Press and hold to transmit")
        print("+ or = - Increase gain")
        print("- - Decrease gain")
        print("ESC - Exit")
        print("==========================")
        
        return True


def main():
    try:
        import keyboard
    except ImportError:
        print("Install: pip install keyboard pyaudio")
        sys.exit(1)
    
    client = SimpleROIPClient()
    if not client.run():
        return
    
    # Main keyboard loop
    space_pressed = False
    
    try:
        while client.running:
            # Check space
            if keyboard.is_pressed('space'):
                if not space_pressed:
                    space_pressed = True
                    client.start_transmission()
            else:
                if space_pressed:
                    space_pressed = False
                    client.stop_transmission()
            
            # Check gain controls
            if keyboard.is_pressed('+') or keyboard.is_pressed('='):
                current_gain = client.filter.gain_db
                client.set_gain(min(24, current_gain + 1))
                time.sleep(0.2)
            elif keyboard.is_pressed('-'):
                current_gain = client.filter.gain_db
                client.set_gain(max(0, current_gain - 1))
                time.sleep(0.2)
            
            # Check exit
            if keyboard.is_pressed('esc'):
                print("\nExiting...")
                client.running = False
                break
            
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        client.disconnect()
        print("Client stopped")


if __name__ == "__main__":
    main()