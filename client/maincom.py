"""
Main entry point for ROIP Client
Handles keyboard shortcuts: Alt+1 for PTT (Push-to-Talk)
Filter controls: F1, F2, F3, F4, F5, F6
Optional: COM port connection for Arduino PTT button
"""

import sys
import threading
import time
import keyboard
import serial
import serial.tools.list_ports
import xml.etree.ElementTree as ET
from roip_client import ROIPClient

# ========== КОНФИГУРАЦИЯ ==========
COM_PORT = None  # Автоматическое определение, или укажите явно: "COM3", "/dev/ttyUSB0"
COM_BAUDRATE = 57600
ENABLE_COM_PTT = True  # Включить управление через COM порт
COM_RECONNECT_DELAY = 5  # Задержка перед переподключением при обрыве (секунды)

class ArduinoPTTController:
    """Управление PTT через Arduino по COM порту"""
    
    def __init__(self, port=None, baudrate=57600):
        self.port = port
        self.baudrate = baudrate
        self.serial_conn = None
        self.running = True
        self.ptt_active = False
        self.callback_on_press = None
        self.callback_on_release = None
        self.reconnect_thread = None
        
    def find_arduino_port(self):
        """Автоматически найти Arduino порт"""
        ports = serial.tools.list_ports.comports()
        
        for port in ports:
            # Проверяем по описанию (Arduino обычно содержит эти ключевые слова)
            if any(keyword in port.description.lower() for keyword in ['arduino', 'usb', 'serial', 'ch340', 'cp210']):
                print(f" Found Arduino on {port.device} ({port.description})")
                return port.device
        
        # Если не нашли, возвращаем первый доступный порт
        if ports:
            print(f" PTT Device not found, using first available port: {ports[0].device}")
            return ports[0].device
        
        return None
    
    def connect(self):
        """Подключение к COM порту"""
        try:
            # Определяем порт если не указан
            if self.port is None:
                self.port = self.find_arduino_port()
                if self.port is None:
                    print(" No COM ports found!")
                    return False
            
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1,
                write_timeout=1
            )
            print(f" Connected to {self.port} at {self.baudrate} baud")
            return True
            
        except Exception as e:
            print(f" Failed to connect to {self.port}: {e}")
            return False
    
    def disconnect(self):
        """Отключение от COM порта"""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            print(f" Disconnected from {self.port}")
    
    def reconnect(self):
        """Переподключение при обрыве связи"""
        while self.running:
            if self.serial_conn is None or not self.serial_conn.is_open:
                print(f" Attempting to reconnect to Arduino...")
                if self.connect():
                    # Успешно переподключились
                    break
                else:
                    print(f" Retry in {COM_RECONNECT_DELAY} seconds...")
                    time.sleep(COM_RECONNECT_DELAY)
            else:
                break
    
    def parse_xml_message(self, line):
        """Парсинг XML сообщения от Arduino"""
        try:
            # Удаляем лишние пробелы и символы
            line = line.strip()
            if not line.startswith('<'):
                return None
            
            root = ET.fromstring(line)
            result = {}
            
            # Парсим map структуру
            for entry in root.findall('entry'):
                key_elem = entry.find('string')
                if key_elem is None:
                    continue
                
                # Ищем второе значение (может быть string или любое другое)
                value_elem = None
                for child in entry:
                    if child != key_elem:
                        value_elem = child
                        break
                
                if value_elem is not None:
                    key = key_elem.text
                    value = value_elem.text
                    result[key] = value
            
            return result
            
        except ET.ParseError as e:
            # Не XML сообщение
            return None
        except Exception as e:
            print(f"Parse error: {e}")
            return None
    
    def set_callbacks(self, on_press, on_release):
        """Установка callback функций для PTT"""
        self.callback_on_press = on_press
        self.callback_on_release = on_release
    
    def run(self):
        """Основной цикл чтения COM порта"""
        print(" Arduino PTT controller started")
        
        while self.running:
            try:
                # Проверяем соединение
                if self.serial_conn is None or not self.serial_conn.is_open:
                    self.reconnect()
                    if self.serial_conn is None or not self.serial_conn.is_open:
                        time.sleep(1)
                        continue
                
                # Читаем данные
                if self.serial_conn.in_waiting > 0:
                    line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                    
                    if line:
                        # Парсим XML
                        data = self.parse_xml_message(line)
                        
                        if data:
                            # Проверяем PTT команду
                            if 'BUTTON' in data and data['BUTTON'] == 'PTT':
                                if 'STATE' in data:
                                    if data['STATE'] == 'PRESSED' and not self.ptt_active:
                                        self.ptt_active = True
                                       # print("\n Arduino: PTT PRESSED")
                                        if self.callback_on_press:
                                            self.callback_on_press()
                                    
                                    elif data['STATE'] == 'RELEASED' and self.ptt_active:
                                        self.ptt_active = False
                                        #print("\n  Arduino: PTT RELEASED")
                                        if self.callback_on_release:
                                            self.callback_on_release()
                            
                            # Keep-alive от Arduino (просто для отладки)
                            elif 'KEEP_ALIVE' in data:
                                pass  # Не выводим keep-alive сообщения
                
                time.sleep(0.01)
                
            except serial.SerialException as e:
                print(f" Serial error: {e}")
                self.reconnect()
                time.sleep(1)
                
            except Exception as e:
                print(f" Unexpected error: {e}")
                time.sleep(0.1)
        
        self.disconnect()
    
    def stop(self):
        """Остановка контроллера"""
        self.running = False
        self.disconnect()


