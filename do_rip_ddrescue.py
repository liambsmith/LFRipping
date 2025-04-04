import serial
import os
import shutil
import subprocess
from multiprocessing import Process, Lock, Queue
import time
from datetime import datetime
from collections import deque
import signal
import sys

# Configuration
SERIAL_PORT = "/dev/ttyUSB0"  # Serial port for autoloader communication
BAUD_RATE = 38400
INPUT_BINS = [1, 2]  # Input bins (use bin 1 first, then bin 2)
OUTPUT_BINS = [3, 4]  # Output bins (overflow into next)
BIN_CAPACITY = 108  # Maximum discs a bin can hold
DISC_HEIGHT = 12  # Disc height in offset units
DEFAULT_OFFSET = 2304  # Default offset with 0 discs in the bin
DRIVE_NAMES = ["sr3", "sr2", "sr0", "sr1"]  # Linux device names for drives (top to bottom)
LOGFILE = f"logs/log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

# Global lock to ensure only one load/unload operation runs at a time
operation_lock = Lock()

# Maintain recent log entries for terminal output
recent_logs = []

# Initialize queues for real-time output
output_queues = {drive_number: Queue() for drive_number in range(1, 5)}

def send_command(serial_conn, command):
    """Send a command to the autoloader, handle errors, and retry if needed."""
    recalibration_needed = False  # Flag to indicate if recalibration is required

    while True:
        # Send the primary command
        command_bytes = b"\x1B" + command.encode("ascii")
        serial_conn.write(command_bytes)

        while True:
            response = serial_conn.read_until(expected=b"\x04").decode("ascii")
            response = response.replace("\x1B", "+").replace("\x04", "=").strip()
            if response:
                log_message(f"Response to '{command}': {response}")
                break

        # Perform a status check (!e1C)
        status_check_bytes = b"\x1B!e1C"
        serial_conn.write(status_check_bytes)

        while True:
            status_response = serial_conn.read_until(expected=b"\x04").decode("ascii")
            status_response = status_response.replace("\x1B", "+").replace("\x04", "=").strip()

            if status_response == "+!e1000000C":
                # Ready state
                if recalibration_needed:
                    log_message("Ready state detected. Recalibrating...")
                    # setup_bays(serial_conn)
                    # TODO maybe do something else here, for now skip we only need to calibrate when we call the function
                    recalibration_needed = False
                    break # retry it all now that the error was cleared
                return response  # Return the original command response
            elif status_response == "+!e1005000C":
                # Bay door issue (first occurrence logs an error)
                if recalibration_needed is False:
                    log_message(f"Error detected: Bay door issue ({status_response}). Retrying...")
                    recalibration_needed = True
                break  # Retry the command
            elif status_response == "+!e1006000C":
                # Door opened (first occurrence logs an error)
                if recalibration_needed is False:
                    log_message(f"Door opened detected ({status_response}). Waiting for resolution...")
                    recalibration_needed = True
                break  # Retry the command
            else:
                log_message(f"Unexpected status after '{command}': {status_response}")
                return response

def setup_bays(serial_conn):
    """Set up bays by probing all bins and tracking disc state."""
    log_message("Performing initial status check...")
    send_command(serial_conn, "!e1C")  # Clear any pending status

    log_message("Setting up bays...")
    disc_held = False  # Track whether a disc is currently held

    for bin_num in range(1,5):
        recalibrate_bin(bin_num)

    log_message("Bays setup completed.")

