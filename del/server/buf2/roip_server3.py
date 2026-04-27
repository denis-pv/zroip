import socket
import threading
import time
from datetime import datetime
from collections import deque

MAX_CLIENTS_COUNT = 10
MAX_CLIENT_LIVE_SEC = 15
UDP_PORT = 1222
BUFFER_SIZE = 808

last_data_time = datetime.now()
data_gener_id=-1

type_names = {
    0: "UNKNOWN", 1: "ROIPC_G711", 2: "ROIP_G711HAM", 3: "WAIS_G711",
    4: "GSM", 5: "GSMHAM", 6: "*FRSF_G711HAM", 7: "*FRSF_HAM",
    8: "*FRSF_GSMHAM", 9: "*COBP_G711"
}

class TRoipClient:
    __slots__ = ('ip', 'port', 'last_seen', 'fl', 'protocol', 'sub_protocol', 
                 'header', 'packet_count', 'dtype', 'channel', 'buffer', 'buffer_lock', 'last_ack_time','last_ds_time')
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
        self.buffer = deque(maxlen=50)
        self.buffer_lock = threading.Lock()
        self.last_ack_time = datetime.now()
        self.last_ds_time = datetime.now()

clients = [TRoipClient() for _ in range(MAX_CLIENTS_COUNT)]
clients_lock = threading.Lock()
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
udp_sock.bind(('0.0.0.0', UDP_PORT))

def cl_add(ip, port):
    with clients_lock:
        for i, c in enumerate(clients):
            if c.port == 0:
                c.ip, c.port, c.last_seen = ip, port, datetime.now()
                c.packet_count, c.fl = 0, 0
                return i
    return -1

def cl_index_of(ip, port):
    with clients_lock:
        for i, c in enumerate(clients):
            if c.port == port and c.ip == ip:
                return i
    return -1

def cl_update(idx):
    if idx >= 0:
        with clients_lock:
            clients[idx].last_seen = datetime.now()

def cl_send_ack(idx):
    with clients_lock:
        if idx >= 0 and clients[idx].port > 0:
            ack = bytes([clients[idx].fl, clients[idx].protocol] + [0]*6)
            udp_sock.sendto(ack, (clients[idx].ip, clients[idx].port))
            clients[idx].fl = (clients[idx].fl + 1) % 256

def cl_clean():
    now = datetime.now()
    with clients_lock:
        for c in clients:
            if c.port and (now - c.last_seen).seconds >= MAX_CLIENT_LIVE_SEC:
                print(f"lost {c.ip}:{c.port}")
                c.port = 0
                with c.buffer_lock:
                    c.buffer.clear()

def send_to_clients(data, sender_idx, target_channel):
    with clients_lock:
        for i, c in enumerate(clients):
            if i != sender_idx and c.port and c.channel == target_channel:
                try:
                    udp_sock.sendto(data, (c.ip, c.port))
                except:
                    pass

def get_dtype(data, sport):
    if sport > 1221:
        if data[3] == 5:
            if data[1] == 5:
                if data[4] == 9: return 1
                if data[4] == 1 and data[6] == 1: return 3
                if data[4] == 5 and data[6] == 0: return 7
                if data[4] == 3: return 9
            elif data[1] == 10 and (data[4] == 1 or data[4] == 3): return 6
            elif data[1] == 2: return 8
        elif data[3] == 0 and data[4] == 2: return 9
        return 7
    if data[3] == 5:
        if data[1] == 5:
            if data[4] == 9: return 1
            if data[4] == 1 and data[6] == 1: return 3
            if data[4] == 5 and data[6] == 0: return 7
        elif data[1] == 10:
            if data[4] == 1: return 2
            if data[4] == 3: return 6
    elif data[3] == 0:
        if data[1] == 5:
            if data[4] == 8: return 1
            if data[6] == 1: return 3
            if data[6] == 0 and data[4] == 0: return 7
        elif data[1] == 10:
            if data[4] == 0: return 2
            if data[4] == 2: return 6
        elif data[1] == 1 and data[6] == 1: return 4
        elif data[1] == 2 and data[6] == 0: return 5
    elif data[3] == 10 and data[4] == 1:
        if data[1] == 1 and data[6] == 1: return 4
        if data[1] == 2 and data[6] == 0: return 5
        if data[1] == 10: return 2
    return 0

def make_voice_header(buf, d):
    buf[1] = buf[3] = buf[4] = buf[6] = 0
    if d == 3: buf[1], buf[3], buf[4], buf[6] = 5, 5, 1, 1
    elif d == 1: buf[1], buf[3], buf[4] = 5, 5, 9
    elif d == 2: buf[1], buf[3], buf[4] = 10, 5, 1
    elif d == 5: buf[1], buf[3], buf[4] = 2, 10, 1
    elif d == 4: buf[1], buf[3], buf[4], buf[6] = 1, 10, 1, 1
    elif d == 6: buf[1], buf[3], buf[4] = 10, 5, 3
    elif d == 9: buf[1], buf[3], buf[4] = 5, 5, 3