class ROIPController:
    def __init__(self):
        self.client = ROIPClient()
        self.running = True
        self.ptt_active = False
        self.transmission_lock = threading.Lock()
        self.arduino_ptt = None
        
        # Для управления фильтром 
        self.filter_freq = 400
        self.last_filter_change = 0
        
        # Настройка горячих клавиш (только если не используем Arduino PTT)
        if not ENABLE_COM_PTT:
            self.setup_keyboard_hotkeys()
        
        # Настройка Arduino PTT
        if ENABLE_COM_PTT:
            self.setup_arduino_ptt()
        
        # ESC для выхода (всегда активна)
        # keyboard.add_hotkey('esc', self.on_exit)
    
    def setup_keyboard_hotkeys(self):
        """Настройка клавиатурных горячих клавиш"""
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
    
    def setup_arduino_ptt(self):
        """Настройка Arduino PTT"""
        self.arduino_ptt = ArduinoPTTController(
            port=COM_PORT,
            baudrate=COM_BAUDRATE
        )
        self.arduino_ptt.set_callbacks(self.on_ptt_press, self.on_ptt_release)
        
        # Запускаем поток Arduino
        arduino_thread = threading.Thread(target=self.arduino_ptt.run, daemon=True)
        arduino_thread.start()
    
    def on_ptt_press(self):
        """Called when PTT key is pressed"""
        with self.transmission_lock:
            if not self.ptt_active and self.client.running:
                self.ptt_active = True
                print("\n TRANSMIT STARTED")
                threading.Thread(target=self.client.start_transmission, daemon=True).start()
    
    def on_ptt_release(self):
        """Called when PTT key is released"""
        with self.transmission_lock:
            if self.ptt_active:
                self.ptt_active = False
                print("\n TRANSMIT STOPPED")
                threading.Thread(target=self.client.stop_transmission, daemon=True).start()
    
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
        print(f"Gain: {new_gain:.1f} dB")
    
    def toggle_filter(self):
        """Toggle high-pass filter on/off"""
        new_state = not self.client.highpass_filter.enabled
        self.client.set_filter_enabled(new_state)
        filter_info = self.client.get_filter_info()
        print(f"\n Filter: {'ON' if new_state else 'OFF'} ({filter_info['type']}, {filter_info['cutoff']}Hz, {filter_info['gain']}dB)")
    
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
        print("\n Shutting down...")
        self.running = False
        
        # Останавливаем Arduino контроллер
        if self.arduino_ptt:
            self.arduino_ptt.stop()
        
        if self.ptt_active:
            self.client.stop_transmission()
        
        self.client.running = False
        self.client.disconnect()
    
    def run(self):
        """Run the controller"""
        if not self.client.run():
            print("Failed to start client")
            return
        
        filter_info = self.client.get_filter_info()
        
        print("\n=== PTT Controls ===")
        if ENABLE_COM_PTT:
            print(" PTT via Arduino button")
        else:
            print(" Press and hold: Alt+1 or Alt+Space to transmit")
            print(" Release to stop transmitting")
        
        print("\n=== Filter Controls ===")
        print(f" Current filter: {filter_info['type']} [{ 'ON' if filter_info['enabled'] else 'OFF' }] {filter_info['cutoff']}Hz, {filter_info['gain']}dB")
        print(" F1 - Toggle filter ON/OFF")
        print(" F2 - Decrease cutoff frequency (-25 Hz)")
        print(" F3 - Increase cutoff frequency (+25 Hz)")
        print(" F4 - Decrease gain (-1 dB)")
        print(" F5 - Increase gain (+1 dB)")
        print(" F6 - Switch filter type (RC <-> Butterworth)")
        
        print("=====================\n")
        
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n Interrupted")
        finally:
            self.on_exit()

def main():
    """Main entry point"""
    # Проверка зависимостей
    try:
        import pyaudio
        import keyboard
        import serial
    except ImportError as e:
        print(f"✗ Missing dependency: {e}")
        print("\nInstall required libraries:")
        print("pip install pyaudio keyboard pyserial")
        sys.exit(1)
    
    controller = ROIPController()
    controller.run()
    print("Client stopped")

if __name__ == "__main__":
    main()