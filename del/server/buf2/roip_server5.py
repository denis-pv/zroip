import socket
import threading
import time
from datetime import datetime, timedelta

# Конфигурация
MAX_CLIENTS_COUNT = 10
MAX_CLIENT_LIVE_SEC = 15  # если клиент не отвечает 15 сек то он оффлайн
UDP_PORT = 1222
BUFFER_SIZE = 808


data_generator_id = -1

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

"""
из ява классов:
ALAW     = 6
ULAW     = 5
ULAW HAM   = 10
IMBE     = 85
GSM     = 1
GSM HAM   = 2

"""
def millis():
    return int(time.time() * 1000)

def get_dtype(data: bytes, sport) -> int:
    """
    Определяет тип пакета по 8-байтному заголовку
    Args:
        data: bytes - ровно 8 байт данных
    Returns:
        int - индекс типа пакета из type_names

        0 - packet_index
        1 - CODEC (10 - HAM, 5 - COMMERCIAL, 255 - DISCONNECT)
        2
        3 - PACKET TYPE (0 - PING, 5 - VOICE_G711,  10 - VOICE_GSM_HAM)
    """

    if sport>1221:             # признак FR_SF
        if data[3] == 5:       # VOICE PACKET
            if data[1] == 5:
                if data[4] == 9:
                    return 1  # ROIPC_G711
                if data[4] == 1 and data[6] == 1:
                    return 3  # WAIS_G711
                if data[4] == 5 and data[6] == 0:
                    return 7  # FRSF_J
                if data[4] == 3:
                    return 9;
            elif data[1] == 10:  # G711-HAM
                if data[4] == 1:
                    return 6  # FRSF_JHAM
                if data[4] == 3:
                    return 6  # FRSF_JHAM
            elif data[1] == 2:  # G711-GSM
                return 8
        elif data[3]==0:   #ping packet
            if data[4]==2:
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



# Структура для хранения клиентов
class TRoipClient:
    def __init__(self):
        self.ip = ""
        self.port = 0
        self.last_seen = datetime.now()
        self.fl = 0
        self.protocol = 0
        self.sub_protocol = 0
        self.header = bytearray(8)  # 8-байтный заголовок (по умолчанию нули)
        self.packet_count = 0
        self.dtype = 0 
        self.channel = 0
        self.last_ack = 0

# Глобальные переменные
clients = [TRoipClient() for _ in range(MAX_CLIENTS_COUNT)]
last_data_time = 0

modificator = 0
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_sock.bind(('0.0.0.0', UDP_PORT))

def remove_client(idx):
    clients[idx].port = 0
    clients[idx].packet_count = 0

def cl_clean():
    now = datetime.now()
    for client in clients:
        if client.port > 0 and (now - client.last_seen).seconds >= MAX_CLIENT_LIVE_SEC:
            print(f"client lost {client.ip}:{client.port}")
            client.port = 0
            packet_count = 0

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
        m=millis();
        if clients[idx].port>0 and (m-clients[idx].last_ack) >= 10000:
            ack = bytes([clients[idx].fl, clients[idx].protocol] + [0]*6)
            try:
                udp_sock.sendto(ack, (clients[idx].ip, clients[idx].port))
                clients[idx].fl = (clients[idx].fl + 1) % 256
                clients[idx].last_ack=millis()
            except Exception as e:
                print(f"ACK send error: {e}")
            m=millis();
            print(f"ACK:{clients[idx].ip}:{clients[idx].port}  millis: {m}")
            

def control_LST(ip,port):
    # 1. Получаем список активных клиентов
    active_clients = [f"{client.ip}:{client.port}\tp:{client.protocol} sp:{client.sub_protocol} ch:{client.channel}\t({client.header}) {type_names[client.dtype]}\tpkt:{client.packet_count}" 
                     for client in clients 
                     if client.ip and client.port]
    
    # 2. Формируем ответ (каждого клиента с новой строки)
    response = "\n".join(active_clients)
    if not active_clients:
        response="no-clients"

    try:

        # 4. Отправляем ответ обратно клиенту
        udp_sock.sendto(response.encode('utf-8'), (ip, port))
        print(f"Sent LST response to {ip}:{port} ({len(active_clients)} clients)")
    except Exception as e:
        print(f"LST send error to {ip}:{port}: {str(e)}")  


def command_decoder(data,sip,sport):
    try:
        # Декодируем данные (с обработкой ошибок)
        decoded_data = data.decode('utf-8').strip()  # Удаляем лишние пробелы/переносы
        
        print(f"Received 20-byte packet: '{decoded_data}'")
        
        # Разбиваем на команду и аргумент (если есть)
        parts = decoded_data.split(maxsplit=1)  # Разделяем только по первому пробелу
        command = parts[0].upper()  # Приводим команду к верхнему регистру
        
        if command == "LIST":
            # Проверяем, есть ли аргумент (например, "LIST FULL" -> arg = "FULL")
            arg = parts[1] if len(parts) > 1 else None
            control_LST(sip, sport)  # Передаём IP, порт и аргумент (если есть)
        else:
            print(f"Unknown command: {command}")
    
    except UnicodeDecodeError:
        print("Error: Received data is not valid UTF-8")


