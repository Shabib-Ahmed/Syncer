import socket
import threading
import time
import argparse
import sys
import hashlib
import os
import urllib.request
import urllib.parse
import json
import logging
from http.server import SimpleHTTPRequestHandler, HTTPServer

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def load_config(config_path="sync_config.json"):
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logging.critical(f"Failed to load config file: {e}")
        sys.exit(1)

def hashFile(filePath):
    sha256 = hashlib.sha256()
    try:
        with open(filePath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception:
        return ""

def hashFolder(folderPath):
    combined = hashlib.sha256()
    if not os.path.exists(folderPath):
        return combined.hexdigest()
        
    for root, dirs, files in os.walk(folderPath):
        for filename in sorted(files):
            filepath = os.path.join(root, filename)
            relativePath = os.path.relpath(filepath, folderPath)
            combined.update(relativePath.encode())
            combined.update(hashFile(filepath).encode())
    return combined.hexdigest()

def getFolderModTime(folderPath):
    latestMod = 0
    if not os.path.exists(folderPath):
        return latestMod
        
    for root, dirs, files in os.walk(folderPath):
        for filename in files:
            filepath = os.path.join(root, filename)
            try:
                modTime = os.path.getmtime(filepath)
                latestMod = max(latestMod, modTime)
            except OSError:
                continue
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
                        fileList.append(relPath.replace(os.sep, '/'))
            
            self.wfile.write(json.dumps(fileList).encode())
        else:
            super().do_GET()
    
    def log_message(self, format, *args):
        pass

def startHTTPServer(port, directory):
    from functools import partial
    handler = partial(CustomHTTPHandler, directory=os.path.abspath(directory))
    try:
        server = HTTPServer(('0.0.0.0', port), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server
    except Exception as e:
        logging.critical(f"Failed to start HTTP server on port {port}: {e}")
        sys.exit(1)

def downloadFolder(sourceIP, sourcePort, destFolder):
    try:
        url = f"http://{sourceIP}:{sourcePort}/filelist.json"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            remoteFiles = json.loads(response.read().decode())
        
        os.makedirs(destFolder, exist_ok=True)
        remotePathsLocalFormat = []
        
        for relPath in remoteFiles:
            localRelPath = relPath.replace('/', os.sep)
            remotePathsLocalFormat.append(localRelPath)
            
            fileUrl = f"http://{sourceIP}:{sourcePort}/{urllib.parse.quote(relPath)}"
            destPath = os.path.join(destFolder, localRelPath)
            
            os.makedirs(os.path.dirname(destPath), exist_ok=True)
            urllib.request.urlretrieve(fileUrl, destPath)
        
        for root, dirs, files in os.walk(destFolder):
            for filename in files:
                localFilePath = os.path.join(root, filename)
                localRelPath = os.path.relpath(localFilePath, destFolder)
                if localRelPath not in remotePathsLocalFormat:
                    os.remove(localFilePath)
        return True
    except Exception as e:
        logging.error(f"Download failed from {sourceIP}:{sourcePort}: {e}")
        return False

def sendPing(sock, targetPort, peers, sync_folders, stopEvent, verified_peers):
    while not stopEvent.is_set():
        try:
            for peer_ip in peers:
                sock.sendto(b"HELLO", (peer_ip, targetPort))
                
                if peer_ip not in verified_peers or (time.time() - verified_peers[peer_ip]) > 15:
                    continue

                for folder in sync_folders:
                    name = folder["name"]
                    path = folder["local_path"]
                    port = folder["http_port"]
                    
                    currentHash = hashFolder(path)
                    currentModTime = getFolderModTime(path)
                    
                    message = f"{name}|{currentHash}|{currentModTime}|{port}".encode()
                    sock.sendto(message, (peer_ip, targetPort))
            
            time.sleep(5)
        except Exception:
            time.sleep(5)

def receivePing(sock, targetPort, sync_folders, stopEvent, verified_peers):
    sock.settimeout(1.0)
    folder_map = {f["name"]: f for f in sync_folders}
    
    while not stopEvent.is_set():
        try:
            data, addr = sock.recvfrom(1024)
            peer_ip = addr[0]
            message = data.decode()
            
            if message == "HELLO":
                sock.sendto(b"HELLO_ACK", addr)
                continue
                
            if message == "HELLO_ACK":
                verified_peers[peer_ip] = time.time()
                continue
            
            if message.startswith("REQUEST_FILES:"):
                requested_name = message.split(":")[1]
                if requested_name in folder_map:
                    sock.sendto(f"SERVER_READY:{requested_name}".encode(), addr)
                continue
            
            if message.startswith("SERVER_READY:") or message.startswith("DOWNLOAD_COMPLETE:"):
                continue
            
            if '|' in message:
                parts = message.split('|')
                if len(parts) < 4:
                    continue
                    
                folderName = parts[0]
                theirHash = parts[1]
                theirModTime = float(parts[2])
                theirHttpPort = int(parts[3])
                
                if folderName not in folder_map:
                    continue
                    
                local_folder = folder_map[folderName]
                currentHash = hashFolder(local_folder["local_path"])
                currentModTime = getFolderModTime(local_folder["local_path"])
                
                if currentHash == theirHash:
                    pass
                else:                        
                    if currentModTime < theirModTime:
                        logging.info(f"[{folderName}] Local is older than state on {peer_ip}. Syncing...")
                        sock.sendto(f"REQUEST_FILES:{folderName}".encode(), addr)
                        
                        waitStart = time.time()
                        serverReady = False
                        sock.settimeout(0.5)
                        
                        while time.time() - waitStart < 5:
                            try:
                                data, addr2 = sock.recvfrom(1024)
                                msg = data.decode()
                                if msg == f"SERVER_READY:{folderName}" and addr2[0] == peer_ip:
                                    serverReady = True
                                    break
                            except socket.timeout:
                                continue
                        
                        sock.settimeout(1.0)
                        
                        if serverReady:
                            if downloadFolder(peer_ip, theirHttpPort, local_folder["local_path"]):
                                logging.info(f"[{folderName}] Sync successful from {peer_ip}.")
                                sock.sendto(f"DOWNLOAD_COMPLETE:{folderName}".encode(), addr)
                        else:
                            logging.warning(f"[{folderName}] Peer server timeout from {peer_ip}.")
                            
        except socket.timeout:
            continue
        except Exception:
            pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('port', type=int, help='Global mesh network UDP signaling port')    
    parser.add_argument('--config', default='sync_config.json', help='Path to configuration JSON file')
    args = parser.parse_args()
    
    config = load_config(args.config)
    sync_folders = config.get("sync_folders", [])
    peers = config.get("peers", [])
    
    if not sync_folders:
        logging.critical("No folders found configured in config file.")
        sys.exit(1)
        
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', args.port))
        logging.info(f"Mesh signaling listening on UDP port {args.port}")
    except socket.error as e:
        logging.critical(f"Could not bind UDP signaling port {args.port}: {e}")
        sys.exit(1)
    
    http_servers = []
    for folder in sync_folders:
        path = folder["local_path"]
        port = folder["http_port"]
        os.makedirs(path, exist_ok=True)
        server = startHTTPServer(port, path)
        http_servers.append(server)
        logging.info(f"Serving directory '{path}' [Ident: {folder['name']}] on port {port}")
    
    stop_event = threading.Event()
    verified_peers = {}
    
    sendThread = threading.Thread(
        target=sendPing, 
        args=(sock, args.port, peers, sync_folders, stop_event, verified_peers),
        daemon=True
    )
    receiveThread = threading.Thread(
        target=receivePing, 
        args=(sock, args.port, sync_folders, stop_event, verified_peers),
        daemon=True
    )
    
    sendThread.start()
    receiveThread.start()
    
    logging.info("Multi-PC sync agent active.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        for server in http_servers:
            server.shutdown()
        sock.close()

if __name__ == '__main__':
    main()