def process_voice(data, ip, port):
    global data_gener_id, last_data_time 
    z = cl_index_of(ip, port)
    data_gener_id=z
    last_data_time=datetime.now()
    if z == -1:
        return
    
    pch = (data[4] - 1) // 2
    ch_data = data[1]
    
    with clients_lock:
        clients[z].packet_count += 1
        clients[z].dtype = get_dtype(data, port)
        clients[z].last_seen = datetime.now()
    
    #print(f"VOICE {ip}:{port} CH:{pch}")    
    with clients_lock:
        for i, c in enumerate(clients):
            if i != z and c.port and c.channel == pch:
                if ch_data == 5 and c.protocol == 10 or ch_data == 10 and c.protocol == 5:
                    converted = bytearray(data)
                    converted[1] = c.protocol
                    if c.dtype == 9:
                        converted[4] = 3
                    make_voice_header(converted, c.dtype)
                    packet = bytes(converted)
                else:
                    packet = data
                
                with c.buffer_lock:
                    c.buffer.append(packet)
                
                if len(c.buffer) == 1:
                    threading.Thread(target=send_buffer, args=(i,), daemon=True).start()


def send_buffer(client_idx):
    with clients_lock:
        if client_idx >= len(clients):
            return
        client = clients[client_idx]
    
    last_send = 0
    
    while True:
        with client.buffer_lock:
            if not client.buffer:
                break
            packet = client.buffer.popleft()
        
        now = time.time()
        if last_send > 0:
            wait = 0.1 - (now - last_send)
            if wait > 0:
                deadline = now + wait
                while time.time() < deadline:
                    pass
        
        try:
            udp_sock.sendto(packet, (client.ip, client.port))
            client.last_ds_time=datetime.now()
            last_send = time.time()
        except:
            break

def handle_packets():
    while True:
        try:
            data, addr = udp_sock.recvfrom(BUFFER_SIZE)
            ip, port = addr
            
            if len(data) == 808:

                process_voice(data, ip, port)
            
            elif len(data) == 8:
                i = cl_index_of(ip, port)
                f = data[1] if len(data) > 1 else 0
                ch = data[4] // 2
                #print("DATA 8 IN")
                
                if i == -1 and f != 255:
                    c = cl_add(ip, port)
                    if c != -1:
                        with clients_lock:
                            clients[c].protocol = f
                            clients[c].channel = ch
                            clients[c].dtype = get_dtype(data, port)
                            clients[c].sub_protocol = data[6] if len(data) > 6 else 0
                        print(f"new client {ip}:{port} pt:{f} ch:{ch}")
                        cl_send_ack(c)
                elif i != -1:
                    cl_update(i)
                    print(f"DATA 8 IN, upd: {i}")
                    with clients_lock:
                        if clients[i].channel != ch:
                            clients[i].channel = ch
                
                if len(data) > 1 and data[1] == 255:
                    print(f"exit {ip}:{port}")
                    if i != -1:
                        with clients_lock:
                            clients[i].port = 0
                            with clients[i].buffer_lock:
                                clients[i].buffer.clear()
                else:
                    send_to_clients(data, i, -1)
            
            elif len(data) == 20:
                try:
                    cmd = data.decode('utf-8').strip().upper()
                    if cmd.startswith("LIST"):
                        with clients_lock:
                            resp = "\n".join([f"{c.ip}:{c.port} ch:{c.channel}" 
                                            for c in clients if c.port])
                        udp_sock.sendto((resp or "no-clients").encode(), (ip, port))
                except:
                    pass
        
        except:
            pass

def timer_tasks():
    global data_gener_id, last_data_time
    while True:
        time.sleep(0.1)
        cl_clean()

        if data_gener_id>-1  and (datetime.now() - last_data_time).total_seconds() > 0.5:
            cl_send_ack(data_gener_id)
            data_gener_id = -1 
            print("reset gener")
                   

        for client in clients:
            if client.port > 0 and (datetime.now() - client.last_ack_time).total_seconds() >=10 :
                if (datetime.now()-client.last_ds_time).microseconds>=10:
                    cl_send_ack(clients.index(client))
                    client.last_ack_time=datetime.now()
                    print(f"ACK:{client.ip}:{client.port}  gener_id {data_gener_id}")        

if __name__ == "__main__":
    print(f"Server on port {UDP_PORT}")
    threading.Thread(target=handle_packets, daemon=True).start()
    threading.Thread(target=timer_tasks, daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        udp_sock.close()