def bits_reverse(buffer: bytearray):
    """Инвертирует биты в буфере (XOR с 0xAA) для элементов с 50 по 849"""
    for i in range(8, 808):
        buffer[i] ^= 0xAA


def make_voice_header(buffer: bytearray, d: int):
    """
    Формирует голосовой заголовок в буфере согласно типу пакета
    :param buffer: bytearray - буфер для записи заголовка (минимум 7 байт)
    :param d: int - тип пакета (из type_names)
    """
    # Очищаем позиции заголовка (опционально)
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
    elif d == 9:  # 
        buffer[1] = 5
        buffer[3] = 5
        buffer[4] = 3
        buffer[6] = 0     

    

'''
1  - счетчик
2  - протокол (10 - HAMG711, 5 - HAMG711 )
'''


def handle_packets():
    global last_data_time, data_generator_id
    while True:
        try:
            data, addr = udp_sock.recvfrom(BUFFER_SIZE)
            ip, port = addr
            packet_size = len(data)
           

            if packet_size == 808:
                z = cl_index_of(ip, port)
                pch=(data[4]-1)//2                 # канал в который идет голосовой траффик
                print(f"VOICE {ip}:{port} CH:{pch}")
                clients[z].packet_count+=1
                clients[z].dtype=get_dtype(data,port)
                clients[z].header = " ".join(f"{b:02X}" for b in data[:8])
                cl_update(z)
                data_generator_id = z

                p=data[1]
                
               
                modified_data = bytearray(data)
                
                for i, client in enumerate(clients):
                    #if i != z and (client.channel==pch or client.channel==0) and client.port > 0:
                    if i != z and (client.channel==pch) and client.port > 0:

                        #print("SEND VOICE TO CLIENTS")

                        if p==5 and client.protocol==10 or p==10 and client.protocol==5:
                            converted=bytearray(data)
                            converted[1]=client.protocol
               
                            if client.dtype==9: # COBP
                                converted[4]=3
                                        #converted[1]=5
                                        #converted[3]=5
                            make_voice_header(converted,client.dtype)
                            try:
                                udp_sock.sendto(converted, (client.ip, client.port))
                            except Exception as e:
                                print(f"--- Forward error: {e}")                            
                        else:                        
                            try:
                                udp_sock.sendto(modified_data, (client.ip, client.port))
                            except Exception as e:
                                print(f"Forward error: {e}")
                        cl_send_ack(i)

                last_data_time = millis()
                
            elif packet_size == 8:

                i = cl_index_of(ip, port)
                f = data[1] if len(data) > 1 else 0
                ch=  (data[4])//2    # канал который включен у абонента, при голосовом траффике прибавляется 1


                #print(f"DATA8 {i} - {ip}:{port} {data}")

                if i == -1 and f != 255:
                    c = cl_add(ip, port)
                    if c != -1:
                        clients[c].protocol = f
                        clients[c].channel = ch
                        clients[c].header = " ".join(f"{b:02X}" for b in data)
                        clients[c].dtype=get_dtype(data,port)
                        clients[c].sub_protocol = data[6] if len(data) > 6 else 0
                        print(f"new client {ip}:{port} pt:{f}")
                        cl_send_ack(c)
                elif i != -1:
                    cl_update(i)
                    if clients[i].channel!=ch:
                        print(f"{clients[i].ip}:{clients[i].port}\tCHANGE CH {clients[i].channel}->{ch}")
                        clients[i].channel=ch;
                    
                # клиент отключается
                if len(data) > 1 and data[1] == 255:
                    print(f"client Exit {ip}:{port}")
                    if i != -1:
                        remove_client(i)

            elif packet_size==20:
                command_decoder(data, ip, port)

            else:
                print(f"packet_size: {packet_size}")
                        
        except Exception as e:
            r=cl_index_of(ip,port)
            remove_client(r)
            #print(f"Error processing packet from {ip}:{port}: {e}")
            print(f"Packet handling error: {e}")

def timer_tasks():
    
    global data_generator_id
    while True:
        time.sleep(0.1)
        cl_clean()
        
        #time.sleep(2)
        if ((millis() - last_data_time)>=500) and (data_generator_id!=-1):
           
            cl_send_ack(data_generator_id)
            data_generator_id = -1
            print("reset gener")
        
        if data_generator_id<0:
            for i, client in enumerate(clients):
                if (client.port) > 0 and (i!=data_generator_id):
                    cl_send_ack(i)                    
                #print("TMR")
                #print(f"ACK:{client.ip}:{client.port}")

if __name__ == "__main__":
    print(f"Starting UDP server on port {UDP_PORT}")
    
    # Запускаем потоки
    packet_thread = threading.Thread(target=handle_packets, daemon=True)
    timer_thread = threading.Thread(target=timer_tasks, daemon=True)
    
    packet_thread.start()
    timer_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
        udp_sock.close()