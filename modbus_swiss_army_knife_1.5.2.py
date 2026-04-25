#!/usr/bin/env python3
"""
============================================================
Modbus Swiss Army Knife (v1.5.2)

This script was vibe coded by Mike Holcomb of UtilSec, LLC.

LinkedIn : https://www.linkedin.com/in/mikeholcomb
Website  : https://mikeholcomb.com
============================================================
"""

import sys
import os
import time
import random
import argparse
from datetime import datetime
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

MAX_LENGTH = 1000
LOG_FILE = None

# Smart-scan tuning. Block sizes stay under the Modbus spec maximums (125 HRs, 2000 coils)
# with margin for devices that quietly enforce smaller limits.
SCAN_DEFAULT_RANGE = 1000
SCAN_BLOCK_COILS = 800
SCAN_BLOCK_REGISTERS = 100

# Standard Modbus FC 43 Device Identification object IDs (per the Modbus spec).
DEVICE_IDENTITY_MAP = {
    0x00: "VendorName",
    0x01: "ProductCode",
    0x02: "MajorMinorRevision",
    0x05: "ModelName",
    0x0A: "ProductName",
}

# ------------------------ Output & Logging ------------------------

def echo(msg):
    """User-facing output only"""
    print(msg)

def log(msg):
    """File-only logging"""
    if not LOG_FILE:
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{timestamp}] {msg}\n")

# ------------------------ Connection ------------------------

def connect_to_modbus(ip, port=502, readonly=False):
    client = ModbusTcpClient(ip, port=port)
    if client.connect():
        echo(f"[✓] Connected to Modbus service at {ip}:{port}")
        log(f"CONNECTED {ip}:{port}")
        if readonly:
            echo("[!] Read-Only Mode ENABLED")
            log("READ_ONLY_MODE ENABLED")
        return client
    else:
        echo("[✗] Failed to connect to Modbus service")
        log(f"FAILED_CONNECT {ip}:{port}")
        return None

# ------------------------ Coil Functions ------------------------

def read_coils(client):
    address = int(input("Enter starting coil address: "))
    count = int(input("Enter number of coils to read: "))

    log(f"READ_COILS addr={address} count={count}")
    result = client.read_coils(address, count)

    if result.isError():
        echo("Failed to read coils.")
        log("ERROR read_coils")
        return

    for i, val in enumerate(result.bits[:count]):
        echo(f"Coil[{address + i}] = {int(val)}")
        log(f"Coil[{address + i}] = {int(val)}")

def write_coil(client, readonly):
    if readonly:
        echo("Write blocked: Read-only mode.")
        log("WRITE_COIL blocked")
        return

    address = int(input("Enter coil address: "))
    value = int(input("Enter value (0 or 1): "))

    log(f"WRITE_COIL addr={address} value={value}")
    result = client.write_coil(address, bool(value))

    if result.isError():
        echo("Failed to write coil.")
        log("ERROR write_coil")
    else:
        echo(f"Coil[{address}] set to {value}")
        log("WRITE_SUCCESS")

# ------------------------ Register Functions ------------------------

def read_registers(client):
    address = int(input("Enter starting register address: "))
    count = int(input("Enter number of registers to read: "))

    log(f"READ_REGISTERS addr={address} count={count}")
    result = client.read_holding_registers(address, count)

    if result.isError():
        echo("Failed to read registers.")
        log("ERROR read_registers")
        return

    for i, val in enumerate(result.registers):
        echo(f"Register[{address + i}] = {val}")
        log(f"Register[{address + i}] = {val}")

def write_register(client, readonly):
    if readonly:
        echo("Write blocked: Read-only mode.")
        log("WRITE_REGISTER blocked")
        return

    address = int(input("Enter register address: "))
    value = int(input("Enter value (0-65535): "))

    log(f"WRITE_REGISTER addr={address} value={value}")
    result = client.write_register(address, value)

    if result.isError():
        echo("Failed to write register.")
        log("ERROR write_register")
    else:
        echo(f"Register[{address}] set to {value}")
        log("WRITE_SUCCESS")

# ------------------------ Scanning ------------------------

