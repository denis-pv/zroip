"""
ROIP Server with proper packet buffering and queue management
Поддерживает буферизацию голосовых пакетов с контролем интервала отправки
"""

import socket
import threading
import time
import queue
from datetime import datetime, timedelta
from collections import defaultdict
from enum import Enum

# Конфигурация
MAX_CLIENTS_COUNT = 10
MAX_CLIENT_LIVE_SEC = 15
UDP_PORT = 1222
BUFFER_SIZE = 808
SOCKET_BUFFER_SIZE = 1024 * 1024  # 1MB

# Настройки буферизации
PACKET_INTERVAL = 0.095  # 100ms между пакетами
PLAYBACK_BUFFER_SIZE = 2  # Накопить N пакетов перед началом воспроизведения
MAX_QUEUE_SIZE = 100  # Максимальный размер очереди на клиента
SILENCE_TIMEOUT = 1.0  # Таймаут тишины (секунды)

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

class ClientState(Enum):
    """Состояния клиента"""
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    PLAYING = 3

class PacketBuffer:
    """Буфер пакетов для одного клиента с контролем потока"""
    
    def __init__(self, client_idx, callback_send):
        self.client_idx = client_idx
        self.callback_send = callback_send
        self.packet_queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        self.last_send_time = 0
        self.running = True
        self.thread = None
        self.buffer_ready = False
        self.buffer_size = PLAYBACK_BUFFER_SIZE
        self.last_packet_time = time.time()
        self.stats = {
            'packets_received': 0,
            'packets_sent': 0,
            'packets_dropped': 0,
            'buffer_underruns': 0
        }
        
    def add_packet(self, packet_data: bytes):
        """Добавить пакет в буфер (вызывается из основного потока)"""
        self.stats['packets_received'] += 1
        self.last_packet_time = time.time()
        
        try:
            # Неблокирующая вставка с таймаутом
            self.packet_queue.put(packet_data, timeout=0.01)
            
            # Проверяем готовность буфера
            if not self.buffer_ready and self.packet_queue.qsize() >= self.buffer_size:
                self.buffer_ready = True
                print(f"[Buffer {self.client_idx}] Ready, size: {self.packet_queue.qsize()}/{self.buffer_size}")
                
        except queue.Full:
            # Очередь переполнена - удаляем самый старый пакет
            try:
                self.packet_queue.get_nowait()
                self.packet_queue.put(packet_data, timeout=0.01)
                self.stats['packets_dropped'] += 1
                print(f"[Buffer {self.client_idx}] Queue full, dropped oldest packet")
            except:
                self.stats['packets_dropped'] += 1
                
    def process_queue(self):
        """Обработка очереди в отдельном потоке"""
        while self.running:
            try:
                # Проверяем таймаут тишины
                time_since_packet = time.time() - self.last_packet_time
                if time_since_packet > SILENCE_TIMEOUT and self.buffer_ready:
                    print(f"[Buffer {self.client_idx}] Silence timeout, clearing buffer")
                    self.clear_buffer()
                    self.buffer_ready = False
                
                # Если буфер не готов и не пуст, ждем накопления
                if not self.buffer_ready and self.buffer_size > 1:
                    if self.packet_queue.qsize() > 0:
                        # Ждем накопления, но не бесконечно
                        time.sleep(0.01)
                        continue
                
                # Получаем пакет из очереди с таймаутом
                try:
                    packet_data = self.packet_queue.get(timeout=0.1)
                except queue.Empty:
                    # Очередь пуста - буфер больше не готов
                    if self.buffer_ready:
                        self.buffer_ready = False
                        self.stats['buffer_underruns'] += 1
                    continue
                
                # Контроль интервала отправки (throttling)
                current_time = time.time()
                time_since_last = current_time - self.last_send_time
                
                if time_since_last < PACKET_INTERVAL and self.last_send_time > 0:
                    sleep_time = PACKET_INTERVAL - time_since_last
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                
                # Отправка через callback (с блокировкой)
                if self.callback_send(self.client_idx, packet_data):
                    self.stats['packets_sent'] += 1
                    self.last_send_time = time.time()
                
            except Exception as e:
                print(f"[Buffer {self.client_idx}] Error in process_queue: {e}")
    
    def clear_buffer(self):
        """Очистить буфер"""
        cleared = 0
        while not self.packet_queue.empty():
            try:
                self.packet_queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        if cleared > 0:
            print(f"[Buffer {self.client_idx}] Cleared {cleared} packets")
        self.buffer_ready = False
    
    def start(self):
        """Запуск потока обработки"""
        self.running = True
        self.thread = threading.Thread(target=self.process_queue, name=f"Buffer-{self.client_idx}", daemon=True)
        self.thread.start()
        print(f"[Buffer {self.client_idx}] Started")
    
    def stop(self):
        """Остановка потока"""
        self.running = False
        self.clear_buffer()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        print(f"[Buffer {self.client_idx}] Stopped (stats: {self.stats})")
    
    def get_stats(self) -> str:
        """Получить статистику буфера"""
        return (f"rcv:{self.stats['packets_received']} "
                f"snd:{self.stats['packets_sent']} "
                f"drp:{self.stats['packets_dropped']} "
                f"und:{self.stats['buffer_underruns']} "
                f"qsz:{self.packet_queue.qsize()}")


