"""
Minimal ROIP Client with keyboard and Arduino PTT support
Press SPACE to talk, ESC to exit, +/- to adjust gain
"""


import sys
import threading
import time
import msvcrt
import ctypes
from ctypes import wintypes
from roip_client import ROIPClient
from ptt import ArduinoPTT


# Configuration

ENABLE_ARDUINO_PTT = True  # Set to False to use only keyboard
ARDUINO_PORT = None  # None = auto-detect, or specify like "COM3"
ARDUINO_BAUDRATE = 57600

def disable_quick_edit():
    """Disable QuickEdit mode for Windows console"""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        
        # Get current console mode
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        
        # Disable QuickEdit mode (0x0040) and enable extended flags
        mode.value &= ~0x0040
        kernel32.SetConsoleMode(handle, mode.value)
        return True
    except Exception as e:
        print(f"Failed to disable QuickEdit: {e}")
        return False

# Call this at the start of your program
if sys.platform == "win32":
    disable_quick_edit()

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
    transmit_start_time = None
    arduino_ptt = None
    
    # Initialize Arduino PTT if enabled
    if ENABLE_ARDUINO_PTT:
        try:
            arduino_ptt = ArduinoPTT(
                port=ARDUINO_PORT,
                baudrate=ARDUINO_BAUDRATE,
                auto_reconnect=True
            )
            arduino_ptt.start()
            print("Arduino PTT enabled")
        except Exception as e:
            print(f"Arduino init failed: {e}")
            print("Using keyboard only")
            arduino_ptt = None
    
    print("Ready. Press SPACE to talk, ESC to exit")
    print("+ / - to adjust gain")
    print()
    
    try:
        while client.running:
            # Check Arduino PTT state
            if arduino_ptt and arduino_ptt.is_pressed():
                if not space_pressed:
                    space_pressed = True
                    transmit_start_time = time.time()
                    print(f"{time.strftime('%H:%M:%S')} TRANSMIT ... ", end='', flush=True)
                    client.start_transmission()
            else:
                # Check keyboard only if Arduino button is not pressed
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    
                    if key == b' ':  # Space pressed
                        if not space_pressed:
                            space_pressed = True
                            transmit_start_time = time.time()
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
                
                # Check if space is still pressed (only when Arduino not active)
                if space_pressed and (not arduino_ptt or not arduino_ptt.is_pressed()):
                    user32 = ctypes.windll.user32
                    VK_SPACE = 0x20
                    
                    if not (user32.GetAsyncKeyState(VK_SPACE) & 0x8000):
                        space_pressed = False
                        if transmit_start_time:
                            duration = time.time() - transmit_start_time
                            print(f"END ({duration:.1f}s)")
                            transmit_start_time = None
                        else:
                            print("END")
                        client.stop_transmission()
            
            time.sleep(0.02)
            
    except KeyboardInterrupt:
        print("Interrupted")
    finally:
        if arduino_ptt:
            arduino_ptt.stop()
        client.disconnect()
        print("Client stopped")

if __name__ == "__main__":
    main()