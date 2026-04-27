import socket
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict

# Конфигурация
MAX_CLIENTS_COUNT = 10
MAX_CLIENT_LIVE_SEC = 15
UDP_PORT = 1222
BUFFER_SIZE = 808
SOCKET_BUFFER_SIZE = 1024 * 1024  # 1MB буфер сокета

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

# Оптимизация: предварительно скомпилированные маппинги
PROTOCOL_MAPPING = {
    (5, 10): True,   # (source_protocol, target_protocol) - нужна конвертация
    (10, 5): True,
}

class TRoipClient:
    __slots__ = ('ip', 'port', 'last_seen', 'fl', 'protocol', 'sub_protocol', 
                 'header', 'packet_count', 'dtype', 'channel')  # Экономия памяти
    
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
clients_lock = threading.RLock()  # Блокировка для потокобезопасности
last_data_time = datetime.now()
data_generator_id = -1

# Настройка сокета с оптимизациями
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, SOCKET_BUFFER_SIZE)
udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
udp_sock.bind(('0.0.0.0', UDP_PORT))

# Кэш для быстрого поиска клиентов
# Оптимизация: словарь {(ip, port): index}
client_cache = {}
client_cache_lock = threading.Lock()

# Пул байтовых массивов для избежания аллокаций
byte_pool = defaultdict(lambda: bytearray(808))

def update_client_cache():
    """Обновить кэш клиентов"""
    with client_cache_lock:
        client_cache.clear()
        for i, client in enumerate(clients):
            if client.port > 0:
                client_cache[(client.ip, client.port)] = i

def cl_clean():
    """Очистка просроченных клиентов с блокировкой"""
    now = datetime.now()
    with clients_lock:
        changed = False
        for client in clients:
            if client.port > 0 and (now - client.last_seen).seconds >= MAX_CLIENT_LIVE_SEC:
                print(f"client lost {client.ip}:{client.port}")
                client.port = 0
                changed = True
        
        if changed:
            update_client_cache()

def cl_send_to_all(from_id, data):
    """Отправить всем кроме from_id"""
    with clients_lock:
        for i, client in enumerate(clients):
            if i != from_id and client.port > 0:
                try:
                    udp_sock.sendto(data, (client.ip, client.port))
                except Exception as e:
                    print(f"Send error to {client.ip}:{client.port}: {e}")

def cl_add(ip, port):
    """Добавить нового клиента"""
    with clients_lock:
        for i, client in enumerate(clients):
            if client.port == 0:
                client.ip = ip
                client.port = port
                client.last_seen = datetime.now()
                client.packet_count = 0
                update_client_cache()
                return i
    return -1

def cl_index_of(ip, port):
    """Быстрый поиск индекса клиента с использованием кэша"""
    with client_cache_lock:
        key = (ip, port)
        if key in client_cache:
            idx = client_cache[key]
            # Проверяем, что клиент еще активен
            with clients_lock:
                if clients[idx].port == port and clients[idx].ip == ip:
                    return idx
            # Если не активен, удаляем из кэша
            del client_cache[key]
    
    # Fallback: линейный поиск
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
                except Exception as e:
                    print(f"ACK send error: {e}")

def control_LST(ip, port):
    """Обработка команды LIST"""
    with clients_lock:
        active_clients = []
        for client in clients:
            if client.ip and client.port:
                active_clients.append(
                    f"{client.ip}:{client.port}\t"
                    f"p:{client.protocol} sp:{client.sub_protocol} "
                    f"ch:{client.channel}\t({client.header}) "
                    f"{type_names[client.dtype]}\tpkt:{client.packet_count}"
                )
    
    response = "\n".join(active_clients) if active_clients else "no-clients"
    
    try:
        udp_sock.sendto(response.encode('utf-8'), (ip, port))
        print(f"Sent LST response to {ip}:{port} ({len(active_clients)} clients)")
    except Exception as e:
        print(f"LST send error: {e}")

def command_decoder(data, sip, sport):
    """Декодирование командных пакетов"""
    try:
        decoded_data = data.decode('utf-8').strip()
        print(f"Command: '{decoded_data}'")
        
        parts = decoded_data.split(maxsplit=1)
        command = parts[0].upper()
        
        if command == "LIST":
            control_LST(sip, sport)
        elif command == "STATS":
            # Быстрая статистика
            with clients_lock:
                active = sum(1 for c in clients if c.port > 0)
                total_packets = sum(c.packet_count for c in clients)
            print(f"STATS: Active clients: {active}, Total packets: {total_packets}")
        else:
            print(f"Unknown command: {command}")
    
    except UnicodeDecodeError:
        print("Error: Invalid UTF-8 data")