class TRoipClient:
    """Структура клиента с поддержкой буферизации"""
    __slots__ = ('ip', 'port', 'last_seen', 'fl', 'protocol', 'sub_protocol',
                 'header', 'packet_count', 'dtype', 'channel', 'buffer', 
                 'use_buffer', 'state', 'created_at')
    
    def __init__(self):
        self.ip = ""
        self.port = 0
        self.last_seen = datetime.now()
        self.created_at = datetime.now()
        self.fl = 0
        self.protocol = 0
        self.sub_protocol = 0
        self.header = bytearray(8)
        self.packet_count = 0
        self.dtype = 0 
        self.channel = 0
        self.buffer = None  # PacketBuffer instance
        self.use_buffer = True  # Флаг использования буфера
        self.state = ClientState.DISCONNECTED


# Глобальные переменные
clients = [TRoipClient() for _ in range(MAX_CLIENTS_COUNT)]
clients_lock = threading.RLock()
client_cache = {}
client_cache_lock = threading.Lock()

last_data_time = datetime.now()
debug_mode = True  # Включить отладку

# Настройка сокета
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_BUFFER_SIZE)
udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
udp_sock.bind(('0.0.0.0', UDP_PORT))


def send_to_client(client_idx: int, data: bytes) -> bool:
    """
    Callback для отправки данных клиенту из буфера
    Возвращает True если отправка успешна
    """
    with clients_lock:
        if client_idx < 0 or client_idx >= len(clients):
            return False
        client = clients[client_idx]
        if client.port == 0 or client.state == ClientState.DISCONNECTED:
            return False
        
        try:
            udp_sock.sendto(data, (client.ip, client.port))
            return True
        except Exception as e:
            if debug_mode:
                print(f"Send error to {client.ip}:{client.port}: {e}")
            return False


def get_client_buffer(client_idx: int) -> PacketBuffer:
    """Получить или создать буфер для клиента (с блокировкой)"""
    with clients_lock:
        client = clients[client_idx]
        if client.buffer is None and client.use_buffer:
            client.buffer = PacketBuffer(client_idx, send_to_client)
            client.buffer.start()
            if debug_mode:
                print(f"[Client {client_idx}] Buffer created for {client.ip}:{client.port}")
        return client.buffer


def update_client_cache():
    """Обновить кэш клиентов"""
    with client_cache_lock:
        client_cache.clear()
        with clients_lock:
            for i, client in enumerate(clients):
                if client.port > 0:
                    client_cache[(client.ip, client.port)] = i


