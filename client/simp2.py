"""
Simple ROIP Client
Space - PTT, +/- for gain
"""

import sys
import threading
import time
import msvcrt
from datetime import datetime
from roip_client import ROIPClient

# ========== CONFIGURATION ==========
ROIP_CHANNEL = 1

class ROIPController:
    def __init__(self):
        self.client = ROIPClient()
        self.client.channel = ROIP_CHANNEL
        
        self.running = True
        self.ptt_active = False
        self.voice_active = False
        self.voice_start_time = None
        self.voice_end_time = None
        self.last_voice_time = 0
        
        # Gain control
        self.gain_step = 1
    
    def on_ptt_press(self):
        """Start transmission"""
        if not self.ptt_active and self.client.running:
            self.ptt_active = True
            print("TRANSMIT STARTED")
            threading.Thread(target=self.client.start_transmission, daemon=True).start()
    
    def on_ptt_release(self):
        """Stop transmission"""
        if self.ptt_active:
            self.ptt_active = False
            print("TRANSMIT STOPPED")
            threading.Thread(target=self.client.stop_transmission, daemon=True).start()
    
    def on_voice_start(self):
        """Called when voice starts arriving"""
        now = datetime.now()
        self.voice_active = True
        self.voice_start_time = now
        print(f"{now.strftime('%H:%M:%S')} VOICE ...", end='', flush=True)
    
    def on_voice_stop(self):
        """Called when voice stops"""
        if self.voice_active:
            now = datetime.now()
            self.voice_end_time = now
            duration = (self.voice_end_time - self.voice_start_time).total_seconds()
            print(f" {duration:.1f}s", flush=True)
            self.voice_active = False
    
    def check_voice_timeout(self):
        """Check if voice has stopped for more than 2 seconds"""
        if self.voice_active:
            time_since_last = time.time() - self.last_voice_time
            if time_since_last >= 2.0:
                self.on_voice_stop()
    
    def decrease_gain(self):
        """Decrease gain by 1 dB"""
        current_gain = self.client.highpass_filter.gain_db
        new_gain = max(0, current_gain - self.gain_step)
        self.client.set_filter_gain(new_gain)
        print(f"Gain: {new_gain:.1f} dB")
    
    def increase_gain(self):
        """Increase gain by 1 dB"""
        current_gain = self.client.highpass_filter.gain_db
        new_gain = min(24, current_gain + self.gain_step)
        self.client.set_filter_gain(new_gain)
        print(f"Gain: {new_gain:.1f} dB")
    
    def monitor_voice(self):
        """Monitor incoming voice and update timing"""
        while self.running:
            if hasattr(self.client, 'packets_received'):
                current_time = time.time()
                if self.client.packets_received > 0:
                    self.last_voice_time = current_time
                    if not self.voice_active:
                        self.on_voice_start()
            self.check_voice_timeout()
            time.sleep(0.1)
    
    def run(self):
        """Run the controller"""
        if not self.client.run():
            print("Failed to start client")
            return
        
        filter_info = self.client.get_filter_info()
        
        print("\n=== ROIP Client ===")
        print(f"Channel: {ROIP_CHANNEL}")
        print(f"Filter: {filter_info['type']} [{ 'ON' if filter_info['enabled'] else 'OFF' }] {filter_info['cutoff']}Hz, {filter_info['gain']}dB")
        print()
        print("Controls:")
        print("  SPACE - Press and hold to transmit")
        print("  +     - Increase gain")
        print("  -     - Decrease gain")
        print("  ESC   - Exit")
        print()
        
        voice_monitor_thread = threading.Thread(target=self.monitor_voice, daemon=True)
        voice_monitor_thread.start()
        
        space_pressed = False
        
        try:
            while self.running:
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    
                    if key == b' ':
                        if not space_pressed:
                            space_pressed = True
                            self.on_ptt_press()
                    elif key == b'+' or key == b'=':
                        self.increase_gain()
                    elif key == b'-' or key == b'_':
                        self.decrease_gain()
                    elif key == b'\x1b':
                        print("\nExiting...")
                        break
                else:
                    if space_pressed:
                        space_pressed = False
                        self.on_ptt_release()
                
                time.sleep(0.02)
                
        except KeyboardInterrupt:
            print("\nInterrupted")
        finally:
            self.on_exit()
    
    def on_exit(self):
        """Exit handler"""
        print("Shutting down...")
        self.running = False
        if self.ptt_active:
            self.client.stop_transmission()
        self.client.running = False
        self.client.disconnect()

def main():
    """Main entry point"""
    try:
        import pyaudio
    except ImportError as e:
        print(f"[X] Missing dependency: {e}")
        print("\nInstall required libraries:")
        print("pip install pyaudio")
        sys.exit(1)
    
    controller = ROIPController()
    controller.run()
    print("Client stopped")

if __name__ == "__main__":
    main()