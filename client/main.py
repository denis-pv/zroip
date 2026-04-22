"""
Main entry point for ROIP Client
Handles keyboard shortcuts: Alt+1 for PTT (Push-to-Talk)
Filter controls: F1, F2, F3, F4, F5, F6
"""

import sys
import threading
import time
import keyboard
from roip_client import ROIPClient

class ROIPController:
    def __init__(self):
        self.client = ROIPClient()
        self.running = True
        self.ptt_active = False
        self.transmission_lock = threading.Lock()
        
        # Для управления фильтром 
        self.filter_freq = 400
        self.last_filter_change = 0
        
        # Настройка горячих клавиш
        keyboard.add_hotkey('alt+1', self.on_ptt_press)
        keyboard.add_hotkey('alt+1', self.on_ptt_release, trigger_on_release=True)
        keyboard.add_hotkey('alt+space', self.on_ptt_press)
        keyboard.add_hotkey('alt+space', self.on_ptt_release, trigger_on_release=True)
        
        # Управление фильтром
        keyboard.add_hotkey('f1', self.toggle_filter)
        keyboard.add_hotkey('f2', self.decrease_cutoff)
        keyboard.add_hotkey('f3', self.increase_cutoff)
        keyboard.add_hotkey('f4', self.decrease_gain)
        keyboard.add_hotkey('f5', self.increase_gain)
        keyboard.add_hotkey('f6', self.switch_filter_type)
        
        # ESC для выхода
        keyboard.add_hotkey('esc', self.on_exit)
    
    def is_ptt_pressed(self) -> bool:
        """Check if PTT combination is currently pressed"""
        try:
            alt_pressed = keyboard.is_pressed('alt')
            grave_pressed = keyboard.is_pressed('1')
            alt_space = keyboard.is_pressed('alt') and keyboard.is_pressed('space')
            
            return (alt_pressed and grave_pressed) or alt_space
        except:
            return False
    
    def switch_filter_type(self):
        """Switch between RC and Butterworth filters"""
        self.client.switch_filter_type()
    
    def decrease_gain(self):
        """Decrease gain by 1 dB"""
        current_gain = self.client.highpass_filter.gain_db
        new_gain = max(0, current_gain - 1)
        self.client.set_filter_gain(new_gain)
        print(f" Gain: {new_gain:.1f} dB")

    def increase_gain(self):
        """Increase gain by 1 dB"""
        current_gain = self.client.highpass_filter.gain_db
        new_gain = min(24, current_gain + 1)
        self.client.set_filter_gain(new_gain)
        print(f" Gain: {new_gain:.1f} dB")
    
    def on_ptt_press(self):
        """Called when PTT key is pressed"""
        with self.transmission_lock:
            if not self.ptt_active and self.client.running:
                self.ptt_active = True
                print(" TRANSMIT STARTED")
                threading.Thread(target=self.client.start_transmission, daemon=True).start()
    
    def on_ptt_release(self):
        """Called when PTT key is released"""
        with self.transmission_lock:
            if self.ptt_active:
                self.ptt_active = False
                print(" TRANSMIT STOPPED")
                threading.Thread(target=self.client.stop_transmission, daemon=True).start()
    
    def toggle_filter(self):
        """Toggle high-pass filter on/off"""
        new_state = not self.client.highpass_filter.enabled
        self.client.set_filter_enabled(new_state)
        filter_info = self.client.get_filter_info()
        print(f"\nFilter: {'ON' if new_state else 'OFF'} ({filter_info['type']}, {filter_info['cutoff']}Hz, {filter_info['gain']}dB)")
    
    def decrease_cutoff(self):
        """Decrease cutoff frequency by 25 Hz"""
        current_time = time.time()
        if current_time - self.last_filter_change > 0.2:
            self.filter_freq = max(50, self.filter_freq - 25)
            self.client.set_filter_cutoff(self.filter_freq)
            self.last_filter_change = current_time
            filter_info = self.client.get_filter_info()
            print(f"\n Cutoff: {self.filter_freq} Hz ({filter_info['type']}, {'ON' if filter_info['enabled'] else 'OFF'})")
    
    def increase_cutoff(self):
        """Increase cutoff frequency by 25 Hz"""
        current_time = time.time()
        if current_time - self.last_filter_change > 0.2:
            self.filter_freq = min(2000, self.filter_freq + 25)
            self.client.set_filter_cutoff(self.filter_freq)
            self.last_filter_change = current_time
            filter_info = self.client.get_filter_info()
            print(f"\n Cutoff: {self.filter_freq} Hz ({filter_info['type']}, {'ON' if filter_info['enabled'] else 'OFF'})")
    
    def on_exit(self):
        """Called when ESC is pressed"""
        print("\n👋 Shutting down...")
        self.running = False
        if self.ptt_active:
            self.client.stop_transmission()
        self.client.running = False
        self.client.disconnect()
    
    def monitor_ptt_loop(self):
        """Monitor PTT state in a loop for reliable detection"""
        last_state = False
        
        while self.running:
            try:
                current_state = self.is_ptt_pressed()
                
                if current_state != last_state:
                    if current_state and not last_state:
                        self.on_ptt_press()
                    elif not current_state and last_state:
                        self.on_ptt_release()
                    last_state = current_state
                
                time.sleep(0.05)
                
            except Exception as e:
                print(f"Monitor error: {e}")
                time.sleep(0.1)
    
    def run(self):

        """Run the controller"""
        if not self.client.run():
            print("Failed to start client")
            return
        
        filter_info = self.client.get_filter_info()
        
        print("\n=== PTT Controls ===")
        print(" Press and hold: Alt+1 or Alt+Space to transmit")
        print(" Release to stop transmitting")
        print("\n=== Filter Controls ===")
        print(f"Current filter: {filter_info['type']} [{ 'ON' if filter_info['enabled'] else 'OFF' }] {filter_info['cutoff']}Hz, {filter_info['gain']}dB")
        print("  F1 - Toggle filter ON/OFF")
        print("  F2 - Decrease cutoff frequency (-25 Hz)")
        print("  F3 - Increase cutoff frequency (+25 Hz)")
        print("  F4 - Decrease gain (-1 dB)")
        print("  F5 - Increase gain (+1 dB)")
        print("  F6 - Switch filter type (RC <-> Butterworth)")
        print("\n Press ESC to exit")
        print("=====================\n")
        
        monitor_thread = threading.Thread(target=self.monitor_ptt_loop, daemon=True)
        monitor_thread.start()
        
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n👋 Interrupted")
        finally:
            self.on_exit()

def main():
    """Main entry point"""
    try:
        import pyaudio
        import keyboard
    except ImportError as e:
        print(f"[X] Missing dependency: {e}")
        print("\nInstall required libraries:")
        print("pip install pyaudio keyboard")
        sys.exit(1)
    
    controller = ROIPController()
    controller.run()
    print("Client stopped")

if __name__ == "__main__":
    main()