def cl_clean():
    """Очистка просроченных клиентов"""
    now = datetime.now()
    with clients_lock:
        changed = False
        for i, client in enumerate(clients):
            if client.port > 0:
                # Проверяем таймаут
                if (now - client.last_seen).seconds >= MAX_CLIENT_LIVE_SEC:
                    print(f"Client lost {client.ip}:{client.port}")
                    
                    # Останавливаем буфер
                    if client.buffer:
                        client.buffer.stop()
                        client.buffer = None
                    
                    client.port = 0
                    client.state = ClientState.DISCONNECTED
                    changed = True
                
                # Проверяем долгоживущие буферы без активности
                elif client.buffer and client.use_buffer:
                    time_since_packet = time.time() - client.buffer.last_packet_time
                    if time_since_packet > SILENCE_TIMEOUT * 2:
                        client.buffer.clear_buffer()
        
        if changed:
            update_client_cache()


def cl_add(ip, port) -> int:
    """Добавить нового клиента"""
    with clients_lock:
        for i, client in enumerate(clients):
            if client.port == 0:
                client.ip = ip
                client.port = port
                client.last_seen = datetime.now()
                client.created_at = datetime.now()
                client.packet_count = 0
                client.state = ClientState.CONNECTED
                
                # Создаем буфер если нужно
                if client.use_buffer:
                    client.buffer = PacketBuffer(i, send_to_client)
                    client.buffer.start()
                
                update_client_cache()
                
                if debug_mode:
                    print(f"New client {i}: {ip}:{port} (buffer: {client.use_buffer})")
                return i
    return -1


def cl_index_of(ip, port) -> int:
    """Быстрый поиск индекса клиента"""
    # Поиск в кэше
    with client_cache_lock:
        key = (ip, port)
        if key in client_cache:
            idx = client_cache[key]
            with clients_lock:
                if idx < len(clients) and clients[idx].port == port and clients[idx].ip == ip:
                    return idx
            # Неактуальная запись
            del client_cache[key]
    
    # Линейный поиск
    with clients_lock:
        for i, client in enumerate(clients):
            if client.port == port and client.ip == ip:
                with client_cache_lock:
                    client_cache[(ip, port)] = i
                return i
    return -1


def cl_update(idx):
    """Обновить время последнего контакта"""
    if idx >= 0:
        with clients_lock:
            if idx < len(clients):
                clients[idx].last_seen = datetime.now()


def cl_send_ack(idx):
    """Отправить ACK клиенту"""
    if idx >= 0:
        with clients_lock:
            if idx < len(clients) and clients[idx].port > 0:
                ack = bytes([clients[idx].fl, clients[idx].protocol] + [0]*6)
                try:
                    udp_sock.sendto(ack, (clients[idx].ip, clients[idx].port))
                    clients[idx].fl = (clients[idx].fl + 1) % 256
                    if debug_mode:
                        print(f"ACK sent to {clients[idx].ip}:{clients[idx].port}")
                except Exception as e:
                    print(f"ACK send error: {e}")


def control_LST(ip, port):
    """Обработка команды LIST"""
    with clients_lock:
        active_clients = []
        for i, client in enumerate(clients):
            if client.port > 0:
                buffer_stats = ""
                if client.buffer:
                    buffer_stats = f" [{client.buffer.get_stats()}]"
                
                active_clients.append(
                    f"{i}:{client.ip}:{client.port}\t"
                    f"p:{client.protocol} sp:{client.sub_protocol} "
                    f"ch:{client.channel} "
                    f"{type_names[client.dtype]}\t"
                    f"pkt:{client.packet_count}{buffer_stats}"
                )
    
    response = "\n".join(active_clients) if active_clients else "no-clients"
    
    try:
        udp_sock.sendto(response.encode('utf-8'), (ip, port))
        print(f"LST response to {ip}:{port} ({len(active_clients)} clients)")
    except Exception as e:
        print(f"LST send error: {e}")


