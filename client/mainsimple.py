"""
Simple ROIP Client
Space - PTT (when window is focused)
+ / - - Adjust gain
ESC - Exit
"""

import sys
import threading
import time
import msvcrt
from roip_client import ROIPClient


class ROIPController:
    def __init__(self):
        self.client = ROIPClient()
        self.running = True
        self.ptt_pressed = False
        
        # Запускаем клиент
        if not self.client.run():
            print("Failed to start client")
            sys.exit(1)
        
        filter_info = self.client.get_filter_info()
        print("\n=== Controls ===")
        print("SPACE - Press and hold to transmit")
        print("+     - Increase gain")
        print("-     - Decrease gain")
        print("ESC   - Exit")
        print(f"\nCurrent gain: {filter_info['gain']:.1f} dB")
        print("================\n")
    
    def run(self):
        """Main keyboard loop"""
        while self.running:
            # Check for key press
            if msvcrt.kbhit():
                key = msvcrt.getch()
                
                # ESC
                if key == b'\x1b':
                    print("\nExiting...")
                    break
                
                # Space (ASCII 32)
                elif key == b' ':
                    if not self.ptt_pressed:
                        self.ptt_pressed = True
                        print("TRANSMIT STARTED")
                        threading.Thread(target=self.client.start_transmission, daemon=True).start()
                
                # + (ASCII 43) or = (ASCII 61)
                elif key == b'+' or key == b'=':
                    current_gain = self.client.highpass_filter.gain_db
                    new_gain = min(24, current_gain + 1)
                    self.client.set_filter_gain(new_gain)
                    print(f"Gain: {new_gain:.1f} dB")
                
                # - (ASCII 45)
                elif key == b'-':
                    current_gain = self.client.highpass_filter.gain_db
                    new_gain = max(0, current_gain - 1)
                    self.client.set_filter_gain(new_gain)
                    print(f"Gain: {new_gain:.1f} dB")
            
            # Check for space release
            if self.ptt_pressed and not msvcrt.kbhit():
                # Need to check if space is still pressed
                import ctypes
                from ctypes import wintypes
                
                user32 = ctypes.windll.user32
                VK_SPACE = 0x20
                
                if not (user32.GetAsyncKeyState(VK_SPACE) & 0x8000):
                    self.ptt_pressed = False
                    print("TRANSMIT STOPPED")
                    threading.Thread(target=self.client.stop_transmission, daemon=True).start()
            
            time.sleep(0.02)
        
        # Cleanup
        self.client.running = False
        self.client.disconnect()


def main():
    """Main entry point"""
    try:
        import pyaudio
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("\nInstall required libraries:")
        print("pip install pyaudio")
        sys.exit(1)
    
    controller = ROIPController()
    controller.run()
    print("Client stopped")


if __name__ == "__main__":
    main()