# Modbus Swiss Army Knife

A menu-driven Modbus TCP utility for OT/ICS security testing, training, and research. Built as a hands-on tool for learning how Modbus works, how it can be attacked, and what defenders can do about it.

> ⚠️ **For authorized testing only.** Modbus has no native authentication, so this tool's writes succeed against any reachable device. See [Ethical Use](#ethical-use) before pointing it at anything.

## Features

The tool exposes core Modbus TCP operations through an interactive numbered menu:

### Recon
- **Read Device Identity** — pull vendor, product, and revision via FC 43
- **Recon Overview** — one-shot fingerprint combining device identity with coil, register, and discrete-input snapshots
- **Smart Scan for Coils / Registers** — adaptive bulk scans that report the device's actual address space size

### Read & Write
- **Read Coils / Registers** — targeted reads at any address
- **Write Coil / Register** — single-shot writes

### Attack & Test
- **Flip Coils** — invert every coil's current value
- **Zero All Coils** — force every coil to 0
- **Fuzz Registers** — random values into every responsive holding register
- **Hold Write** — sustained write loop that wins the race against PLC scan cycles

### Utility
- `--readonly` flag disables all write operations for safe recon
- `--log` writes a timestamped audit trail of every action to a file

## Installation

Requires Python 3.8 or newer.

```bash
git clone https://github.com/utilsec/Modbus-Swiss-Army-Knife.git
cd Modbus-Swiss-Army-Knife
pip install -r requirements.txt
```

## Quick start

```bash
# Recon-only mode - safe default for unfamiliar targets
python modbus_util.py 127.0.0.1 --readonly --log

# Full mode with logging
python modbus_util.py 127.0.0.1 --log
```

After connecting you'll see a numbered menu. Pick an option and follow the prompts.

## Lab walkthrough: ENCO simulator

This tool was designed alongside the **ENCO Building Heating Simulator** — a Python-based simulated PLC that exposes Modbus TCP, Telnet, and a web HMI for a fictional apartment hydronic heating system. It's a safe target for practicing the attack scenarios below.

### Step 1: Reconnaissance

Start the ENCO sim in one terminal, then connect with the tool in another:

```bash
python modbus_util.py 127.0.0.1 --readonly --log
```

Pick option **8** (Recon Overview). In one shot you get device identity, the first 16 coils, the first 16 holding registers, and the first 16 discrete inputs. Pattern-match the values to infer process meaning — three near-identical numbers around 2000 are temperatures × 100, a large signed-negative number is the outdoor sensor, etc.

Then run smart scan (options **5** and **6**) to confirm the device's full address space size.

### Step 2: Single-shot write

Reconnect without `--readonly`. Use option **2** to write coil 0 to 0 — and watch the controller fight back within one second. This demonstrates that a one-shot write doesn't stick against a PLC that re-asserts outputs every scan cycle.

### Step 3: Loud attack via Hold Write

Use option **12**, target type `c` (coil), address `0`, value `0`, default interval. The tool now hammers coil 0 every 100 ms, faster than the controller's 1-second scan can re-assert it. The boiler stays off, zone temperatures drop, and the controller logs `Coil 0 state mismatch` warnings every cycle — the loud-attack signature.

### Step 4: Quiet attack via sensor injection

Same as step 3, but target type `r` (register), address `0`, value `2500`. The controller now reads "all zones at 25 °C," voluntarily turns off the boiler, and *no mismatch warnings fire*. Compare the controller console output to step 3 — that contrast is the lesson.

## How smart scan works

Naive Modbus scanners probe one address at a time, which is slow and tends to overstate results. This tool uses **adaptive block sizing**: it starts with a large block, halves on failure until it finds a size that fits the device's address space, then continues with that size until a single-address read fails (signaling the end of the responsive region).

For a typical small PLC with 100 coils, the scan resolves in ~10 round-trips instead of 1000 — same answer, dramatically faster, less network noise.

Note: the scan stops at the first single-address failure, so devices with non-contiguous address spaces will only have the first contiguous region reported. This is a deliberate trade-off for simplicity — the vast majority of Modbus devices use contiguous spaces starting at 0.

## Roadmap

Planned additions, roughly in priority order:

- Snapshot and diff commands for before/after attack comparison
- Multi-target Hold Write for sensor-injection and hybrid attacks
- Watch mode to observe register/coil values in real time
- Configurable unit/slave ID for gateway scenarios
- Replay mode for reproducible lab exercises

Issues and PRs welcome.

## Ethical use

This tool is provided for:

- Security testing of systems you own or are explicitly authorized to test
- Educational labs and CTF-style exercises against intentionally vulnerable targets like the ENCO simulator
- Research published responsibly through coordinated disclosure

This tool is **not** for:

- Probing or attacking systems you don't own or lack written authorization to test
- Operations against production critical infrastructure
- Any activity that could endanger life, safety, or service availability

Misuse against real OT systems is a felony in most jurisdictions (Computer Fraud and Abuse Act in the US, Computer Misuse Act in the UK, equivalents elsewhere). The author and contributors accept no liability for misuse.

## Author

Created by **Mike Holcomb**, UtilSec, LLC.

- LinkedIn: [linkedin.com/in/mikeholcomb](https://www.linkedin.com/in/mikeholcomb)
- Website: [mikeholcomb.com](https://mikeholcomb.com)

## License

MIT. See [LICENSE](LICENSE) for details.