def command_decoder(data, sip, sport):
    """Декодирование командных пакетов"""
    try:
        cmd_str = data.decode('utf-8').strip()
        print(f"Command: '{cmd_str}' from {sip}:{sport}")
        
        parts = cmd_str.split(maxsplit=1)
        command = parts[0].upper()
        
        if command == "LIST":
            control_LST(sip, sport)
            
        elif command == "BUFFER" and len(parts) > 1:
            # Управление буфером для клиента
            idx = cl_index_of(sip, sport)
            if idx == -1:
                return
            
            arg = parts[1].upper()
            with clients_lock:
                client = clients[idx]
                
                if arg == "ON":
                    if not client.buffer:
                        client.use_buffer = True
                        client.buffer = PacketBuffer(idx, send_to_client)
                        client.buffer.start()
                        print(f"Buffer ENABLED for {sip}:{sport}")
                        
                elif arg == "OFF":
                    if client.buffer:
                        client.buffer.stop()
                        client.buffer = None
                    client.use_buffer = False
                    print(f"Buffer DISABLED for {sip}:{sport}")
                    
                elif arg == "STATS":
                    stats = client.buffer.get_stats() if client.buffer else "no buffer"
                    print(f"Buffer stats for {sip}:{sport}: {stats}")
                    
                elif arg == "CLEAR":
                    if client.buffer:
                        client.buffer.clear_buffer()
                        print(f"Buffer CLEARED for {sip}:{sport}")
        
        elif command == "STATS":
            # Общая статистика сервера
            with clients_lock:
                active = sum(1 for c in clients if c.port > 0)
                buffered = sum(1 for c in clients if c.buffer)
                total_packets = sum(c.packet_count for c in clients)
                
                stats = f"Active: {active}, Buffered: {buffered}, Total packets: {total_packets}"
                print(f"STATS: {stats}")
                
        else:
            print(f"Unknown command: {command}")
            
    except UnicodeDecodeError:
        print(f"Invalid UTF-8 from {sip}:{sport}")


def get_dtype(data: bytes, sport: int) -> int:
    """Определение типа пакета (оптимизированная версия)"""
    if len(data) < 8:
        return 0
    
    b1 = data[1]
    b3 = data[3]
    b4 = data[4]
    b6 = data[6]
    
    if sport > 1221:  # FR_SF
        if b3 == 5:
            if b1 == 5:
                if b4 == 9:
                    return 1
                if b4 == 1 and b6 == 1:
                    return 3
                if b4 == 5 and b6 == 0:
                    return 7
                if b4 == 3:
                    return 9
            elif b1 == 10 and (b4 == 1 or b4 == 3):
                return 6
            elif b1 == 2:
                return 8
        elif b3 == 0 and b4 == 2:
            return 9
        return 7
    
    # Обычный режим
    if b3 == 5:
        if b1 == 5:
            if b4 == 9:
                return 1
            if b4 == 1 and b6 == 1:
                return 3
            if b4 == 5 and b6 == 0:
                return 7
        elif b1 == 10:
            if b4 == 1:
                return 2
            if b4 == 3:
                return 6
    elif b3 == 0:
        if b1 == 5:
            if b4 == 8:
                return 1
            if b6 == 1:
                return 3
            if b6 == 0 and b4 == 0:
                return 7
        elif b1 == 10:
            if b4 == 0:
                return 2
            if b4 == 2:
                return 6
        elif b1 == 1 and b6 == 1:
            return 4
        elif b1 == 2 and b6 == 0:
            return 5
    elif b3 == 10 and b4 == 1:
        if b1 == 1 and b6 == 1:
            return 4
        if b1 == 2 and b6 == 0:
            return 5
        if b1 == 10:
            return 2
    
    return 0


def make_voice_header(buffer: bytearray, d: int):
    """Формирование голосового заголовка"""
    # Обнуляем нужные байты
    buffer[1] = buffer[3] = buffer[4] = buffer[6] = 0
    
    if d == 3:  # WAIS_G711
        buffer[1] = 5
        buffer[3] = 5
        buffer[4] = 1
        buffer[6] = 1
    elif d == 1:  # ROIPC_G711
        buffer[1] = 5
        buffer[3] = 5
        buffer[4] = 9
    elif d == 2:  # ROIP_G711HAM
        buffer[1] = 10
        buffer[3] = 5
        buffer[4] = 1
    elif d == 5:  # GSMHAM
        buffer[1] = 2
        buffer[3] = 10
        buffer[4] = 1
    elif d == 4:  # GSM
        buffer[1] = 1
        buffer[3] = 10
        buffer[4] = 1
        buffer[6] = 1
    elif d == 6:  # FRSF_JHAM
        buffer[1] = 10
        buffer[3] = 5
        buffer[4] = 3
    elif d == 9:  # COBP
        buffer[1] = 5
        buffer[3] = 5
        buffer[4] = 3


