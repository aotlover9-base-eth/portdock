# portdock

> **Interactive Port Conflict Resolver & Ghost Process Dissector for Linux & macOS**  
> *Day 6 of 100 Days, 100 Problems, 100 Solutions*

![portdock terminal dashboard](assets/preview.png)

`portdock` is a high-performance terminal utility and interactive TUI engineered to inspect, diagnose, and resolve port collisions in milliseconds. Unlike traditional `kill-port` or `lsof -i :PORT | kill` one-liners, `portdock` dissects process supervisor hierarchies (e.g. `npm` -> `nodemon` -> `node`), traces Docker container mappings, and purges resilient ghost worker trees so dev servers do not resurrect.

---

## Key Features

- **Sub-50ms Socket Kill**: Graceful `SIGTERM` with 200ms escalation to `SIGKILL` and kernel socket release verification.
- **Ghost Process Dissector (`-t, --tree`)**: Climbs the process hierarchy to terminate root supervisors (`nodemon`, `vite`, `cargo-watch`) and all child workers in one sweep.
- **Zero-Flicker Interactive TUI**: Atomic in-memory frame rendering over alternate screen buffer (`\x1b[?1049h\x1b[?25l`) with windowed viewport scrolling.
- **Dev vs System Sockets Toggle (`[Tab]`)**: Clean developer view by default; hides 30+ root OS daemons with instant one-key switching.
- **Safe Action Confirmation**: Inline verification prompts for `k` (Kill) and `t` (Tree Kill) with `[Enter] Confirm` / `[Esc] Cancel`.
- **Live Search & Filter (`/` or `f`)**: Real-time filtering by port, process name, or IP with instant table updates.
- **Deep Port Inspector (`portdock <port>`)**: Inspects any port, displaying bind scope (`[LOCAL]` vs `[PUBLIC]`), process hierarchy, command line, and worker trees.
- **Docker Mapping Detection**: Identifies whether a port is held by a Docker container (`docker-proxy`) and displays container name and image.
- **Scriptable Automation**: Includes `portdock wait <port>` and `portdock list --json` for CI/CD and deployment healthchecks.

---

## Installation

### Automated Installer (Recommended)
```bash
curl -fsSL https://raw.githubusercontent.com/aotlover9-base-eth/portdock/main/install.sh | bash
```

### From Source
```bash
git clone https://github.com/aotlover9-base-eth/portdock.git
cd portdock
./install.sh
```

### Via Pip / Pipx
```bash
pip install .
```

---

## Quick Start & Usage

### 1. Launch Interactive TUI Dashboard
Run `portdock` without arguments in any terminal:
```bash
portdock
```

#### Keyboard Shortcuts:
- `↑ / ↓` or `j / k` -> Navigate listening ports (zero-flicker)
- `[Tab]` -> Toggle Dev Apps view vs All Ports (including system daemons)
- `[Enter]` or `d` -> Dissect / inspect port card & process tree
- `k` -> Standard kill with `[Enter]` confirmation prompt
- `t` -> Tree kill (terminates parent supervisor + worker tree)
- `/` or `f` -> Live interactive search filter
- `r` -> Refresh list
- `q` or `Esc` -> Exit

---

### 2. Command-Line Port Kill

Terminate a process holding port 3000:
```bash
portdock kill 3000
```

Batch kill multiple ports:
```bash
portdock kill 3000 8080 5432
```

Ghost Process Killer (Purge supervisor + child worker tree):
```bash
portdock kill 3000 -t
```

Immediate Force Kill (`SIGKILL` without graceful escalation):
```bash
portdock kill 3000 -f
```

---

### 3. Deep Port Inspection (`portdock <port>`)

Inspect what is occupying a port:
```bash
portdock 3000
# or
portdock :8080
```

Displays:
- **Bind Type**: `[LOCAL] Localhost Only (127.0.0.1)` vs `[PUBLIC] All Interfaces (0.0.0.0)`
- **Process Metadata**: PID, User, Memory RSS, CPU %, Uptime, Working Directory
- **Supervisor Hierarchy**: `npm (4990) -> nodemon (4995) -> node (5000)`
- **Full Process Tree**: Visual branch of all worker threads and child subprocesses
- **Docker Container**: Container name and image if bound through Docker

---

### 4. Listing Ports & Automation

List active listening ports:
```bash
portdock list
```

Filter by process type or network exposure:
```bash
portdock list --apps      # Developer and user applications only (hides OS daemons)
portdock list --system    # OS background daemons only
portdock list --public    # Ports exposed to 0.0.0.0 / all interfaces
portdock list --local     # Localhost-only ports (127.0.0.1 / ::1)
```

Export as structured JSON:
```bash
portdock list --json
```

Wait for a port to be freed (e.g. before starting a service):
```bash
portdock wait 3000 --timeout 15
```

Wait for a server to become healthy/open:
```bash
portdock wait 3000 --open --timeout 30
```

---

## CLI Reference

```text
usage: portdock [-h] [-v] {list,kill,free,wait,dissect,inspect} ...

portdock - Interactive Port Conflict Resolver & Ghost Process Dissector

positional arguments:
  {list,kill,free,wait,dissect,inspect}
    list                List listening ports (--apps, --system, --local, --public, --json)
    kill (free)         Terminate process(es) holding specified port(s)
    wait                Wait for a port to be freed or opened (--timeout, --open)
    dissect (inspect)   Deep inspection of a port and its process tree

options:
  -h, --help            Show this help message and exit
  -v, --version         Show program's version number and exit

Kill Options:
  -t, --tree            Ghost killer: terminate supervisor + all child processes
  -f, --force           Immediate SIGKILL without graceful SIGTERM period
  -p, --proto           Protocol: tcp or udp (default: tcp)
  -q, --quiet           Quiet mode (exit code only)
```

---

## License

MIT License. Built for developer productivity.
