import socket
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict
import queue

# Конфигурация
MAX_CLIENTS_COUNT = 10
MAX_CLIENT_LIVE_SEC = 15
UDP_PORT = 1222
BUFFER_SIZE = 808
PACKET_INTERVAL = 0.08  # 100 milliseconds between packets
PLAYBACK_BUFFER_SIZE = 1  # Количество пакетов для начала отправки

type_names = {
    0: "UNKNOWN",
    1: "ROIPC_G711",
    2: "ROIP_G711HAM",
    3: "WAIS_G711",
    4: "GSM",
    5: "GSMHAM",
    6: "*FRSF_G711HAM",
    7: "*FRSF_HAM",
    8: "*FRSF_GSMHAM",
    9: "*COBP_G711"
}

class ClientPlaybackBuffer:
    """Буфер воспроизведения для отдельного клиента"""
    
    def __init__(self, client_idx):
        self.client_idx = client_idx
        self.packet_queue = queue.Queue(maxsize=50)  # Ограничиваем размер очереди
        self.last_send_time = 0
        self.running = True
        self.thread = None
        self.buffer_ready = False
        self.buffer_size = PLAYBACK_BUFFER_SIZE
        
    def add_packet(self, packet_data):
        """Добавить пакет в буфер клиента"""
        try:
            self.packet_queue.put(packet_data, timeout=0.1)
            # Если очередь достигла нужного размера, буфер готов к воспроизведению
            if not self.buffer_ready and self.packet_queue.qsize() >= self.buffer_size:
                self.buffer_ready = True
                print(f"Client buffer ready (size: {self.packet_queue.qsize()})")
        except queue.Full:
            # Если очередь переполнена, удаляем старые пакеты
            try:
                self.packet_queue.get_nowait()
                self.packet_queue.put(packet_data, timeout=0.1)
            except:
                pass
    
    def process_queue(self):
        """Обработка очереди с задержкой PACKET_INTERVAL"""
        while self.running:
            try:
                # Ждем накопления буфера, если он еще не готов
                if not self.buffer_ready and self.buffer_size > 1:
                    time.sleep(0.01)
                    continue
                
                # Получаем пакет из очереди
                try:
                    packet_data = self.packet_queue.get(timeout=0.1)
                except queue.Empty:
                    # Если очередь пуста, буфер больше не готов
                    if self.buffer_ready:
                        self.buffer_ready = False
                    continue
                
                # Контроль времени отправки
                current_time = time.time()
                time_since_last = current_time - self.last_send_time
                
                if time_since_last < PACKET_INTERVAL and self.last_send_time > 0:
                    sleep_time = PACKET_INTERVAL - time_since_last
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                
                # Отправляем пакет клиенту
                client = clients[self.client_idx]
                if client.port > 0:  # Проверяем, что клиент еще активен
                    try:
                        udp_sock.sendto(packet_data, (client.ip, client.port))
                        self.last_send_time = time.time()
                    except Exception as e:
                        print(f"Send error to {client.ip}:{client.port}: {e}")
                
            except Exception as e:
                print(f"Client buffer process error: {e}")
    
    def start(self):
        """Запуск потока обработки буфера"""
        self.running = True
        self.thread = threading.Thread(target=self.process_queue, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Остановка потока буфера"""
        self.running = False
        # Очищаем очередь
        while not self.packet_queue.empty():
            try:
                self.packet_queue.get_nowait()
            except:
                break
        if self.thread:
            self.thread.join(timeout=1)
    
    def clear(self):
        """Очистить буфер"""
        while not self.packet_queue.empty():
            try:
                self.packet_queue.get_nowait()
            except:
                break
        self.buffer_ready = False

# Структура для хранения клиентов
class TRoipClient:
    def __init__(self):
        self.ip = ""
        self.port = 0
        self.last_seen = datetime.now()
        self.fl = 0
        self.protocol = 0
        self.sub_protocol = 0
        self.header = bytearray(8)
        self.packet_count = 0
        self.dtype = 0 
        self.channel = 0
        self.buffer = None  # Буфер для этого клиента
        self.use_buffer = True  # Флаг использования буфера

# Глобальные переменные
clients = [TRoipClient() for _ in range(MAX_CLIENTS_COUNT)]
last_data_time = datetime.now()
data_generator_id = -1
modificator = 0
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_sock.bind(('0.0.0.0', UDP_PORT))

def get_client_buffer(client_idx):
    """Получить или создать буфер для клиента"""
    client = clients[client_idx]
    if client.buffer is None and client.use_buffer:
        client.buffer = ClientPlaybackBuffer(client_idx)
        client.buffer.start()
        print(f"Created buffer for client {client.ip}:{client.port}")
    return client.buffer

def cl_clean():
    now = datetime.now()
    for client in clients:
        if client.port > 0 and (now - client.last_seen).seconds >= MAX_CLIENT_LIVE_SEC:
            print(f"client lost {client.ip}:{client.port}")
            # Останавливаем буфер клиента
            if client.buffer:
                client.buffer.stop()
                client.buffer = None
            client.port = 0

def cl_send_to_all(from_id, data):
    for i, client in enumerate(clients):
        if i != from_id and client.port > 0:
            print(f"data to: {client.ip}:{client.port} ignore: {from_id}")
            try:
                udp_sock.sendto(data, (client.ip, client.port))
            except Exception as e:
                print(f"Send error: {e}")

def cl_add(ip, port):
    for client in clients:
        if client.port == 0:
            client.ip = ip
            client.port = port
            client.last_seen = datetime.now()
            client.use_buffer = True  # По умолчанию используем буфер
            # Создаем буфер для нового клиента
            idx = clients.index(client)
            client.buffer = ClientPlaybackBuffer(idx)
            client.buffer.start()
            return idx
    return -1

def cl_index_of(ip, port):
    for i, client in enumerate(clients):
        if client.port == port and client.ip == ip:
            return i
    return -1

def cl_update(idx):
    if 0 <= idx < len(clients):
        clients[idx].last_seen = datetime.now()

def cl_send_ack(idx):
    if 0 <= idx < len(clients):
        ack = bytes([clients[idx].fl, clients[idx].protocol] + [0]*6)
        try:
            udp_sock.sendto(ack, (clients[idx].ip, clients[idx].port))
            clients[idx].fl = (clients[idx].fl + 1) % 256
        except Exception as e:
            print(f"ACK send error: {e}")

def control_LST(ip,port):
    active_clients = [f"{client.ip}:{client.port}\tp:{client.protocol} sp:{client.sub_protocol} ch:{client.channel}\t({client.header}) {type_names[client.dtype]}\tpkt:{client.packet_count}{' (buffered)' if client.use_buffer else ''}" 
                     for client in clients 
                     if client.ip and client.port]
    
    response = "\n".join(active_clients)
    if not active_clients:
        response="no-clients"

    try:
        udp_sock.sendto(response.encode('utf-8'), (ip, port))
        print(f"Sent LST response to {ip}:{port} ({len(active_clients)} clients)")
    except Exception as e:
        print(f"LST send error to {ip}:{port}: {str(e)}")  

def command_decoder(data,sip,sport):
    try:
        decoded_data = data.decode('utf-8').strip()
        print(f"Received 20-byte packet: '{decoded_data}'")
        
        parts = decoded_data.split(maxsplit=1)
        command = parts[0].upper()
        
        if command == "LIST":
            control_LST(sip, sport)
        elif command == "BUFFER" and len(parts) > 1:
            # Команда для управления буфером: BUFFER ON/OFF/STATUS
            arg = parts[1].upper()
            idx = cl_index_of(sip, sport)
            if idx != -1:
                if arg == "ON":
                    clients[idx].use_buffer = True
                    if not clients[idx].buffer:
                        clients[idx].buffer = ClientPlaybackBuffer(idx)
                        clients[idx].buffer.start()
                    print(f"Buffer enabled for {sip}:{sport}")
                elif arg == "OFF":
                    clients[idx].use_buffer = False
                    if clients[idx].buffer:
                        clients[idx].buffer.stop()
                        clients[idx].buffer = None
                    print(f"Buffer disabled for {sip}:{sport}")
                elif arg == "STATUS":
                    status = "enabled" if clients[idx].use_buffer else "disabled"
                    print(f"Buffer status for {sip}:{sport}: {status}")
        else:
            print(f"Unknown command: {command}")
    
    except UnicodeDecodeError:
        print("Error: Received data is not valid UTF-8")

def bits_reverse(buffer: bytearray):
    for i in range(8, 808):
        buffer[i] ^= 0xAA

def make_voice_header(buffer: bytearray, d: int):
    buffer[1] = buffer[3] = buffer[4] = buffer[6] = 0
    
    if d == 3:
        buffer[1] = 5
        buffer[3] = 5
        buffer[4] = 1
        buffer[6] = 1
    elif d == 1:
        buffer[1] = 5
        buffer[3] = 5
        buffer[4] = 9
        buffer[6] = 0
    elif d == 2:
        buffer[1] = 10
        buffer[3] = 5
        buffer[4] = 1
        buffer[6] = 0
    elif d == 5:
        buffer[1] = 2
        buffer[3] = 10
        buffer[4] = 1
        buffer[6] = 0
    elif d == 4:
        buffer[1] = 1
        buffer[3] = 10
        buffer[4] = 1
        buffer[6] = 1
    elif d == 6:
        buffer[1] = 10
        buffer[3] = 5
        buffer[4] = 3
        buffer[6] = 0
    elif d == 9:
        buffer[1] = 5
        buffer[3] = 5
        buffer[4] = 3
        buffer[6] = 0        

def get_dtype(data: bytes, sport) -> int:
    if sport>1221:
        if data[3] == 5:
            if data[1] == 5:
                if data[4] == 9:
                    return 1
                if data[4] == 1 and data[6] == 1:
                    return 3
                if data[4] == 5 and data[6] == 0:
                    return 7
                if data[4] == 3:
                    return 9
            elif data[1] == 10:
                if data[4] == 1:
                    return 6
                if data[4] == 3:
                    return 6
            elif data[1] == 2:
                return 8
        elif data[3]==0:
            if data[4]==2:
                return 9
        return 7

    if data[3] == 5:
        if data[1] == 5:
            if data[4] == 9:
                return 1
            if data[4] == 1 and data[6] == 1:
                return 3
            if data[4] == 5 and data[6] == 0:
                return 7
        elif data[1] == 10:
            if data[4] == 1:
                return 2
            if data[4] == 3:
                return 6
    
    elif data[3] == 0:
        if data[1] == 5:
            if data[4] == 8:
                return 1
            if data[6] == 1:
                return 3
            if data[6] == 0 and data[4] == 0:
                return 7
        elif data[1] == 10:
            if data[4] == 0:
                return 2
            if data[4] == 2:
                return 6
        elif data[1] == 1 and data[6] == 1:
            return 4
        elif data[1] == 2 and data[6] == 0:
            return 5
    
    elif data[3] == 10 and data[4] == 1:
        if data[1] == 1 and data[6] == 1:
            return 4
        if data[1] == 2 and data[6] == 0:
            return 5
        if data[1] == 10:
            return 2
    
    return 0

def handle_packets():
    global last_data_time, data_generator_id
    while True:
        try:
            data, addr = udp_sock.recvfrom(BUFFER_SIZE)
            ip, port = addr
            packet_size = len(data)

            if packet_size == 808:
                z = cl_index_of(ip, port)
                if z == -1:
                    # Игнорируем голос от неизвестного клиента
                    continue
                    
                pch=(data[4]-1)//2
                print(f"VOICE {ip}:{port} CH:{pch}")
                clients[z].packet_count+=1
                clients[z].dtype=get_dtype(data,port)
                clients[z].header = " ".join(f"{b:02X}" for b in data[:8])
                cl_update(z)
                
                p=data[1]
                modified_data = bytearray(data)
                
                for i, client in enumerate(clients):
                    if i != z and client.channel == pch and client.port > 0:
                        # Определяем, отправлять через буфер или напрямую
                        if client.use_buffer and client.buffer:
                            # Конвертируем протокол если нужно
                            if p==5 and client.protocol==10 or p==10 and client.protocol==5:
                                converted = bytearray(data)
                                converted[1] = client.protocol
                                if client.dtype == 9:
                                    converted[4] = 3
                                make_voice_header(converted, client.dtype)
                                packet_to_send = bytes(converted)
                            else:
                                packet_to_send = bytes(modified_data)
                            
                            # Добавляем в буфер клиента
                            client.buffer.add_packet(packet_to_send)
                        else:
                            # Отправляем напрямую (старый способ)
                            if p==5 and client.protocol==10 or p==10 and client.protocol==5:
                                converted = bytearray(data)
                                converted[1] = client.protocol
                                if client.dtype == 9:
                                    converted[4] = 3
                                make_voice_header(converted, client.dtype)
                                try:
                                    udp_sock.sendto(bytes(converted), (client.ip, client.port))
                                except Exception as e:
                                    print(f"Forward error: {e}")
                            else:
                                try:
                                    udp_sock.sendto(modified_data, (client.ip, client.port))
                                except Exception as e:
                                    print(f"Forward error: {e}")
                
                last_data_time = datetime.now()
                
            elif packet_size == 8:
                i = cl_index_of(ip, port)
                f = data[1] if len(data) > 1 else 0
                ch = (data[4]) // 2

                if i == -1 and f != 255:
                    c = cl_add(ip, port)
                    if c != -1:
                        clients[c].protocol = f
                        clients[c].channel = ch
                        clients[c].header = " ".join(f"{b:02X}" for b in data)
                        clients[c].dtype=get_dtype(data,port)
                        clients[c].sub_protocol = data[6] if len(data) > 6 else 0
                        print(f"new client {ip}:{port} pt:{f} ch:{ch} (buffering: {clients[c].use_buffer})")
                        cl_send_ack(c)
                elif i != -1:
                    cl_update(i)
                    if clients[i].channel != ch:
                        print(f"{clients[i].ip}:{clients[i].port}\tCHANGE CH {clients[i].channel}->{ch}")
                        clients[i].channel = ch
                        
                    # Если клиент переключил канал, очищаем его буфер
                    if clients[i].buffer:
                        clients[i].buffer.clear()
                    
                if len(data) > 1 and data[1] == 255:
                    print(f"client Exit {ip}:{port}")
                    if i != -1:
                        if clients[i].buffer:
                            clients[i].buffer.stop()
                            clients[i].buffer = None
                        clients[i].port = 0
                        
            elif packet_size == 20:
                command_decoder(data, ip, port)
            else:
                print(f"packet_size: {packet_size}")
                        
        except Exception as e:
            print(f"Packet handling error: {e}")

def timer_tasks():
    global data_generator_id
    while True:
        time.sleep(3)
        cl_clean()
        
        time.sleep(2)
        if (datetime.now() - last_data_time).total_seconds() > 1:
            data_generator_id = -1
        
        if data_generator_id != -1:
            cl_send_ack(data_generator_id)
            print(f"ACK gener {data_generator_id}")
        else:       
            for client in clients:
                if client.port > 0:
                    cl_send_ack(clients.index(client))

if __name__ == "__main__":
    print(f"Starting UDP server on port {UDP_PORT}")
    print(f"Playback buffer size: {PLAYBACK_BUFFER_SIZE} packets")
    print(f"Packet interval: {PACKET_INTERVAL * 1000:.0f}ms")
    print("Commands: LIST, BUFFER ON/OFF/STATUS")
    print()
    
    packet_thread = threading.Thread(target=handle_packets, daemon=True)
    timer_thread = threading.Thread(target=timer_tasks, daemon=True)
    
    packet_thread.start()
    timer_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
        # Останавливаем все буферы
        for client in clients:
            if client.buffer:
                client.buffer.stop()
        udp_sock.close()