def convert_packet(data: bytes, source_protocol: int, target_protocol: int, target_dtype: int) -> bytes:
    """Конвертация пакета между протоколами"""
    if source_protocol == target_protocol:
        return data
    
    converted = bytearray(data)
    converted[1] = target_protocol
    
    if target_dtype == 9:  # COBP
        converted[4] = 3
    
    make_voice_header(converted, target_dtype)
    return bytes(converted)


def handle_packets():
    """Основной обработчик пакетов (с поддержкой буферизации)"""
    global last_data_time
    
    while True:
        try:
            data, addr = udp_sock.recvfrom(BUFFER_SIZE)
            ip, port = addr
            packet_size = len(data)
            
            # Быстрая обработка по типу пакета
            if packet_size == 808:  # Voice packet
                # Поиск отправителя
                sender_idx = cl_index_of(ip, port)
                if sender_idx == -1:
                    if debug_mode:
                        print(f"Voice from unknown {ip}:{port}, ignoring")
                    continue
                
                # Определяем канал
                if len(data) > 4:
                    channel = (data[4] - 1) // 2
                else:
                    continue
                
                # Обновляем статистику отправителя
                with clients_lock:
                    clients[sender_idx].packet_count += 1
                    clients[sender_idx].dtype = get_dtype(data, port)
                    clients[sender_idx].last_seen = datetime.now()
                    source_protocol = data[1] if len(data) > 1 else 0
                
                if debug_mode:
                    print(f"VOICE {ip}:{port} CH:{channel} (proto:{source_protocol})")
                
                # Собираем получателей на этом канале (кроме отправителя)
                recipients = []
                with clients_lock:
                    for i, client in enumerate(clients):
                        if (i != sender_idx and client.port > 0 and 
                            client.channel == channel and client.state == ClientState.CONNECTED):
                            recipients.append((i, client))
                
                # Группируем получателей по протоколу для оптимизации
                groups = {}
                for idx, client in recipients:
                    proto = client.protocol
                    if proto not in groups:
                        groups[proto] = []
                    groups[proto].append((idx, client))
                
                # Обрабатываем каждую группу
                for target_protocol, group in groups.items():
                    # Конвертируем пакет один раз для группы
                    if source_protocol != target_protocol:
                        target_dtype = group[0][1].dtype
                        packet_to_send = convert_packet(data, source_protocol, target_protocol, target_dtype)
                    else:
                        packet_to_send = data
                    
                    # Отправляем или буферизуем
                    for client_idx, client in group:
                        if client.use_buffer and client.buffer:
                            # Через буфер
                            client.buffer.add_packet(packet_to_send)
                        else:
                            # Прямая отправка
                            try:
                                udp_sock.sendto(packet_to_send, (client.ip, client.port))
                            except Exception as e:
                                print(f"Send error to {client.ip}:{client.port}: {e}")
                
                last_data_time = datetime.now()
                
            elif packet_size == 8:  # Keep-alive / Control packet
                if len(data) < 2:
                    continue
                    
                client_idx = cl_index_of(ip, port)
                protocol = data[1]
                channel = data[4] // 2 if len(data) > 4 else 0
                
                if client_idx == -1 and protocol != 255:
                    # Новый клиент
                    new_idx = cl_add(ip, port)
                    if new_idx != -1:
                        with clients_lock:
                            clients[new_idx].protocol = protocol
                            clients[new_idx].channel = channel
                            clients[new_idx].dtype = get_dtype(data, port)
                            clients[new_idx].sub_protocol = data[6] if len(data) > 6 else 0
                            clients[new_idx].state = ClientState.CONNECTED
                        
                        cl_send_ack(new_idx)
                        print(f"New client {ip}:{port} proto:{protocol} ch:{channel}")
                        
                elif client_idx != -1:
                    # Существующий клиент
                    cl_update(client_idx)
                    
                    with clients_lock:
                        client = clients[client_idx]
                        if client.channel != channel:
                            print(f"Client {ip}:{port} channel change: {client.channel} -> {channel}")
                            # При смене канала очищаем буфер
                            if client.buffer:
                                client.buffer.clear_buffer()
                            client.channel = channel
                    
                    # Отправляем периодический ACK (не на каждый keep-alive)
                    # cl_send_ack(client_idx)
                    
                    # Обработка отключения
                    if protocol == 255:
                        print(f"Client disconnect {ip}:{port}")
                        with clients_lock:
                            if clients[client_idx].buffer:
                                clients[client_idx].buffer.stop()
                                clients[client_idx].buffer = None
                            clients[client_idx].port = 0
                            clients[client_idx].state = ClientState.DISCONNECTED
                        update_client_cache()
                        
            elif packet_size == 20:  # Command packet
                command_decoder(data, ip, port)
                
            else:
                if debug_mode:
                    print(f"Unknown packet size: {packet_size} from {ip}:{port}")
                    
        except socket.timeout:
            continue
        except Exception as e:
            print(f"Packet handling error: {e}")


