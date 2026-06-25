# Peer-to-Peer File Syncer

A lightweight tool that keeps folders in sync between computers over your local network. It notices when files change, get added, or get deleted, and automatically updates the other machines.

Multiple folders and multiple peers can be synced at the same time, and the folder locations on each computer don't have to match.

---

## How It Works

Each computer runs a small background agent that:

1. **Says hello** — Computers find each other over the network and confirm they're both online.
2. **Compares folders** — Each side generates a "fingerprint" of its files and shares it with the others.
3. **Figures out what's different** — If the fingerprints don't match, the computer with the older files requests the newer ones.
4. **Downloads only what changed** — Instead of re-sending everything, only new or missing files are transferred.
5. **Cleans up safely** — Deleted files are removed after the transfer, so nothing is wiped by accident.

```
  Your Computer                        Other Computer(s)
  ─────────────                        ─────────────────
  [ Network Thread ] <── Hello/Ack ──> [ Network Thread ]
         │                                    ▲
   Compare files                              │
         ▼                                    │
  [ File Server ] <───── Download files ──────┘
```

---

## Setup

### Requirements

- Python 3.6 or newer on all computers
- All computers on the same network, with firewalls allowing the ports you choose
  ```

### Configuration File

Each computer needs a `sync_config.json` file in the same folder as the script. It has two sections:

- **`peers`** — the IP addresses of the other computers to sync with
- **`sync_folders`** — which local folders to sync, and on what port

The `"name"` field is how computers know which folders match up across machines — the actual folder paths can be completely different on each machine.

**Example `sync_config.json`:**
```json
{
  "peers": [
    "192.168.1.50",
    "192.168.1.51",
    "192.168.1.52"
  ],
  "sync_folders": [
    {
      "name": "project-alpha",
      "local_path": "./alpha",
      "http_port": 8001
    },
    {
      "name": "shared-documents",
      "local_path": "/home/alice/documents",
      "http_port": 8002
    }
  ]
}
```

> The `"name"` values must be identical on all machines for a folder pair to sync. The `local_path` can differ between machines.

---

## Running the Agent

### Command format

```bash
python main.py <port> [--config <config-file>]
```

- `<port>` — the UDP port this agent listens on (must be the same across all machines)
- `--config` — optional path to your config file (defaults to `sync_config.json`)

### Example

All machines use the same port. Peer IPs are defined in the config file, not on the command line.

```bash
python main.py 9000
```

Or with a custom config path:

```bash
python main.py 9000 --config /path/to/my_config.json
```