def _smart_scan(client, item_label, max_block, read_fn):
    """Generic smart-scan engine with adaptive block sizing.

    Starts with a large block and halves on failure until either the block fits the
    device's address space or we reach single-address probing. A failure at single-
    address means we've hit the end of the responsive region, so we stop.

    item_label : "coil" or "register" (used in prompts/output)
    max_block  : initial block size to try; halved adaptively on failure
    read_fn    : client method - signature (address, count) -> result

    Note: this stops at the first single-address failure, so devices with gaps in their
    address space (responsive at 0-99, dead at 100-199, responsive again at 200+) will
    only have the first contiguous region reported.
    """
    range_input = input(f"Enter scan range (default {SCAN_DEFAULT_RANGE}): ").strip()
    scan_range = int(range_input) if range_input else SCAN_DEFAULT_RANGE

    echo(f"Smart-scanning {scan_range} {item_label}s (starting block size {max_block}, adaptive)...")
    log(f"SMART_SCAN_{item_label.upper()} started range={scan_range} max_block={max_block}")

    responsive = 0
    response_ranges = []
    range_start = None
    range_end = None

    address = 0
    block = max_block
    while address < scan_range:
        count = min(block, scan_range - address)
        try:
            result = read_fn(address, count)
            errored = result.isError()
        except (ModbusException, OSError, ConnectionError) as e:
            log(f"SMART_SCAN_{item_label.upper()} block_exception addr={address} count={count} {e}")
            errored = True

        if not errored:
            responsive += count

            if range_start is None:
                range_start = address
            range_end = address + count - 1

            address += count
            # Block size sticks at whatever last worked - don't grow it back up
        elif count == 1:
            # Single-address probe failed: we've hit the end of the responsive region.
            break
        else:
            # Block was too large (either device PDU limit or spanning the boundary).
            # Halve and retry the same address.
            block = max(1, count // 2)

    if range_start is not None:
        response_ranges.append((range_start, range_end))

    # --- Report ---
    echo(f"\n--- Smart Scan Results: {item_label}s ---")
    echo(f" Probed         : 0 to {scan_range - 1}")
    echo(f" Responsive     : {responsive}")

    if response_ranges:
        echo(f" Response ranges:")
        for start, end in response_ranges:
            echo(f"   {start}-{end}  ({end - start + 1} {item_label}s)")
    else:
        echo(f" Response ranges: (none)")

    log(f"SMART_SCAN_{item_label.upper()} completed responsive={responsive} "
        f"ranges={response_ranges}")


def scan_coils(client):
    _smart_scan(
        client,
        item_label="coil",
        max_block=SCAN_BLOCK_COILS,
        read_fn=client.read_coils,
    )


def scan_registers(client):
    _smart_scan(
        client,
        item_label="register",
        max_block=SCAN_BLOCK_REGISTERS,
        read_fn=client.read_holding_registers,
    )

# ------------------------ Device Identity ------------------------

def read_device_identity(client):
    echo("Reading device identity...")
    log("READ_DEVICE_IDENTITY")

    result = client.read_device_information()
    if result.isError():
        echo("Failed to retrieve device identity.")
        log("ERROR read_device_identity")
        return

    for obj_id, label in DEVICE_IDENTITY_MAP.items():
        value = result.information.get(obj_id, b"").decode(errors="ignore")
        echo(f"{label}: {value}")
        log(f"{label}: {value}")

def banner_grab(client, target_ip, target_port):
    """Quick fingerprint: device identity + sample coil/register values in one shot.

    Combines what nmap's modbus-discover script does (FC 43) with a small live-data
    snapshot, so the operator gets an at-a-glance picture of the device without
    having to run multiple menu options.
    """
    SAMPLE_COUNT = 16
    BAR = "=" * 60

    echo(f"\n{BAR}")
    echo(" MODBUS BANNER GRAB")
    echo(BAR)
    log(f"BANNER_GRAB target={target_ip}:{target_port}")

    # --- Connection info ---
    echo(f" Target          : {target_ip}:{target_port}")
    echo(f" Unit ID   : {getattr(client, 'unit_id', 1)}")
    echo(f" Timestamp       : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # --- Device identity (FC 43) ---
    echo(f"\n[Device Identity - FC 43]")
    try:
        result = client.read_device_information()
        if result.isError():
            echo(" (device did not respond to FC 43)")
            log("BANNER_GRAB FC43_unsupported")
        else:
            for obj_id, label in DEVICE_IDENTITY_MAP.items():
                value = result.information.get(obj_id, b"").decode(errors="ignore")
                if value:
                    echo(f" {label:<20}: {value}")
                    log(f"BANNER_GRAB {label}={value}")
    except (ModbusException, OSError, ConnectionError) as e:
        echo(f" (FC 43 query failed: {e})")
        log(f"BANNER_GRAB FC43_error {e}")

    # --- Coil snapshot (FC 1) ---
    echo(f"\n[Coil Snapshot - first {SAMPLE_COUNT}]")
    try:
        result = client.read_coils(0, SAMPLE_COUNT)
        if result.isError():
            echo(" (no coils responded at address 0)")
        else:
            bits = [int(b) for b in result.bits[:SAMPLE_COUNT]]
            echo(" Address : " + " ".join(f"{i:>2}" for i in range(SAMPLE_COUNT)))
            echo(" Value   : " + " ".join(f"{b:>2}" for b in bits))
            log(f"BANNER_GRAB coils={bits}")
    except (ModbusException, OSError, ConnectionError) as e:
        echo(f" (coil read failed: {e})")
        log(f"BANNER_GRAB coil_error {e}")

    # --- Holding register snapshot (FC 3) ---
    echo(f"\n[Holding Register Snapshot - first {SAMPLE_COUNT}]")
    try:
        result = client.read_holding_registers(0, SAMPLE_COUNT)
        if result.isError():
            echo(" (no registers responded at address 0)")
        else:
            for i, val in enumerate(result.registers):
                signed = val if val < 32768 else val - 65536
                echo(f" Register[{i:>2}] = {val:>5}  (signed: {signed:>6})")
            log(f"BANNER_GRAB registers={list(result.registers)}")
    except (ModbusException, OSError, ConnectionError) as e:
        echo(f" (register read failed: {e})")
        log(f"BANNER_GRAB register_error {e}")

    # --- Discrete input snapshot (FC 2) ---
    echo(f"\n[Discrete Input Snapshot - first {SAMPLE_COUNT}]")
    try:
        result = client.read_discrete_inputs(0, SAMPLE_COUNT)
        if result.isError():
            echo(" (no discrete inputs responded at address 0)")
        else:
            bits = [int(b) for b in result.bits[:SAMPLE_COUNT]]
            echo(" Address : " + " ".join(f"{i:>2}" for i in range(SAMPLE_COUNT)))
            echo(" Value   : " + " ".join(f"{b:>2}" for b in bits))
            log(f"BANNER_GRAB discrete_inputs={bits}")
    except (ModbusException, OSError, ConnectionError) as e:
        echo(f" (discrete input read failed: {e})")
        log(f"BANNER_GRAB di_error {e}")

    echo(f"{BAR}\n")
    log("BANNER_GRAB completed")

# ------------------------ Advanced Actions ------------------------

def flip_all_coils(client, readonly):
    if readonly:
        echo("Flip blocked: Read-only mode.")
        log("FLIP_COILS blocked")
        return

    echo("Flipping all available coils...")
    log("FLIP_COILS started")
    count = 0

    for i in range(MAX_LENGTH):
        if not client.read_coils(i, 1).isError():
            count += 1
        else:
            break

    result = client.read_coils(0, count)
    if result.isError():
        echo("Failed to read coils.")
        log("ERROR flip_read")
        return

    for i, val in enumerate(result.bits[:count]):
        client.write_coil(i, not val)

    echo(f"Flipped {count} coils.")
    log(f"FLIP_COILS completed count={count}")

def zero_all_coils(client, readonly):
    if readonly:
        echo("Zeroing blocked: Read-only mode.")
        log("ZERO_COILS blocked")
        return

    echo("Zeroing all available coils...")
    log("ZERO_COILS started")
    count = 0

    for i in range(MAX_LENGTH):
        if not client.read_coils(i, 1).isError():
            count += 1
        else:
            break

    for i in range(count):
        client.write_coil(i, False)

    echo(f"Zeroed {count} coils.")
    log(f"ZERO_COILS completed count={count}")

def fuzz_registers(client, readonly):
    if readonly:
        echo("Fuzzing blocked: Read-only mode.")
        log("FUZZ_REGISTERS blocked")
        return

    echo("Fuzzing holding registers...")
    log("FUZZ_REGISTERS started")
    count = 0

    for i in range(MAX_LENGTH):
        if not client.read_holding_registers(i, 1).isError():
            count += 1
        else:
            break

    for i in range(count):
        value = random.randint(0, 65535)
        result = client.write_register(i, value)
        if not result.isError():
            log(f"Register[{i}] fuzzed value={value}")

    echo(f"Fuzzed {count} registers.")
    log(f"FUZZ_REGISTERS completed count={count}")

def hold_write(client, readonly):
    """Continuously write a value to a coil or register at a fixed interval until interrupted.

    Many controllers re-assert outputs every scan cycle, so a one-shot write is overwritten
    almost immediately. Holding the target value in a tight loop wins the race against the
    controller's scan, which is the realistic shape of an actuator-override attack.
    """
    if readonly:
        echo("Hold blocked: Read-only mode.")
        log("HOLD_WRITE blocked")
        return

    target_type = input("Target type ([c]oil or [r]egister): ").strip().lower()
    if not target_type or target_type[0] not in ("c", "r"):
        echo("Invalid target type. Use 'c' for coil or 'r' for register.")
        return
    is_coil = target_type[0] == "c"

    address = int(input("Enter target address: "))

    if is_coil:
        value_input = int(input("Enter value (0 or 1): "))
        value = bool(value_input)
        display_value = int(value)
    else:
        value = int(input("Enter value (0-65535): "))
        display_value = value

    interval_input = input("Interval between writes in seconds (default 0.1): ").strip()
    interval = float(interval_input) if interval_input else 0.1

    duration_input = input("Duration in seconds (blank or 0 = run until Ctrl+C): ").strip()
    duration = float(duration_input) if duration_input else 0

    target_label = f"{'Coil' if is_coil else 'Register'}[{address}]={display_value}"

    echo(f"\n[hold] Holding {target_label} every {interval}s. Press Ctrl+C to stop.")
    log(f"HOLD_WRITE_START target={target_label} interval={interval}s duration={duration}s")

    writes = 0
    errors = 0
    start = time.time()

    try:
        while True:
            try:
                if is_coil:
                    result = client.write_coil(address, value)
                else:
                    result = client.write_register(address, value)

                if result.isError():
                    errors += 1
                else:
                    writes += 1
            except (ModbusException, OSError, ConnectionError):
                errors += 1

            elapsed = time.time() - start
            sys.stdout.write(
                f"\r[hold] {target_label} | elapsed: {int(elapsed)}s | "
                f"writes: {writes} | errors: {errors}   "
            )
            sys.stdout.flush()

            if duration > 0 and elapsed >= duration:
                break

            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        elapsed = time.time() - start
        sys.stdout.write("\n")
        sys.stdout.flush()
        echo(f"[hold] Stopped. Total writes: {writes}, errors: {errors}, elapsed: {int(elapsed)}s")
        log(f"HOLD_WRITE_END target={target_label} writes={writes} errors={errors} elapsed={int(elapsed)}s")

# ------------------------ Log Viewer ------------------------

def view_log():
    if not LOG_FILE or not os.path.exists(LOG_FILE):
        echo("Logging is not enabled or log file not found.")
        return

    echo("\n--- Current Log File ---")
    with open(LOG_FILE, "r") as f:
        print(f.read())
    echo("--- End of Log ---")

# ------------------------ Menu ------------------------

def show_menu(client, readonly, target_ip, target_port):
    while True:
        print("\n--- Modbus Utility Menu ---")
        print("1.  Read Coils")
        print("2.  Write Coil")
        print("3.  Read Registers")
        print("4.  Write Register")
        print("5.  Scan for Coils")
        print("6.  Scan for Registers")
        print("7.  Read Device Identity")
        print("8.  Recon Overview")
        print("9.  Flip Coils")
        print("10. Zero All Coils")
        print("11. Fuzz Registers")
        print("12. Hold Write (loop until interrupted)")
        print("13. View Log File")
        print("14. Exit")

        choice = input("Select an option: ")

        try:
            if choice == "1":
                read_coils(client)
            elif choice == "2":
                write_coil(client, readonly)
            elif choice == "3":
                read_registers(client)
            elif choice == "4":
                write_register(client, readonly)
            elif choice == "5":
                scan_coils(client)
            elif choice == "6":
                scan_registers(client)
            elif choice == "7":
                read_device_identity(client)
            elif choice == "8":
                banner_grab(client, target_ip, target_port)
            elif choice == "9":
                flip_all_coils(client, readonly)
            elif choice == "10":
                zero_all_coils(client, readonly)
            elif choice == "11":
                fuzz_registers(client, readonly)
            elif choice == "12":
                hold_write(client, readonly)
            elif choice == "13":
                view_log()
            elif choice == "14":
                log("SESSION_END")
                break
            else:
                echo("Invalid option.")
        except (ValueError, ModbusException) as e:
            echo("Operation failed.")
            log(f"ERROR {e}")

# ------------------------ Main ------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Modbus Utility Tool")
    parser.add_argument("ip", help="Target Modbus TCP IP address")
    parser.add_argument("--readonly", action="store_true", help="Enable read-only mode")
    parser.add_argument("--log", action="store_true", help="Enable file logging")
    args = parser.parse_args()

    if args.log:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        LOG_FILE = f"modbus_log_{ts}.log"
        log("LOGGING_ENABLED")

    client = connect_to_modbus(args.ip, readonly=args.readonly)

    if client:
        try:
            show_menu(client, args.readonly, args.ip, 502)
        finally:
            client.close()
            log("DISCONNECTED")
