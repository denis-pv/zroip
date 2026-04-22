"""
ROIP Client for HAM Radio
Supports mu-law encoding/decoding with XOR encryption
Packet size: 800 bytes audio data, sent every 100ms
"""

import socket
import threading
import time
import pyaudio
from datetime import datetime
from audio_codec import AudioCodec, SimpleHighPassFilter, ButterworthHighPass

# ========== CONFIGURATION ==========
SERVER_IP = "api.k240.ru"  # Change to your server IP
SERVER_PORT = 1222
BUFFER_SIZE = 808  # 8 bytes header + 800 bytes audio
AUDIO_CHUNK = 800   # 800 samples = 100ms audio at 8000 Hz
SAMPLE_RATE = 8000  # 8 kHz for VoIP
KEEP_ALIVE_INTERVAL = 15  # seconds
PACKET_INTERVAL = 0.1  # 100 milliseconds between packets

# Codec selection (default HAM)
CODEC_TYPE = 2  # D_ROIP_G711HAM

# High-pass filter settings
ENABLE_HIGHPASS_FILTER = True
HIGHPASS_CUTOFF_FREQ = 300
HIGHPASS_GAIN_DB = 9.0
FILTER_TYPE = "butterworth"  # "rc" or "butterworth"

# Playback buffer settings
PLAYBACK_BUFFER_SIZE = 2
PLAYBACK_QUEUE_MAX = 50

# Packet types
D_ROIPC_G711 = 1
D_ROIP_G711HAM = 2
D_WAIS_G711 = 3
D_GSM = 4
D_GSMHAM = 5
D_FRSF_JHAM = 6


