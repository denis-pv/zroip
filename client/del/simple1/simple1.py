"""
Minimal ROIP Client
Press SPACE to talk, ESC to exit, +/- to adjust gain
"""

import sys
import threading
import time
import msvcrt
import ctypes
from ctypes import wintypes
from roip_client import ROIPClient

def main():
    try:
        import pyaudio
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("pip install pyaudio")
        return
    
    client = ROIPClient()
    if not client.run():
        print("Failed to start client")
        return
    
    space_pressed = False
    
    print("Ready. Press SPACE to talk, ESC to exit")
    print("+ / - to adjust gain")
    print()
    
    try:
        while client.running:
            if msvcrt.kbhit():
                key = msvcrt.getch()
                
                if key == b' ':  # Space pressed
                    if not space_pressed:
                        space_pressed = True
                        print(f"{time.strftime('%H:%M:%S')} TRANSMIT ... ", end='', flush=True)
                      
                        client.start_transmission()
                
                elif key == b'\x1b':  # ESC
                    print("Exiting...")
                    break
                
                elif key == b'+' or key == b'=':  # Increase gain
                    current_gain = client.highpass_filter.gain_db
                    new_gain = min(24, current_gain + 1)
                    client.set_gain(new_gain)
                    print(f"Gain: {new_gain:.1f} dB")
                
                elif key == b'-' or key == b'_':  # Decrease gain
                    current_gain = client.highpass_filter.gain_db
                    new_gain = max(0, current_gain - 1)
                    client.set_gain(new_gain)
                    print(f"Gain: {new_gain:.1f} dB")
            
            # Check if space is still pressed
            if space_pressed:
                user32 = ctypes.windll.user32
                VK_SPACE = 0x20
                
                if not (user32.GetAsyncKeyState(VK_SPACE) & 0x8000):
                    space_pressed = False
                    duration = time.time() - self.transmit_start_time
                    print(f"END ({duration:.1f}s)", flush=True)
                    client.stop_transmission()
            
            time.sleep(0.02)
            
    except KeyboardInterrupt:
        print("Interrupted")
    finally:
        client.disconnect()
        print("Client stopped")

if __name__ == "__main__":
    main()