import socket
import threading
import time
from datetime import datetime
from collections import deque

MAX_CLIENTS_COUNT = 10
MAX_CLIENT_LIVE_SEC = 15
UDP_PORT = 1222
BUFFER_SIZE = 808

type_names = {
    0: "UNKNOWN", 1: "ROIPC_G711", 2: "ROIP_G711HAM", 3: "WAIS_G711",
    4: "GSM", 5: "GSMHAM", 6: "*FRSF_G711HAM", 7: "*FRSF_HAM",
    8: "*FRSF_GSMHAM", 9: "*COBP_G711"
}

class TRoipClient:
    __slots__ = ('ip', 'port', 'last_seen', 'fl', 'protocol', 'sub_protocol', 
                 'header', 'packet_count', 'dtype', 'channel', 'buffer', 'buffer_lock')
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

clients = [TRoipClient() for _ in range(MAX_CLIENTS_COUNT)]
clients_lock = threading.Lock()
last_data_time = datetime.now()
data_generator_id = -1
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
    global data_generator_id
    now = datetime.now()
    with clients_lock:
        for c in clients:
            if c.port and (now - c.last_seen).seconds >= MAX_CLIENT_LIVE_SEC:
                print(f"lost {c.ip}:{c.port}")
                c.port = 0
                with c.buffer_lock:
                    c.buffer.clear()
                if data_generator_id == clients.index(c):
                    data_generator_id = -1

def send_to_clients(data, sender_idx, target_channel):
    with clients_lock:
        for i, c in enumerate(clients):
            if i != sender_idx and c.port and (target_channel == -1 or c.channel == target_channel):
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
    elif d == 9: buf[1], buf[3], buf[4] = 5,