class ROIPClient:
    def __init__(self):
        self.sock = None
        self.transmitting = False
        self.running = True
        self.connected = False
        self.packet_counter = 0
        self.channel = 1
        
        # Audio
        self.audio = pyaudio.PyAudio()
        self.stream_in = None
        self.stream_out = None
        
        # Threads
        self.keep_alive_thread = None
        self.receive_thread = None
        self.transmit_thread = None
        
        # Statistics
        self.last_ack_time = None
        self.packets_sent = 0
        self.packets_received = 0
        
        # Playback buffer
        self.playback_queue = []
        self.playback_queue_lock = threading.Lock()
        self.playback_buffer_size = PLAYBACK_BUFFER_SIZE
        
        # Codec
        self.codec = AudioCodec()
        
        # Filters
        self.rc_filter = SimpleHighPassFilter(
            cutoff_freq=HIGHPASS_CUTOFF_FREQ,
            sample_rate=SAMPLE_RATE,
            gain_db=HIGHPASS_GAIN_DB
        )
        
        self.butterworth_filter = ButterworthHighPass(
            cutoff_freq=HIGHPASS_CUTOFF_FREQ,
            sample_rate=SAMPLE_RATE,
            gain_db=HIGHPASS_GAIN_DB
        )
        
        # Select active filter
        self.filter_type = FILTER_TYPE
        if self.filter_type == "butterworth":
            self.highpass_filter = self.butterworth_filter
        else:
            self.highpass_filter = self.rc_filter
        
        if ENABLE_HIGHPASS_FILTER:
            self.highpass_filter.enable()
        else:
            self.highpass_filter.disable()
        
        # Create socket
        self._create_socket()
        
        print(f"Initialized with {self.filter_type.upper()} filter")
        print(f"Playback buffer size: {self.playback_buffer_size} packets")
    
    def _create_socket(self):
        """Create and configure UDP socket"""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.5)  # Short timeout for faster shutdown
    
    def switch_filter_type(self):
        """Switch between RC and Butterworth filters"""
        was_enabled = self.highpass_filter.enabled
        current_cutoff = self.highpass_filter.cutoff_freq
        current_gain = self.highpass_filter.gain_db
        
        if self.filter_type == "butterworth":
            self.filter_type = "rc"
            self.highpass_filter = self.rc_filter
            print(f"\nSwitched to RC FILTER")
        else:
            self.filter_type = "butterworth"
            self.highpass_filter = self.butterworth_filter
            print(f"\nSwitched to BUTTERWORTH FILTER")
        
        self.highpass_filter.set_cutoff(current_cutoff)
        self.highpass_filter.set_gain(current_gain)
        if was_enabled:
            self.highpass_filter.enable()
        else:
            self.highpass_filter.disable()
        
        status = "ON" if self.highpass_filter.enabled else "OFF"
        print(f"Filter: {status}, Cutoff: {current_cutoff}Hz, Gain: {current_gain}dB")
    
    def set_filter_cutoff(self, freq: int):
        """Change filter cutoff frequency"""
        if not self.running:
            return
        self.highpass_filter.set_cutoff(freq)
        self.rc_filter.set_cutoff(freq)
        self.butterworth_filter.set_cutoff(freq)
    
    def set_filter_gain(self, gain_db: float):
        """Change filter gain"""
        if not self.running:
            return
        self.highpass_filter.set_gain(gain_db)
        self.rc_filter.set_gain(gain_db)
        self.butterworth_filter.set_gain(gain_db)
    
    def set_filter_enabled(self, enabled: bool):
        """Enable/disable filter"""
        if not self.running:
            return
        if enabled:
            self.highpass_filter.enable()
        else:
            self.highpass_filter.disable()
    
    def get_filter_info(self):
        """Get current filter information"""
        return {
            'type': self.filter_type.upper(),
            'enabled': self.highpass_filter.enabled,
            'cutoff': self.highpass_filter.cutoff_freq,
            'gain': self.highpass_filter.gain_db
        }
    
    def init_audio(self) -> bool:
        """Initialize audio devices"""
        try:
            self.stream_in = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=SAMPLE_RATE,
                input=True,
                frames_per_buffer=AUDIO_CHUNK
            )
            print("Microphone initialized (default device)")
            
            self.stream_out = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=SAMPLE_RATE,
                output=True,
                frames_per_buffer=AUDIO_CHUNK
            )
            print("Speaker initialized (default device)")
            return True
        except Exception as e:
            print(f"Audio init error: {e}")
            return False
    
    def make_voice_header(self, buffer: bytearray, packet_type: int):
        """Create voice packet header (8 bytes)"""
        for i in range(8):
            buffer[i] = 0
        
        buffer[0] = self.packet_counter & 0xFF
        self.packet_counter = (self.packet_counter + 1) & 0xFF
        
        if packet_type == D_ROIPC_G711:
            buffer[1] = 5
            buffer[3] = 5
            buffer[4] = self.channel * 2 + 1
            buffer[6] = 0
        elif packet_type == D_WAIS_G711:
            buffer[1] = 5
            buffer[3] = 5
            buffer[4] = self.channel * 2 + 1
            buffer[6] = 1
        elif packet_type == D_ROIP_G711HAM:
            buffer[1] = 10
            buffer[3] = 5
            buffer[4] = self.channel * 2 + 1
            buffer[6] = 0
        elif packet_type == D_GSM:
            buffer[1] = 1
            buffer[3] = 10
            buffer[4] = self.channel * 2 + 1
            buffer[6] = 1
        elif packet_type == D_GSMHAM:
            buffer[1] = 2
            buffer[3] = 10
            buffer[4] = self.channel * 2 + 1
            buffer[6] = 0
    
    def send_keep_alive(self):
        """Send keep-alive packet every KEEP_ALIVE_INTERVAL seconds"""
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
                print(f"Keep-alive sent (channel {self.channel})")
                
                for _ in range(KEEP_ALIVE_INTERVAL):
                    if not self.running or not self.connected:
                        break
                    time.sleep(1)
            except Exception as e:
                if self.running:
                    print(f"Keep-alive error: {e}")
                time.sleep(5)
    
    def start_transmission(self):
        """Start audio transmission"""
        if not self.transmitting and self.running:
            self.transmitting = True
            self.transmit_thread = threading.Thread(target=self.transmit_audio, daemon=True)
            self.transmit_thread.start()
    
    def stop_transmission(self):
        """Stop audio transmission"""
        if self.transmitting:
            self.transmitting = False
            if self.transmit_thread:
                self.transmit_thread.join(timeout=2)
    
    def transmit_audio(self):
        """Transmit audio from microphone to server"""
        next_send_time = time.time()
        packets_in_cycle = 0
        cycle_start_time = time.time()
        
        filter_info = self.get_filter_info()
        print(f"Filter: {filter_info['type']} [{ 'ON' if filter_info['enabled'] else 'OFF' }] {filter_info['cutoff']}Hz, {filter_info['gain']}dB")
        
        while self.transmitting and self.running:
            try:
                if not self.sock:
                    break
                    
                pcm_data = self.stream_in.read(AUDIO_CHUNK, exception_on_overflow=False)
                
                # Apply filter
                pcm_data = self.highpass_filter.process(pcm_data)
                
                # Encode
                if CODEC_TYPE == D_ROIP_G711HAM:
                    encrypted_data = self.codec.encode_audio_for_ham(pcm_data)
                else:
                    encrypted_data = self.codec.encode_pcm_to_ulaw(pcm_data)
                
                packet = bytearray(BUFFER_SIZE)
                self.make_voice_header(packet, CODEC_TYPE)
                packet[8:8+len(encrypted_data)] = encrypted_data[:800]
                
                self.sock.sendto(bytes(packet), (SERVER_IP, SERVER_PORT))
                self.packets_sent += 1
                packets_in_cycle += 1
                
                if self.packets_sent % 50 == 0:
                    current_time = time.time()
                    elapsed = current_time - cycle_start_time
                    rate = packets_in_cycle / elapsed if elapsed > 0 else 0
                    print(f"Sent: {self.packets_sent} packets, Rate: {rate:.1f} pkt/s")
                    packets_in_cycle = 0
                    cycle_start_time = current_time
                
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
        
        print("Transmission thread finished")
    
    def receive_audio(self):
        """Receive audio from server and play with buffering"""
        print(f"Waiting for incoming audio... (buffer size: {self.playback_buffer_size} packets)")
        
        while self.running:
            try:
                if not self.sock:
                    break
                    
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
                
                if not self.running:
                    break
                
                if len(data) == 808:  # Voice packet
                    audio_data = data[8:808]
                    
                    if CODEC_TYPE == D_ROIP_G711HAM:
                        pcm_data = self.codec.decode_audio_from_ham(audio_data)
                    else:
                        pcm_data = self.codec.decode_ulaw_to_pcm(audio_data)
                    
                    with self.playback_queue_lock:
                        self.playback_queue.append(pcm_data)
                        
                        if len(self.playback_queue) > PLAYBACK_QUEUE_MAX:
                            self.playback_queue.pop(0)
                        
                        if len(self.playback_queue) >= self.playback_buffer_size:
                            to_play = self.playback_queue.pop(0)
                            if self.stream_out and self.stream_out.is_active():
                                self.stream_out.write(to_play)
                    
                    self.packets_received += 1
                    
                    if self.packets_received % 50 == 0:
                        with self.playback_queue_lock:
                            queue_size = len(self.playback_queue)
                        print(f"Received: {self.packets_received} packets, Queue: {queue_size}")
                
                elif len(data) == 8:  # ACK packet
                    self.last_ack_time = datetime.now()
                    
            except socket.timeout:
                continue
            except OSError as e:
                if self.running:
                    if e.winerror != 10038:  # Not a socket error
                        print(f"Receive error: {e}")
                break
            except Exception as e:
                if self.running:
                    print(f"Receive error: {e}")
                break
    
    def connect(self) -> bool:
        """Connect to ROIP server"""
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
            print(f"Connected to {SERVER_IP}:{SERVER_PORT}")
            self.connected = True
            return True
            
        except Exception as e:
            print(f"Connection error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from server"""
        print("Disconnecting...")
        self.running = False
        self.connected = False
        self.transmitting = False
        
        # Send disconnect packet
        try:
            if self.sock:
                disc_packet = bytearray(8)
                disc_packet[1] = 255
                self.sock.sendto(bytes(disc_packet), (SERVER_IP, SERVER_PORT))
        except:
            pass
        
        # Close socket
        try:
            if self.sock:
                self.sock.close()
                self.sock = None
        except:
            pass
        
        # Close audio streams
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
    
    def debug_audio_devices(self):
        """Print audio device information"""
        print("\n=== Audio Devices ===")
        print("\nInput devices (microphones):")
        for i in range(self.audio.get_device_count()):
            dev_info = self.audio.get_device_info_by_index(i)
            if dev_info.get('maxInputChannels', 0) > 0:
                is_default = dev_info.get('defaultSampleRate', 0) > 0
                default_mark = " [DEFAULT]" if is_default else ""
                print(f"  [{i}]{default_mark} - {dev_info.get('name')}")
        
        print("\nOutput devices (speakers):")
        for i in range(self.audio.get_device_count()):
            dev_info = self.audio.get_device_info_by_index(i)
            if dev_info.get('maxOutputChannels', 0) > 0:
                is_default = dev_info.get('defaultSampleRate', 0) > 0
                default_mark = " [DEFAULT]" if is_default else ""
                print(f"  [{i}]{default_mark} - {dev_info.get('name')}")
        
        print("\n" + "="*30)
    
    def run(self) -> bool:
        """Run the ROIP client"""
        print("=== ROIP Client for HAM Radio ===")
        print(f"Server: {SERVER_IP}:{SERVER_PORT}")
        print(f"Channel: {self.channel}")
        print(f"Codec: {'HAM (mu-law + XOR)' if CODEC_TYPE == D_ROIP_G711HAM else 'Commercial (mu-law only)'}")
        print(f"Packet size: {AUDIO_CHUNK} samples ({PACKET_INTERVAL*1000:.0f}ms)")
        print(f"Playback buffer: {self.playback_buffer_size} packet(s)")
        print()
        
        if not self.init_audio():
            return False
        
        #self.debug_audio_devices()
        
        if not self.connect():
            return False
        
        self.receive_thread = threading.Thread(target=self.receive_audio, daemon=True)
        self.keep_alive_thread = threading.Thread(target=self.send_keep_alive, daemon=True)
        
        self.receive_thread.start()
        self.keep_alive_thread.start()
        
        print("\nClient ready.")
        return True