def calculate_disc_count(response):
    """Calculate the number of discs in a bin based on the response."""
    if response.startswith("+!f01036000C"):
        return 0  # Empty bin
    if response.startswith("+!f01365534C"):
        return 'Error code in bin count'
    try:
        # Extract the offset value from the response
        offset = int(response[6:10])  # Extract the XXXX portion
        # Convert offset to 108 - X logic
        return BIN_CAPACITY - max(0, (offset - DEFAULT_OFFSET) // DISC_HEIGHT)
    except ValueError:
        log_message(f"Error parsing disc count from response: {response}")
        return "unknown"

def recalibrate_bin(serial_conn, bin_num):
    """Recalibrate a specific bin by performing a pick/place operation."""
    log_message(f"Recalibrating Bin {bin_num}...")
    # Attempt to grab a disc
    grab_command = f"!f120{bin_num-1}2C"
    response = send_command(serial_conn, grab_command)

    if "+!f11C" in response:  # Disc successfully picked up
        log_message(f"Disc picked up from Bin {bin_num}.")
        # Place the disc back
        place_command = f"!f120{bin_num-1}1C"
        send_command(serial_conn, place_command)
        log_message(f"Disc placed back into Bin {bin_num}.")
    elif "+!f10C" in response:  # No disc detected
        log_message(f"Bin {bin_num} is empty.")
    else:
        log_message(f"Unexpected response during recalibration of Bin {bin_num}: {response}")

def query_bin_inventory(serial_conn, bin_num):
    """Query the number of discs in a specific bin and recalibrate if necessary."""
    command = f"!f020{bin_num-1}C"  # Query command for the specific bin
    response = send_command(serial_conn, command)

    if "+!f01365534C" in response:  # Error code for bin count
        log_message(f"Error detected in Bin {bin_num}, recalibrating...")
        recalibrate_bin(serial_conn, bin_num)
        # Retry querying the bin after recalibration
        response = send_command(serial_conn, command)

    if "+!f01036000C" in response:  # Bin is empty
        return 0

    try:
        # Calculate disc count from the response
        return calculate_disc_count(response)
    except ValueError:
        log_message(f"Unexpected response format for Bin {bin_num}: {response}")
        return "unknown"

def load_disc_to_drive(serial_conn, drive_number):
    """Load a disc from the first available input bin into the specified drive."""
    input_bin = None
    # Find the first input bin with discs
    for bin_num in INPUT_BINS:
        if query_bin_inventory(serial_conn, bin_num) > 0:
            input_bin = bin_num
            break

    if not input_bin:
        log_message("No discs available in input bins.")
        return False  # No disc loaded

    log_message(f"Picking a disc from Bin {input_bin}...")
    grab_command = f"!f120{input_bin-1}2C"  # Grab disc from the input bin
    response = send_command(serial_conn, grab_command)
    if "+!f10C" in response:
        log_message(f"No disc available in Bin {input_bin}.")
        return False  # No disc loaded
    elif "+!f11C" in response:
        log_message(f"Disc picked up from Bin {input_bin}.")

    # Move the autoloader to the specified drive bay
    log_message(f"Moving to Drive {drive_number}...")
    move_command = f"!f124{drive_number}0C"  # Move to the drive
    send_command(serial_conn, move_command)

    # Get the Linux device name for the drive
    drive_name = DRIVE_NAMES[drive_number - 1]

    # Open the drive
    log_message(f"Opening Drive {drive_number} ({drive_name})...")
    open_drive(drive_name)

    # Place the disc in the drive
    log_message(f"Placing disc into Drive {drive_number}...")
    place_command = f"!f124{drive_number}1C"  # Place the disc
    send_command(serial_conn, place_command)

    # Close the drive
    log_message(f"Closing Drive {drive_number} ({drive_name})...")
    close_drive(drive_name)

    log_message(f"Disc successfully placed in Drive {drive_number}.")
    return True  # Disc loaded successfully

def unload_disc_to_bin(serial_conn, drive_number):
    """Unload a disc from a drive and move it to the first non-full output bin."""
    # Check which output bin has space
    target_bin = None
    for bin_num in OUTPUT_BINS:
        bin_inventory = query_bin_inventory(serial_conn, bin_num)
        if bin_inventory < BIN_CAPACITY:
            target_bin = bin_num
            break

    if target_bin is None:
        log_message("All output bins are full. Cannot unload disc.")
        return False  # No disc unloaded

    log_message(f"Unloading disc from Drive {drive_number}...")
    # Move autoloader to the drive
    move_to_drive_command = f"!f124{drive_number}0C"
    send_command(serial_conn, move_to_drive_command)

    # Get the Linux device name for the drive
    drive_name = DRIVE_NAMES[drive_number - 1]

    # Open the drive
    log_message(f"Opening Drive {drive_number} ({drive_name})...")
    open_drive(drive_name)

    # Grab the disc from the drive
    grab_command = f"!f124{drive_number}2C"
    send_command(serial_conn, grab_command)
    log_message(f"Disc removed from Drive {drive_number}.")

    # Close the drive
    log_message(f"Closing Drive {drive_number} ({drive_name})...")
    close_drive(drive_name)

    # Move the disc to the target output bin
    log_message(f"Moving disc to Output Bin {target_bin}...")
    move_to_bin_command = f"!f120{target_bin-1}1C"
    send_command(serial_conn, move_to_bin_command)

    log_message(f"Disc successfully placed in Output Bin {target_bin}.")
    return True  # Disc unloaded successfully

def open_drive(drive_name):
    """Open the drive tray using the Linux device name."""
    try:
        subprocess.run(["eject", drive_name], check=True)
        log_message(f"Drive {drive_name} opened successfully.")
    except subprocess.CalledProcessError:
        log_message(f"Failed to open drive {drive_name}.")

def close_drive(drive_name):
    """Close the drive tray using the Linux device name."""
    try:
        subprocess.run(["eject", "-t", drive_name], check=True)
        log_message(f"Drive {drive_name} closed successfully.")
    except subprocess.CalledProcessError:
        log_message(f"Failed to close drive {drive_name}.")

# Main Test Script
def test_autoloader_in_out_4():
    """Test autoloader functionality by loading and then unloading discs."""
    with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as serial_conn:
        # log_message("Starting setup process...")
        # setup_bays(serial_conn)

        log_message("Loading discs into all drives from top to bottom...")
        # Load discs sequentially from top to bottom
        load_disc_to_drive(serial_conn, drive_number=4)  # Top tray
        load_disc_to_drive(serial_conn, drive_number=3)  # Second from top
        load_disc_to_drive(serial_conn, drive_number=2)  # Third from top
        load_disc_to_drive(serial_conn, drive_number=1)  # Bottom tray

        log_message("All drives loaded successfully.")

        log_message("Unloading discs from drives in reverse order...")
        # Unload discs sequentially from bottom to top
        unload_disc_to_bin(serial_conn, drive_number=1)  # Bottom tray
        unload_disc_to_bin(serial_conn, drive_number=2)  # Third from top
        unload_disc_to_bin(serial_conn, drive_number=3)  # Second from top
        unload_disc_to_bin(serial_conn, drive_number=4)  # Top tray

        log_message("All drives unloaded successfully.")

def detect_hard_drive_path():
    """Automatically detect the external hard drive path under /media/lf/."""
    base_path = "/media/lf/"
    if not os.path.exists(base_path):
        raise FileNotFoundError(f"Base path {base_path} does not exist. Ensure the drive is mounted.")

    # Find the first directory under /media/lf/
    for item in os.listdir(base_path):
        full_path = os.path.join(base_path, item)
        if os.path.isdir(full_path):
            log_message(f"Detected external hard drive: {full_path}")
            return full_path

    raise FileNotFoundError("No external hard drives detected under /media/lf/")

def generate_unique_folder_path(base_path, folder_name):
    """Generate a unique folder path in the RIPPING subfolder, appending (2), (3), etc., if necessary."""
    ripping_path = os.path.join(base_path, "RIPPING")
    os.makedirs(ripping_path, exist_ok=True)  # Create the RIPPING directory if it doesn't exist
    os.chmod(ripping_path, 0o777)  # Set universal permissions

    folder_path = os.path.join(ripping_path, folder_name)
    counter = 1
    while os.path.exists(folder_path):
        folder_path = os.path.join(ripping_path, f"{folder_name} ({counter})")
        counter += 1
    return folder_path

def read_dvd(drive_number, destination_path, output_queue):
    """Read data from a DVD using ddrescue."""
    drive_name = DRIVE_NAMES[drive_number - 1]
    dvd_device = f"/dev/{drive_name}"
    ripping_path = os.path.join(destination_path, "RIPPING")
    os.makedirs(ripping_path, exist_ok=True)
    os.chmod(ripping_path, 0o777)

    try:
        log_message(f"Waiting for DVD in Drive {drive_name}...")
        dvd_label = None
        block_size = None

        for attempt in range(10):
            blkid_output = subprocess.run(["blkid", dvd_device], capture_output=True, text=True)
            if blkid_output.returncode == 0:
                dvd_label = subprocess.run(
                    ["blkid", "-o", "value", "-s", "LABEL", dvd_device],
                    capture_output=True, text=True
                ).stdout.strip() or f"DVD_{drive_number}"
                block_size = subprocess.run(
                    ["blockdev", "--getbsz", dvd_device],
                    capture_output=True, text=True
                ).stdout.strip()
                if dvd_label and block_size:
                    log_message(f"DVD label: {dvd_label}, Block size: {block_size}")
                    break
            time.sleep(1)
        else:
            raise TimeoutError(f"Timeout waiting for DVD in Drive {drive_name}.")

        iso_path = os.path.join(ripping_path, f"{dvd_label}.iso")
        log_path = os.path.join(ripping_path, f"{dvd_label}_rescue.log")

        steps = [
            ["ddrescue", "-b", block_size, "-n", "-v", dvd_device, iso_path, log_path],
            ["ddrescue", "-b", block_size, "-d", "-r", "3", "-v", dvd_device, iso_path, log_path],
            ["ddrescue", "-b", block_size, "-d", "-R", "-r", "3", "-v", dvd_device, iso_path, log_path],
        ]
        for i, step in enumerate(steps, 1):
            output_queue.put(f"Step {i}: Running ddrescue...")
            process = subprocess.Popen(step, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            line_count = 0
            for line in iter(process.stdout.readline, ""):
                if line_count >= 10:  # Skip the first 10 lines
                    output_queue.put(line.strip())
                    refresh_terminal()
                line_count += 1
            process.wait()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, step)

        log_message(f"DVD '{dvd_label}' successfully rescued to {iso_path}")

    except Exception as e:
        log_message(f"Error in Drive {drive_name}: {e}")

def process_drive(serial_conn, drive_number, destination_path, lock):
    """Process a single drive: read data and handle autoloader."""
    output_queue = output_queues[drive_number]
    while True:
        try:
            with lock:
                if not load_disc_to_drive(serial_conn, drive_number):
                    log_message(f"Drive {drive_number}: No discs left in input bins.")
                    break

            read_dvd(drive_number, destination_path, output_queue)

            with lock:
                if not unload_disc_to_bin(serial_conn, drive_number):
                    log_message(f"Drive {drive_number}: Output bins are full.")
                    break
        except Exception as e:
            log_message(f"Error in Drive {drive_number}: {e}")
            break


def log_message(message):
    """Log a message to the logfile and update the recent terminal output."""
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    entry = f"{timestamp} {message}"
    with open(LOGFILE, "a") as log_file:
        log_file.write(entry + "\n")
    recent_logs.append(entry)
    refresh_terminal()

def refresh_terminal():
    """Refresh the terminal UI with reserved sections for logs and drive outputs."""
    # Get terminal dimensions
    terminal_size = shutil.get_terminal_size((80, 24))  # Default to 80x24 if size cannot be determined
    terminal_width = terminal_size.columns
    terminal_height = terminal_size.lines

    # Define layout heights
    log_section_height = 10  # Number of lines for logs
    drive_section_height = (terminal_height - log_section_height) // 4

    # Clear the entire terminal by printing empty lines
    print("\033[2J", end="")  # Clear screen
    print("\033[H", end="")   # Move cursor to top

    # Render Recent Logs section
    print("Recent Logs:".ljust(terminal_width))
    print("-" * terminal_width)
    for log in recent_logs[-log_section_height:]:
        print(log.ljust(terminal_width))
    for _ in range(log_section_height - min(len(recent_logs), log_section_height) - 2):
        print("".ljust(terminal_width))  # Fill remaining space in the log section

    # Render Drive Outputs section
    for drive_number, queue in output_queues.items():
        print(f"Drive {drive_number} Output:".ljust(terminal_width))
        print("-" * terminal_width)
        output_lines = []
        while not queue.empty():
            output_lines.append(queue.get_nowait())
        output_lines = output_lines[-drive_section_height:]  # Keep only the last few lines
        for line in output_lines:
            print(line.ljust(terminal_width))
        for _ in range(drive_section_height - len(output_lines) - 2):
            print("".ljust(terminal_width))  # Fill remaining space in the drive section

    # Ensure the cursor is reset
    print("\033[H", end="")  # Move cursor back to the top

def handle_interrupt(signal, frame):
    """Handle Ctrl+C gracefully by resetting the terminal."""
    print("\033[2J\033[H", end="")  # Clear the screen and reset cursor
    print("Exiting gracefully...")
    sys.exit(0)

def add_drive_output(drive_number, message):
    """Add a message to a drive's output queue and refresh the terminal."""
    if drive_number in output_queues:
        output_queues[drive_number].put(message)
    refresh_terminal()

# Register the signal handler
signal.signal(signal.SIGINT, handle_interrupt)

def main():
    """Main function to orchestrate the DVD processing."""
    destination_path = detect_hard_drive_path()
    log_message(f"Using {destination_path} as the destination for DVD contents.")

    with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as serial_conn:
        processes = []
        for drive_number in range(1, 5):  # Drives 1 through 4
            process = Process(target=process_drive, args=(serial_conn, drive_number, destination_path, operation_lock))
            processes.append(process)
            process.start()

        for process in processes:
            process.join()

    log_message("All discs processed successfully.")

if __name__ == "__main__":
    main()

