"""
ROIP Server with packet buffering per channel
Sends voice packets to clients not faster than every 100ms
"""

import socket
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict
import queue

# Конфигурация
MAX_CLIENTS_COUNT = 10
MAX_CLIENT_LIVE_SEC = 15
UDP_PORT = 1221
BUFFER_SIZE = 808
PACKET_INTERVAL = 0.1  # 100 milliseconds between packets
PLAYBACK_BUFFER_SIZE = 2  # Количество пакетов для начала отправки (1 = без буфера)

type_names = {
    0: "UNKNOWN",
    1: "ROIPC_G711",
    2: "ROIP_G711HAM",
    3: "WAIS_G711",
    4: "GSM",
    5: "GSMHAM",
    6: "FRSF_G711HAM",
    7: "FRSF_HAM",
    8: "FRSF_GSMHAM",
    9: "COBP_G711"
}


class ChannelBuffer:
    """Буфер для одного канала"""
    
    def __init__(self, channel_id, buffer_size=PLAYBACK_BUFFER_SIZE):
        self.channel_id = channel_id
        self.buffer_size = buffer_size
        self.packet_queue = queue.Queue()
        self.last_send_time = 0
        self.running = True
        self.thread = None
        self.clients = []  # Список клиентов на этом канале
        self.transmitting = False  # Флаг активной передачи
        self.last_packet_time = 0  # Время последнего полученного пакета
        self.silence_timeout = 1.0  # Таймаут тишины (секунды)
    
    def add_packet(self, packet_data, target_clients):
        """Добавить пакет в буфер канала"""
        self.last_packet_time = time.time()
        self.transmitting = True
        
        if self.buffer_size <= 1:
            # Отправляем сразу без буфера
            self._send_to_clients(packet_data, target_clients)
        else:
            # Добавляем в очередь
            self.packet_queue.put((packet_data, target_clients))
    
    def _send_to_clients(self, packet_data, target_clients):
        """Отправить пакет клиентам"""
        for client in target_clients:
            try:
                udp_sock.sendto(packet_data, (client.ip, client.port))
            except Exception as e:
                print(f"Send error to {client.ip}:{client.port}: {e}")
    
    def clear_buffer(self):
        """Очистить буфер очереди"""
        cleared = 0
        while not self.packet_queue.empty():
            try:
                self.packet_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        if cleared > 0:
            print(f"Channel {self.channel_id}: cleared {cleared} packets from buffer")
    
    def check_silence(self):
        """Проверить таймаут тишины и очистить буфер при необходимости"""
        if self.transmitting:
            time_since_last = time.time() - self.last_packet_time
            if time_since_last > self.silence_timeout:
                self.transmitting = False
                self.clear_buffer()
                print(f"Channel {self.channel_id}: transmission ended, buffer cleared")
    
    def process_queue(self):
        """Обработка очереди с задержкой 100ms"""
        # Ждем накопления буфера
        if self.buffer_size > 1:
            # Ждем пока накопится достаточно пакетов
            while self.running and self.packet_queue.qsize() < self.buffer_size:
                # Проверяем таймаут тишины во время ожидания
                self.check_silence()
                if not self.transmitting:
                    # Если передача закончилась, выходим из цикла ожидания
                    break
                time.sleep(0.01)
        
        while self.running:
            try:
                # Проверяем таймаут тишины
                self.check_silence()
                
                # Получаем пакет из очереди (с таймаутом)
                try:
                    packet_data, target_clients = self.packet_queue.get(timeout=0.1)
                except queue.Empty:
                    # Если очередь пуста и передача не активна, выходим
                    if not self.transmitting:
                        time.sleep(0.1)
                    continue
                
                # Контроль времени отправки
                current_time = time.time()
                time_since_last = current_time - self.last_send_time
                
                if time_since_last < PACKET_INTERVAL and self.last_send_time > 0:
                    # Ждем до следующего разрешенного времени отправки
                    sleep_time = PACKET_INTERVAL - time_since_last
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                
                # Отправляем пакет
                self._send_to_clients(packet_data, target_clients)
                self.last_send_time = time.time()
                
            except Exception as e:
                print(f"Channel {self.channel_id} process error: {e}")
    
    def start(self):
        """Запуск потока обработки канала"""
        self.running = True
        self.thread = threading.Thread(target=self.process_queue, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Остановка потока канала"""
        self.running = False
        self.clear_buffer()
        if self.thread:
            self.thread.join(timeout=1)


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


# Глобальные переменные
clients = [TRoipClient() for _ in range(MAX_CLIENTS_COUNT)]
last_data_time = datetime.now()
data_generator_id = -1
modificator = 0
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_sock.bind(('0.0.0.0', UDP_PORT))

# Буферы для каналов
channel_buffers = {}
channel_buffers_lock = threading.Lock()


def get_channel_buffer(channel_id):
    """Получить или создать буфер для канала"""
    with channel_buffers_lock:
        if channel_id not in channel_buffers:
            channel_buffers[channel_id] = ChannelBuffer(channel_id)
            channel_buffers[channel_id].start()
            print(f"Created buffer for channel {channel_id} (size: {PLAYBACK_BUFFER_SIZE})")
        return channel_buffers[channel_id]


def get_clients_by_channel(channel):
    """Получить список клиентов на указанном канале"""
    result = []
    for client in clients:
        if client.port > 0 and client.channel == channel:
            result.append(client)
    return result


def cl_clean():
    now = datetime.now()
    for client in clients:
        if client.port > 0 and (now - client.last_seen).seconds >= MAX_CLIENT_LIVE_SEC:
            print(f"client lost {client.ip}:{client.port}")
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
            return clients.index(client)
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


def control_LST(ip, port):
    active_clients = [f"{client.ip}:{client.port}\tp:{client.protocol} sp:{client.sub_protocol} ch:{client.channel}\t({client.header}) {type_names[client.dtype]}\tpkt:{client.packet_count}" 
                     for client in clients 
                     if client.ip and client.port]
    
    response = "\n".join(active_clients)
    if not active_clients:
        response = "no-clients"

    try:
        udp_sock.sendto(response.encode('utf-8'), (ip, port))
        print(f"Sent LST response to {ip}:{port} ({len(active_clients)} clients)")
    except Exception as e:
        print(f"LST send error to {ip}:{port}: {str(e)}")


def command_decoder(data, sip, sport):
    try:
        decoded_data = data.decode('utf-8').strip()
        print(f"Received 20-byte packet: '{decoded_data}'")
        
        parts = decoded_data.split(maxsplit=1)
        command = parts[0].upper()
        
        if command == "LIST":
            control_LST(sip, sport)
        else:
            print(f"Unknown command: {command}")
    
    except UnicodeDecodeError:
        print("Error: Received data is not valid UTF-8")


def bits_reverse(buffer: bytearray):
    """Инвертирует биты в буфере (XOR с 0xAA)"""
    for i in range(8, 808):
        buffer[i] ^= 0xAA


def make_voice_header(buffer: bytearray, d: int):
    """Формирует голосовой заголовок в буфере согласно типу пакета"""
    buffer[1] = buffer[3] = buffer[4] = buffer[6] = 0
    
    if d == 3:  # D_WAIS_G711
        buffer[1] = 5
        buffer[3] = 5
        buffer[4] = 1
        buffer[6] = 1
    elif d == 1:  # D_ROIPC_G711
        buffer[1] = 5
        buffer[3] = 5
        buffer[4] = 9
        buffer[6] = 0
    elif d == 2:  # D_ROIP_G711HAM
        buffer[1] = 10
        buffer[3] = 5
        buffer[4] = 1
        buffer[6] = 0
    elif d == 5:  # D_GSMHAM
        buffer[1] = 2
        buffer[3] = 10
        buffer[4] = 1
        buffer[6] = 0
    elif d == 4:  # D_GSM
        buffer[1] = 1
        buffer[3] = 10
        buffer[4] = 1
        buffer[6] = 1
    elif d == 6:  # D_FRSF_JHAM
        buffer[1] = 10
        buffer[3] = 5
        buffer[4] = 3
        buffer[6] = 0
    elif d == 9:  # COBP
        buffer[1] = 5
        buffer[3] = 5
        buffer[4] = 3
        buffer[6] = 0


def get_dtype(data: bytes, sport) -> int:
    """Определяет тип пакета по 8-байтному заголовку"""
    if sport > 1221:  # признак FR_SF
        if data[3] == 5:  # VOICE PACKET
            if data[1] == 5:
                if data[4] == 9:
                    return 1  # ROIPC_G711
                if data[4] == 1 and data[6] == 1:
                    return 3  # WAIS_G711
                if data[4] == 5 and data[6] == 0:
                    return 7  # FRSF_J
                if data[4] == 3:
                    return 9
            elif data[1] == 10:  # G711-HAM
                if data[4] == 1:
                    return 6  # FRSF_JHAM
                if data[4] == 3:
                    return 6  # FRSF_JHAM
            elif data[1] == 2:  # G711-GSM
                return 8
        elif data[3] == 0:  # ping packet
            if data[4] == 2:
                return 9
        return 7

    # Voice packet G711
    if data[3] == 5:
        if data[1] == 5:
            if data[4] == 9:
                return 1  # ROIPC_G711
            if data[4] == 1 and data[6] == 1:
                return 3  # WAIS_G711
            if data[4] == 5 and data[6] == 0:
                return 7  # FRSF_J
        elif data[1] == 10:
            if data[4] == 1:
                return 2  # ROIP_G711HAM
            if data[4] == 3:
                return 6  # FRSF_JHAM
    
    # Ping packet
    elif data[3] == 0:
        if data[1] == 5:
            if data[4] == 8:
                return 1  # ROIPC_G711
            if data[6] == 1:
                return 3  # WAIS_G711
            if data[6] == 0 and data[4] == 0:
                return 7  # FRSF_J
        elif data[1] == 10:
            if data[4] == 0:
                return 2  # ROIP_G711HAM
            if data[4] == 2:
                return 6  # FRSF_JHAM
        elif data[1] == 1 and data[6] == 1:
            return 4  # GSM
        elif data[1] == 2 and data[6] == 0:
            return 5  # GSMHAM
    
    # Voice packet G711
    elif data[3] == 10 and data[4] == 1:
        if data[1] == 1 and data[6] == 1:
            return 4  # GSM
        if data[1] == 2 and data[6] == 0:
            return 5  # GSMHAM
        if data[1] == 10:
            return 2
    
    return 0  # UNKNOWN


def handle_packets():
    global last_data_time, data_generator_id
    while True:
        try:
            data, addr = udp_sock.recvfrom(BUFFER_SIZE)
            ip, port = addr
            packet_size = len(data)

            if packet_size == 808:  # Voice packet
                z = cl_index_of(ip, port)
                if z == -1:
                    #print(f"Voice from unknown client {ip}:{port}, ignoring")
                    #continue
                    z = cl_add()
                    
                pch = (data[4] - 1) // 2  # канал
                print(f"VOICE {ip}:{port} CH:{pch}")
                
                clients[z].packet_count += 1
                clients[z].dtype = get_dtype(data, port)
                clients[z].header = " ".join(f"{b:02X}" for b in data[:8])
                cl_update(z)

                p = data[1]
                modified_data = bytearray(data)
                
                # Собираем клиентов на этом канале (кроме отправителя)
                target_clients = []
                for i, client in enumerate(clients):
                    if i != z and client.channel == pch and client.port > 0:
                        target_clients.append(client)
                
                if target_clients:
                    # Для каждого клиента может потребоваться конвертация протокола
                    # Группируем клиентов по типу для оптимизации
                    clients_by_protocol = {}
                    for client in target_clients:
                        protocol_key = client.protocol
                        if protocol_key not in clients_by_protocol:
                            clients_by_protocol[protocol_key] = []
                        clients_by_protocol[protocol_key].append(client)
                    
                    # Обрабатываем каждую группу
                    for protocol, client_group in clients_by_protocol.items():
                        if p == 5 and protocol == 10 or p == 10 and protocol == 5:
                            # Нужна конвертация
                            converted = bytearray(data)
                            converted[1] = protocol
                            if client_group[0].dtype == 9:  # COBP
                                converted[4] = 3
                            make_voice_header(converted, client_group[0].dtype)
                            packet_to_send = bytes(converted)
                        else:
                            packet_to_send = bytes(modified_data)
                        
                        # Добавляем в буфер канала
                        channel_buffer = get_channel_buffer(pch)
                        channel_buffer.add_packet(packet_to_send, client_group)
                
                last_data_time = datetime.now()
                
            elif packet_size == 8:  # Control packet
                i = cl_index_of(ip, port)
                f = data[1] if len(data) > 1 else 0
                ch = (data[4]) // 2

                if i == -1 and f != 255:
                    c = cl_add(ip, port)
                    if c != -1:
                        clients[c].protocol = f
                        clients[c].channel = ch
                        clients[c].header = " ".join(f"{b:02X}" for b in data)
                        clients[c].dtype = get_dtype(data, port)
                        clients[c].sub_protocol = data[6] if len(data) > 6 else 0
                        if debug:
                        	print(f"new client {ip}:{port} pt:{f} ch:{ch}")
                        cl_send_ack(c)
                elif i != -1:
                    cl_update(i)
                    if clients[i].channel != ch:
                        if debug:
                        	print(f"{clients[i].ip}:{clients[i].port} CHANGE CH {clients[i].channel}->{ch}")
                        clients[i].channel = ch
                    
                if len(data) > 1 and data[1] == 255:
                    if debug:
                    	print(f"client Exit {ip}:{port}")
                    if i != -1:
                        clients[i].port = 0
                        
            elif packet_size == 20:  # Command packet
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
        
        # Проверяем буферы каналов на таймаут
        with channel_buffers_lock:
            for buffer in channel_buffers.values():
                buffer.check_silence()
        
        time.sleep(2)
        if (datetime.now() - last_data_time).total_seconds() > 1:
            data_generator_id = -1
        
        if data_generator_id != -1:
            cl_send_ack(data_generator_id)
            #print(f"ACK gener {data_generator_id}")
        else:       
            for client in clients:
                if client.port > 0:
                    cl_send_ack(clients.index(client))


def cleanup_channels():
    """Периодическая очистка пустых каналов"""
    while True:
        time.sleep(60)  # Раз в минуту
        with channel_buffers_lock:
            to_remove = []
            for ch_id, buffer in channel_buffers.items():
                # Проверяем, есть ли клиенты на этом канале
                has_clients = False
                for client in clients:
                    if client.port > 0 and client.channel == ch_id:
                        has_clients = True
                        break
                
                # Если нет клиентов и очередь пуста, удаляем буфер
                if not has_clients and buffer.packet_queue.empty():
                    buffer.stop()
                    to_remove.append(ch_id)
            
            for ch_id in to_remove:
                del channel_buffers[ch_id]
                #print(f"Removed buffer for inactive channel {ch_id}")


if __name__ == "__main__":
    print(f"Starting UDP server on port {UDP_PORT}")
    print(f"Playback buffer size: {PLAYBACK_BUFFER_SIZE} packets")
    print(f"Packet interval: {PACKET_INTERVAL * 1000:.0f}ms")
    print()
    
    # Запускаем потоки
    packet_thread = threading.Thread(target=handle_packets, daemon=True)
    timer_thread = threading.Thread(target=timer_tasks, daemon=True)
    cleanup_thread = threading.Thread(target=cleanup_channels, daemon=True)
    
    packet_thread.start()
    timer_thread.start()
    cleanup_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        # Останавливаем все буферы каналов
        with channel_buffers_lock:
            for buffer in channel_buffers.values():
                buffer.stop()
        udp_sock.close()
        print("Server stopped")