def timer_tasks():
    """Фоновые задачи: очистка, мониторинг, статистика"""
    last_stats_time = time.time()
    
    while True:
        time.sleep(1)
        
        # Очистка старых клиентов (каждые 3 секунды)
        if int(time.time()) % 3 == 0:
            cl_clean()
        
        # Периодическая статистика (каждые 30 секунд)
        if time.time() - last_stats_time > 30:
            with clients_lock:
                active = sum(1 for c in clients if c.port > 0)
                buffered = sum(1 for c in clients if c.buffer)
                total_packets = sum(c.packet_count for c in clients)
                
                print(f"\n=== SERVER STATS ===")
                print(f"Active clients: {active}/{MAX_CLIENTS_COUNT}")
                print(f"Buffered clients: {buffered}")
                print(f"Total packets: {total_packets}")
                
                # Статистика по активным буферам
                for i, client in enumerate(clients):
                    if client.buffer:
                        print(f"  Client {i}: {client.ip}:{client.port} - {client.buffer.get_stats()}")
                print("==================\n")
                
            last_stats_time = time.time()


def main():
    """Запуск сервера"""
    print("=" * 60)
    print("ROIP Server with Packet Buffering")
    print("=" * 60)
    print(f"UDP Port: {UDP_PORT}")
    print(f"Max clients: {MAX_CLIENTS_COUNT}")
    print(f"Client timeout: {MAX_CLIENT_LIVE_SEC}s")
    print(f"\nBuffer settings:")
    print(f"  Packet interval: {PACKET_INTERVAL * 1000:.0f}ms")
    print(f"  Playback buffer: {PLAYBACK_BUFFER_SIZE} packets")
    print(f"  Max queue size: {MAX_QUEUE_SIZE} packets")
    print(f"  Silence timeout: {SILENCE_TIMEOUT}s")
    print("\nCommands (UDP port 1222):")
    print("  LIST - list clients")
    print("  BUFFER ON/OFF/STATS/CLEAR - per-client buffer control")
    print("  STATS - server statistics")
    print("=" * 60)
    print("Server started, waiting for packets...\n")
    
    # Настройка сокета
    udp_sock.settimeout(0.5)
    
    # Запуск потоков
    packet_thread = threading.Thread(target=handle_packets, name="PacketHandler", daemon=True)
    timer_thread = threading.Thread(target=timer_tasks, name="TimerTasks", daemon=True)
    
    packet_thread.start()
    timer_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        
        # Остановка всех буферов
        with clients_lock:
            for client in clients:
                if client.buffer:
                    client.buffer.stop()
        
        udp_sock.close()
        print("Server stopped")


if __name__ == "__main__":
    main()