def convert_packet_if_needed(data: bytearray, source_protocol: int, target_protocol: int, target_dtype: int) -> bytes:
    """Конвертация пакета между протоколами (оптимизированная версия)"""
    if source_protocol == target_protocol:
        return bytes(data)
    
    # Проверяем, нужна ли конвертация
    if (source_protocol, target_protocol) in PROTOCOL_MAPPING:
        converted = bytearray(data)  # Создаем копию только при необходимости
        converted[1] = target_protocol
        
        if target_dtype == 9:  # COBP
            converted[4] = 3
        
        # Быстрое формирование заголовка (избегаем вызова функции)
        converted[1] = converted[3] = converted[4] = converted[6] = 0
        
        if target_dtype == 3:  # D_WAIS_G711
            converted[1] = 5
            converted[3] = 5
            converted[4] = 1
            converted[6] = 1
        elif target_dtype == 1:  # D_ROIPC_G711
            converted[1] = 5
            converted[3] = 5
            converted[4] = 9
        elif target_dtype == 2:  # D_ROIP_G711HAM
            converted[1] = 10
            converted[3] = 5
            converted[4] = 1
        elif target_dtype == 5:  # D_GSMHAM
            converted[1] = 2
            converted[3] = 10
            converted[4] = 1
        elif target_dtype == 4:  # D_GSM
            converted[1] = 1
            converted[3] = 10
            converted[4] = 1
            converted[6] = 1
        elif target_dtype == 6:  # D_FRSF_JHAM
            converted[1] = 10
            converted[3] = 5
            converted[4] = 3
        
        return bytes(converted)
    
    return bytes(data)

def get_dtype_optimized(data: bytes, sport: int) -> int:
    """Оптимизированная версия определения типа пакета"""
    # Используем локальные переменные для скорости
    b1 = data[1] if len(data) > 1 else 0
    b3 = data[3] if len(data) > 3 else 0
    b4 = data[4] if len(data) > 4 else 0
    b6 = data[6] if len(data) > 6 else 0
    
    if sport > 1221:  # FR_SF
        if b3 == 5:  # VOICE PACKET
            if b1 == 5:
                if b4 == 9:
                    return 1
                if b4 == 1 and b6 == 1:
                    return 3
                if b4 == 5 and b6 == 0:
                    return 7
                if b4 == 3:
                    return 9
            elif b1 == 10:
                if b4 == 1 or b4 == 3:
                    return 6
            elif b1 == 2:
                return 8
        elif b3 == 0 and b4 == 2:
            return 9
        return 7
    
    # Обычный режим
    if b3 == 5:  # Voice
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
    elif b3 == 0:  # Ping
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

