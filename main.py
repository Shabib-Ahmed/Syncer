import socket
import threading
import time
import argparse
import sys
import hashlib
import os
import shutil
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.request
import urllib.parse
import json

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

def getFolderModTime(folderPath):
    latestMod = 0
    for root, dirs, files in os.walk(folderPath):
        for filename in files:
            filepath = os.path.join(root, filename)
            modTime = os.path.getmtime(filepath)
            latestMod = max(latestMod, modTime)
    
    return latestMod

class CustomHTTPHandler(SimpleHTTPRequestHandler):    
    def __init__(self, *args, directory=None, **kwargs):
        self.directory = directory
        super().__init__(*args, directory=directory, **kwargs)
    
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        
        if parsed_path.path == '/filelist.json':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            fileList = []
            if os.path.exists(self.directory):
                for root, dirs, files in os.walk(self.directory):
                    for filename in files:
                        filepath = os.path.join(root, filename)
                        relPath = os.path.relpath(filepath, self.directory)
                        fileList.append(relPath)
            
            self.wfile.write(json.dumps(fileList).encode())
        else:
            super().do_GET()
    
    def log_message(self, format, *args):
        pass

def startHTTPServer(port, directory):
    from functools import partial
    handler = partial(CustomHTTPHandler, directory=os.path.abspath(directory))
    
    server = HTTPServer(('0.0.0.0', port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"HTTP server started on port {port} serving {directory}")
    return server


def downloadFolder(sourceIP, sourcePort, destFolder):
    try:
        url = f"http://{sourceIP}:{sourcePort}/filelist.json"
        with urllib.request.urlopen(url) as response:
            fileList = json.loads(response.read().decode())
        
        if os.path.exists(destFolder):
            shutil.rmtree(destFolder)
        os.makedirs(destFolder)
        
        for relPath in fileList:
            url = f"http://{sourceIP}:{sourcePort}/{relPath}"
            destPath = os.path.join(destFolder, relPath)
            
            os.makedirs(os.path.dirname(destPath), exist_ok=True)
            urllib.request.urlretrieve(url, destPath)
        
        print("Download complete!")
        return True
        
    except Exception as e:
        print(f"Download failed: {e}")
        return False

folderPath = 'testData2'
httpPort = 8001

def sendPing(sock, targetIP, targetPort, stopEvent, handshakeComplete):
    print(f"Sending to {targetIP}:{targetPort}")
    
    try:
        while not stopEvent.is_set():
            #Handshake
            try:
                sock.sendto(b"HELLO", (targetIP, targetPort))
            except socket.error as e:
                print(f"Error sending handshake: {e}")
            
            if not handshakeComplete.wait(timeout=1.0):
                continue 

            try:
                currentHash = hashFolder(folderPath)
                currentModTime = getFolderModTime(folderPath)
                
                message = f"{currentHash}|{currentModTime}|{httpPort}".encode()
                sock.sendto(message, (targetIP, targetPort))
                print(f"Sent message to {targetIP}:{targetPort}")
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
                
                if message == "SERVER_READY":
                    continue
                
                if message == "DOWNLOAD_COMPLETE":
                    continue
                
                if message == "REQUEST_FILES":
                    httpServer = startHTTPServer(httpPort, folderPath)
                    
                    # Send Server Ready
                    sock.sendto(b"SERVER_READY", addr)
                    
                    waitStart = time.time()
                    downloadComplete = False
                    sock.settimeout(0.5)
                    
                    while time.time() - waitStart < 120:
                        try:
                            data, addr2 = sock.recvfrom(1024)
                            msg = data.decode()
                            if msg == "DOWNLOAD_COMPLETE":
                                downloadComplete = True
                                break
                        except socket.timeout:
                            continue
                    
                    sock.settimeout(1.0)
                    httpServer.shutdown()
                    
                    continue
                
                if handshakeComplete.is_set() and '|' in message:
                    print(f"Received from {addr}: {message}")
                    
                    parts = message.split('|')
                    theirHash = parts[0]
                    theirModTime = float(parts[1])
                    theirHttpPort = int(parts[2])
                    
                    currentHash = hashFolder(folderPath)
                    currentModTime = getFolderModTime(folderPath)
                    
                    if currentHash == theirHash:
                        print('SAME')
                    else:                        
                        # Determine who needs to update
                        if currentModTime < theirModTime:
                            print(f"Our folder is OLDER ({currentModTime} < {theirModTime})")
                            sock.sendto(b"REQUEST_FILES", addr)
                            
                            waitStart = time.time()
                            serverReady = False
                            sock.settimeout(0.5)
                            
                            while time.time() - waitStart < 10:
                                try:
                                    data, addr2 = sock.recvfrom(1024)
                                    msg = data.decode()
                                    if msg == "SERVER_READY":
                                        serverReady = True
                                        break
                                except socket.timeout:
                                    continue
                            
                            sock.settimeout(1.0)
                            
                            if serverReady:
                                if downloadFolder(addr[0], theirHttpPort, folderPath):
                                    print("Download complete! Folder synced.")
                                else:
                                    print("Download failed!")
                            else:
                                print("Server ready timeout - download aborted")
                                
                            currentHash = hashFolder(folderPath)
                            currentModTime = getFolderModTime(folderPath)
                            
                            sock.sendto(b"DOWNLOAD_COMPLETE", addr)
                        else:
                            print(f"Their folder is OLDER ({theirModTime} < {currentModTime})")
                    
                    # Send our current hash back
                    response = f"{currentHash}|{currentModTime}|{httpPort}".encode()
                    sock.sendto(response, addr)
                    print(f"Sent hash back to {addr}")
                    
                    # Reset handshake
                    print("Comparison done. Resetting handshake.\n")
                    handshakeComplete.clear()
                    time.sleep(2)

            except socket.timeout:
                continue
            except socket.error as e:
                if not stopEvent.is_set():
                    print(f"Error receiving: {e}")
    
    except Exception as e:
        print(f"Thread error: {e}")
    finally:
        print("Receive thread stopped")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('ip', help='Target IP address')
    parser.add_argument('port', type=int, help='Target port number')    
    parser.add_argument('--bind-port', type=int, default=0, help='Local port to bind for receiving (default: random)')
    
    args = parser.parse_args()
    
    if not os.path.exists(folderPath):
        print(f"Error: Folder '{folderPath}' does not exist")
        sys.exit(1)
    
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