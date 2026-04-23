import socket
import sys
import time

def send_udp_command(server_ip, server_port, command, arg=None):
    # Создаем UDP сокет
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)  # Таймаут 5 секунд на ожидание ответа
    
    # Формируем сообщение
    message = command
    if arg is not None:
        message += str(arg)+"                                             "
    
    # Адрес сервера
    server_address = (server_ip, server_port)
    
    try:
        # Отправляем данные
        print(f"Sending: {message} to {server_ip}:{server_port}")
        message = message.ljust(20)[:20]
        sock.sendto(message.encode('utf-8'), server_address)
        
        # Ждем ответа
        try:
            data, server = sock.recvfrom(4096)
            print(f"\nReceived response:\n\r{data.decode('utf-8')}")
        except socket.timeout:
            print("No response received within 5 seconds")
    
    finally:
        sock.close()

if __name__ == "__main__":
    # Проверяем аргументы командной строки
    if len(sys.argv) < 4:
        print("Usage:")
        print("  script.py <server_ip> <port> LIST")
        print("  script.py <server_ip> <port> DROP <id>")
        print("Example:")
        print("  script.py 192.168.1.1 1234 LIST")
        sys.exit(1)
    
    server_ip = sys.argv[1]
    server_port = int(sys.argv[2])
    command = sys.argv[3]
    arg = sys.argv[4] if len(sys.argv) > 4 else None
    
    send_udp_command(server_ip, server_port, command, arg)