def handle_packets():
    """Основной обработчик пакетов (оптимизированный)"""
    global last_data_time, data_generator_id
    
    # Локальные переменные для скорости
    local_clients = clients
    local_get_dtype = get_dtype_optimized
    
    while True:
        try:
            data, addr = udp_sock.recvfrom(BUFFER_SIZE)
            ip, port = addr
            packet_size = len(data)
            
            # Быстрая маршрутизация по размеру пакета
            if packet_size == 808:  # Voice packet
                # Быстрый поиск клиента
                z = cl_index_of(ip, port)
                if z == -1:
                    # Неизвестный клиент - игнорируем голос
                    continue
                
                # Вычисляем канал
                pch = (data[4] - 1) // 2
                
                # Обновляем статистику
                with clients_lock:
                    client = local_clients[z]
                    client.packet_count += 1
                    client.dtype = local_get_dtype(data, port)
                    # Формируем заголовок для отображения (только если нужно)
                    # client.header = " ".join(f"{b:02X}" for b in data[:8])
                    client.last_seen = datetime.now()
                    source_protocol = data[1]
                
                print(f"VOICE {ip}:{port} CH:{pch}")
                
                # Подготовка modified_data (только для тех, кому не нужна конвертация)
                modified_data = None
                
                # Группируем клиентов по протоколам для оптимизации отправки
                clients_by_protocol = {}
                
                with clients_lock:
                    for i, client in enumerate(local_clients):
                        if i != z and client.channel == pch and client.port > 0:
                            protocol_key = client.protocol
                            if protocol_key not in clients_by_protocol:
                                clients_by_protocol[protocol_key] = []
                            clients_by_protocol[protocol_key].append(client)
                
                # Отправляем группам
                for target_protocol, target_clients in clients_by_protocol.items():
                    # Определяем, нужна ли конвертация
                    if source_protocol != target_protocol:
                        # Конвертируем один раз для всей группы
                        target_dtype = target_clients[0].dtype
                        packet_to_send = convert_packet_if_needed(
                            bytearray(data), source_protocol, target_protocol, target_dtype
                        )
                    else:
                        # Без конвертации - используем оригинал
                        if modified_data is None:
                            modified_data = data  # bytes не нужно копировать
                        packet_to_send = modified_data
                    
                    # Отправляем всем клиентам в группе
                    for client in target_clients:
                        try:
                            udp_sock.sendto(packet_to_send, (client.ip, client.port))
                        except Exception as e:
                            print(f"Send error: {e}")
                
                last_data_time = datetime.now()
                
            elif packet_size == 8:  # Control/Keep-alive packet
                i = cl_index_of(ip, port)
                f = data[1] if len(data) > 1 else 0
                ch = (data[4]) // 2
                
                if i == -1 and f != 255:
                    # Новый клиент
                    c = cl_add(ip, port)
                    if c != -1:
                        with clients_lock:
                            local_clients[c].protocol = f
                            local_clients[c].channel = ch
                            local_clients[c].dtype = get_dtype_optimized(data, port)
                            local_clients[c].sub_protocol = data[6] if len(data) > 6 else 0
                        print(f"new client {ip}:{port} pt:{f} ch:{ch}")
                        cl_send_ack(c)
                elif i != -1:
                    # Существующий клиент
                    cl_update(i)
                    with clients_lock:
                        if local_clients[i].channel != ch:
                            print(f"CHANGE CH {local_clients[i].channel}->{ch} for {ip}:{port}")
                            local_clients[i].channel = ch
                    
                    # Отправляем ACK не для каждого keep-alive, а раз в N секунд
                    # (оптимизация: уменьшаем трафик)
                    # cl_send_ack(i)  # Раскомментировать если нужно
                
                # Обработка отключения
                if len(data) > 1 and data[1] == 255:
                    print(f"client Exit {ip}:{port}")
                    if i != -1:
                        with clients_lock:
                            local_clients[i].port = 0
                            local_clients[i].packet_count = 0
                        update_client_cache()
                        
            elif packet_size == 20:  # Command packet
                command_decoder(data, ip, port)
            else:
                print(f"Unknown packet size: {packet_size}")
                
        except socket.timeout:
            continue
        except Exception as e:
            print(f"Packet handling error: {e}")

def timer_tasks():
    """Фоновые задачи"""
    last_ack_time = {}
    
    while True:
        time.sleep(1)  # Уменьшили интервал для более точной очистки
        
        # Очистка старых клиентов (раз в 3 секунды)
        if int(time.time()) % 3 == 0:
            cl_clean()
        
        # Отправка ACK активным клиентам (раз в 2 секунды)
        if int(time.time()) % 2 == 0:
            with clients_lock:
                for client in clients:
                    if client.port > 0:
                        idx = clients.index(client)
                        # Rate limiting для ACK
                        now = time.time()
                        if last_ack_time.get(idx, 0) < now - 2:
                            cl_send_ack(idx)
                            last_ack_time[idx] = now

def setup_socket_timeout():
    """Настройка таймаута сокета для возможности прерывания"""
    udp_sock.settimeout(0.5)

if __name__ == "__main__":
    print(f"Starting optimized UDP server on port {UDP_PORT}")
    print(f"Max clients: {MAX_CLIENTS_COUNT}")
    print(f"Socket buffer: {SOCKET_BUFFER_SIZE // 1024}KB")
    print()
    
    setup_socket_timeout()
    
    # Запускаем потоки
    packet_thread = threading.Thread(target=handle_packets, daemon=True)
    timer_thread = threading.Thread(target=timer_tasks, daemon=True)
    
    packet_thread.start()
    timer_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        udp_sock.close()
        print("Server stopped")