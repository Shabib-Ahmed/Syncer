import socket
import threading
import time
import argparse
import sys
import hashlib
import os

def hashFile(filePath):
    sha256 = hashlib.sha256()
    
    with open(filePath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            sha256.update(chunk)
    
    return sha256.hexdigest()

def hashFolder(folderPath):
    combined = hashlib.sha256()
    
    for root, dirs, files in os.walk(folderPath):
        for filename in sorted(files):
            filepath = os.path.join(root, filename)
            relativePath = os.path.relpath(filepath, folderPath)
            
            combined.update(relativePath.encode())
            combined.update(hashFile(filepath).encode())
    
    return combined.hexdigest()



def sendPing(sock, targetIP, targetPort, stopEvent, handshakeComplete):
    print(f"Sending to {targetIP}:{targetPort}")
    
    pingNum = 1
    try:
        while not stopEvent.is_set():

            # Send handshake
            try:
                sock.sendto(b"HELLO", (targetIP, targetPort))
            except socket.error as e:
                print(f"Error sending handshake: {e}")
            
            if not handshakeComplete.wait(timeout=1.0):
                continue 

            try:
                message = f"PING {pingNum}|{folderHash}".encode()
                sock.sendto(message, (targetIP, targetPort))
                print(f"Sent message #{pingNum} to {targetIP}:{targetPort}")
                pingNum += 1
            except socket.error as e:
                print(f"Error sending: {e}")
            
            # Reset handshake
            handshakeComplete.clear()

            time.sleep(10)
            
    except Exception as e:
        print(f"Sending Thread error: {e}")
    finally:
        print("Sending Thread Stopped")

def receivePing(sock, stopEvent, handshakeComplete):
    print("Starting receiver")
    sock.settimeout(1.0)
    
    try:
        while not stopEvent.is_set():
            try:
                data, addr = sock.recvfrom(1024)
                message = data.decode()
                
                if message == "HELLO" and not handshakeComplete.is_set():
                    print(f"Received Handshake from {addr}")
                    sock.sendto(b"HELLO", addr)
                    print(f"Sent Handshake back to {addr}")
                    handshakeComplete.set()
                    continue
                
                # Check Hash on Handshake
                if handshakeComplete.is_set() and message.startswith("PING"):
                    print(f"Received from {addr}: {message}")
                    
                    # Parse the message
                    if '|' in message:
                        parts = message.split('|')
                        theirHash = parts[1]
                        
                        if folderHash == theirHash:
                            print("FOLDERS MATCH")
                        else:
                            print("FOLDERS DIFFERENT")
                        
                        # Send our hash back
                        response = f"PONG|{folderHash}".encode()
                        sock.sendto(response, addr)
                        print(f"Sent hash back to {addr}")
                    
                        # Reset handshake
                        print("Comparison done. Resetting handshake.\n")
                        handshakeComplete.clear()
                
                # Handle PONG response
                if message.startswith("PONG"):
                    print(f"Received PONG from {addr}: {message}")
                    
                    if '|' in message:
                        parts = message.split('|')
                        theirHash = parts[1]
                        
                        if folderHash == theirHash:
                            print("FOLDERS MATCH")
                        else:
                            print("FOLDERS DIFFERENT")
                        
            except socket.timeout:
                continue
            except socket.error as e:
                if not stopEvent.is_set():
                    print(f"Error receiving: {e}")
    
    except Exception as e:
        print(f"Thread error: {e}")
    finally:
        print("Receive thread stopped")


"""
if not os.path.exists(folder):
    print(f"Error: Folder '{folder}' does not exist")
    sys.exit(1)
"""

folderHash = hashFolder('testData2')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('ip', help='Target IP address')
    parser.add_argument('port', type=int, help='Target port number')    
    parser.add_argument('--bind-port', type=int, default=0, help='Local port to bind for receiving (default: random)')
    
    args = parser.parse_args()
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', args.bind_port))
        actualPort = sock.getsockname()[1]
        print(f"Socket bound to port {actualPort}")
    except socket.error as e:
        print(f"Error creating socket: {e}")
        sys.exit(1)
    
    stop_event = threading.Event()
    handshake_complete = threading.Event()
    
    # Create and start threads
    sendThread = threading.Thread(target=sendPing, args=(sock, args.ip, args.port, stop_event, handshake_complete))
    receiveThread = threading.Thread(target=receivePing, args=(sock, stop_event, handshake_complete))
    
    sendThread.start()
    receiveThread.start()
    
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        stop_event.set()
    
    # Wait for threads to finish
    sendThread.join(timeout=3)
    receiveThread.join(timeout=3)
    
    sock.close()

if __name__ == '__main__':
    main()