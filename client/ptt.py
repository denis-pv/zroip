"""
PTT Controller for Arduino USB-Com
Reads PTT button state from Arduino via serial port
"""

import serial
import serial.tools.list_ports
import threading
import time
import xml.etree.ElementTree as ET

class ArduinoPTT:
    def __init__(self, port=None, baudrate=57600, auto_reconnect=True):
        self.port = port
        self.baudrate = baudrate
        self.auto_reconnect = auto_reconnect
        self.serial_conn = None
        self.running = False
        self.ptt_pressed = False
        self.callback_on_press = None
        self.callback_on_release = None
        self.thread = None
        self.reconnect_delay = 5
    
    def find_arduino_port(self):
        """Auto-detect Arduino port"""
        try:
            ports = serial.tools.list_ports.comports()
            
            for port in ports:
                description = port.description.lower()
                if any(keyword in description for keyword in ['arduino', 'usb', 'serial', 'ch340', 'cp210']):
                    print(f"Found Arduino on {port.device} ({port.description})")
                    return port.device
            
            if ports:
                print(f"Arduino not found, using first available port: {ports[0].device}")
                return ports[0].device
            
            return None
        except Exception as e:
            print(f"Error finding Arduino port: {e}")
            return None
    
    def connect(self):
        """Connect to Arduino"""
        try:
            if self.port is None:
                self.port = self.find_arduino_port()
                if self.port is None:
                    print("No COM ports found")
                    return False
            
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1,
                write_timeout=1
            )
            print(f"Connected to Arduino on {self.port}")
            return True
            
        except Exception as e:
            print(f"Failed to connect to Arduino: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from Arduino"""
        try:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()
                print("Disconnected from Arduino")
        except:
            pass
    
    def parse_xml(self, line):
        """Parse XML message from Arduino"""
        try:
            line = line.strip()
            if not line.startswith('<'):
                return None
            
            root = ET.fromstring(line)
            result = {}
            
            for entry in root.findall('entry'):
                key_elem = entry.find('string')
                if key_elem is None:
                    continue
                
                value_elem = None
                for child in entry:
                    if child != key_elem:
                        value_elem = child
                        break
                
                if value_elem is not None:
                    result[key_elem.text] = value_elem.text
            
            return result
            
        except ET.ParseError:
            return None
        except Exception as e:
            return None
    
    def set_callbacks(self, on_press, on_release):
        """Set callback functions for PTT events"""
        self.callback_on_press = on_press
        self.callback_on_release = on_release
    
    def _reconnect(self):
        """Attempt to reconnect to Arduino"""
        if not self.running:
            return
        
        print(f"Attempting to reconnect in {self.reconnect_delay} seconds...")
        time.sleep(self.reconnect_delay)
        
        if self.connect():
            print("Arduino reconnected")
        else:
            print("Reconnect failed, will retry later")
    
    def _read_loop(self):
        """Main read loop for serial data"""
        while self.running:
            try:
                # Check connection
                if self.serial_conn is None or not self.serial_conn.is_open:
                    if self.auto_reconnect:
                        self._reconnect()
                    time.sleep(1)
                    continue
                
                # Read data
                if self.serial_conn.in_waiting > 0:
                    line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                    
                    if line:
                        data = self.parse_xml(line)
                        
                        if data:
                            # Check for PTT button event
                            if 'BUTTON' in data and data['BUTTON'] == 'PTT':
                                if 'STATE' in data:
                                    if data['STATE'] == 'PRESSED' and not self.ptt_pressed:
                                        self.ptt_pressed = True
                                        #print(f"{time.strftime('%H:%M:%S')} Arduino: PTT PRESSED")
                                        if self.callback_on_press:
                                            try:
                                                self.callback_on_press()
                                            except Exception as e:
                                                print(f"Callback error: {e}")
                                    
                                    elif data['STATE'] == 'RELEASED' and self.ptt_pressed:
                                        self.ptt_pressed = False
                                        #print(f"{time.strftime('%H:%M:%S')} Arduino: PTT RELEASED")
                                        if self.callback_on_release:
                                            try:
                                                self.callback_on_release()
                                            except Exception as e:
                                                print(f"Callback error: {e}")
                
                time.sleep(0.01)
                
            except serial.SerialException as e:
                print(f"Serial error: {e}")
                self.serial_conn = None
                if not self.auto_reconnect:
                    break
                time.sleep(1)
                
            except Exception as e:
                print(f"PTT read error: {e}")
                time.sleep(0.1)
    
    def start(self):
        """Start PTT monitoring"""
        if self.running:
            return
        
        if not self.connect():
            if self.auto_reconnect:
                print("Will retry connection in background")
            else:
                return
        
        self.running = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Stop PTT monitoring"""
        self.running = False
        self.disconnect()
        if self.thread:
            self.thread.join(timeout=2)
    
    def is_pressed(self):
        """Get current PTT state"""
        return self.ptt_pressed