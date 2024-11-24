import serial
import os
import shutil
import subprocess
from multiprocessing import Process
from multiprocessing import Lock
import time

# Global lock to ensure only one load/unload operation runs at a time
operation_lock = Lock()

# Configuration
SERIAL_PORT = "/dev/ttyUSB0"  # Serial port for autoloader communication
BAUD_RATE = 38400
INPUT_BINS = [1, 2]  # Input bins (use bin 1 first, then bin 2)
OUTPUT_BINS = [3, 4]  # Output bins (overflow into next)
BIN_CAPACITY = 108  # Maximum discs a bin can hold
DISC_HEIGHT = 12  # Disc height in offset units
DEFAULT_OFFSET = 2304  # Default offset with 0 discs in the bin
DRIVE_NAMES = ["sr3", "sr2", "sr0", "sr1"]  # Linux device names for drives (top to bottom)

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
                print(f"Response to '{command}': {response}")
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
                    print("Ready state detected. Recalibrating...")
                    # setup_bays(serial_conn)
                    # TODO maybe do something else here, for now skip we only need to calibrate when we call the function
                    recalibration_needed = False
                    break # retry it all now that the error was cleared
                return response  # Return the original command response
            elif status_response == "+!e1005000C":
                # Bay door issue (first occurrence logs an error)
                if recalibration_needed is False:
                    print(f"Error detected: Bay door issue ({status_response}). Retrying...")
                    recalibration_needed = True
                break  # Retry the command
            elif status_response == "+!e1006000C":
                # Door opened (first occurrence logs an error)
                if recalibration_needed is False:
                    print(f"Door opened detected ({status_response}). Waiting for resolution...")
                    recalibration_needed = True
                break  # Retry the command
            else:
                print(f"Unexpected status after '{command}': {status_response}")
                return response

def setup_bays(serial_conn):
    """Set up bays by probing all bins and tracking disc state."""
    print("Performing initial status check...")
    send_command(serial_conn, "!e1C")  # Clear any pending status

    print("Setting up bays...")
    disc_held = False  # Track whether a disc is currently held

    for bin_num in range(1,5):
        recalibrate_bin(bin_num)

    print("Bays setup completed.")

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
        print(f"Error parsing disc count from response: {response}")
        return "unknown"

def recalibrate_bin(serial_conn, bin_num):
    """Recalibrate a specific bin by performing a pick/place operation."""
    print(f"Recalibrating Bin {bin_num}...")
    # Attempt to grab a disc
    grab_command = f"!f120{bin_num-1}2C"
    response = send_command(serial_conn, grab_command)

    if "+!f11C" in response:  # Disc successfully picked up
        print(f"Disc picked up from Bin {bin_num}.")
        # Place the disc back
        place_command = f"!f120{bin_num-1}1C"
        send_command(serial_conn, place_command)
        print(f"Disc placed back into Bin {bin_num}.")
    elif "+!f10C" in response:  # No disc detected
        print(f"Bin {bin_num} is empty.")
    else:
        print(f"Unexpected response during recalibration of Bin {bin_num}: {response}")

def query_bin_inventory(serial_conn, bin_num):
    """Query the number of discs in a specific bin and recalibrate if necessary."""
    command = f"!f020{bin_num-1}C"  # Query command for the specific bin
    response = send_command(serial_conn, command)

    if "+!f01365534C" in response:  # Error code for bin count
        print(f"Error detected in Bin {bin_num}, recalibrating...")
        recalibrate_bin(serial_conn, bin_num)
        # Retry querying the bin after recalibration
        response = send_command(serial_conn, command)

    if "+!f01036000C" in response:  # Bin is empty
        return 0

    try:
        # Calculate disc count from the response
        return calculate_disc_count(response)
    except ValueError:
        print(f"Unexpected response format for Bin {bin_num}: {response}")
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
        print("No discs available in input bins.")
        return False  # No disc loaded

    print(f"Picking a disc from Bin {input_bin}...")
    grab_command = f"!f120{input_bin-1}2C"  # Grab disc from the input bin
    response = send_command(serial_conn, grab_command)
    if "+!f10C" in response:
        print(f"No disc available in Bin {input_bin}.")
        return False  # No disc loaded
    elif "+!f11C" in response:
        print(f"Disc picked up from Bin {input_bin}.")

    # Move the autoloader to the specified drive bay
    print(f"Moving to Drive {drive_number}...")
    move_command = f"!f124{drive_number}0C"  # Move to the drive
    send_command(serial_conn, move_command)

    # Get the Linux device name for the drive
    drive_name = DRIVE_NAMES[drive_number - 1]

    # Open the drive
    print(f"Opening Drive {drive_number} ({drive_name})...")
    open_drive(drive_name)

    # Place the disc in the drive
    print(f"Placing disc into Drive {drive_number}...")
    place_command = f"!f124{drive_number}1C"  # Place the disc
    send_command(serial_conn, place_command)

    # Close the drive
    print(f"Closing Drive {drive_number} ({drive_name})...")
    close_drive(drive_name)

    print(f"Disc successfully placed in Drive {drive_number}.")
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
        print("All output bins are full. Cannot unload disc.")
        return False  # No disc unloaded

    print(f"Unloading disc from Drive {drive_number}...")
    # Move autoloader to the drive
    move_to_drive_command = f"!f124{drive_number}0C"
    send_command(serial_conn, move_to_drive_command)

    # Get the Linux device name for the drive
    drive_name = DRIVE_NAMES[drive_number - 1]

    # Open the drive
    print(f"Opening Drive {drive_number} ({drive_name})...")
    open_drive(drive_name)

    # Grab the disc from the drive
    grab_command = f"!f124{drive_number}2C"
    send_command(serial_conn, grab_command)
    print(f"Disc removed from Drive {drive_number}.")

    # Close the drive
    print(f"Closing Drive {drive_number} ({drive_name})...")
    close_drive(drive_name)

    # Move the disc to the target output bin
    print(f"Moving disc to Output Bin {target_bin}...")
    move_to_bin_command = f"!f120{target_bin-1}1C"
    send_command(serial_conn, move_to_bin_command)

    print(f"Disc successfully placed in Output Bin {target_bin}.")
    return True  # Disc unloaded successfully

def open_drive(drive_name):
    """Open the drive tray using the Linux device name."""
    try:
        subprocess.run(["eject", drive_name], check=True)
        print(f"Drive {drive_name} opened successfully.")
    except subprocess.CalledProcessError:
        print(f"Failed to open drive {drive_name}.")

def close_drive(drive_name):
    """Close the drive tray using the Linux device name."""
    try:
        subprocess.run(["eject", "-t", drive_name], check=True)
        print(f"Drive {drive_name} closed successfully.")
    except subprocess.CalledProcessError:
        print(f"Failed to close drive {drive_name}.")

# Main Test Script
def test_autoloader_in_out_4():
    """Test autoloader functionality by loading and then unloading discs."""
    with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as serial_conn:
        # print("Starting setup process...")
        # setup_bays(serial_conn)

        print("Loading discs into all drives from top to bottom...")
        # Load discs sequentially from top to bottom
        load_disc_to_drive(serial_conn, drive_number=4)  # Top tray
        load_disc_to_drive(serial_conn, drive_number=3)  # Second from top
        load_disc_to_drive(serial_conn, drive_number=2)  # Third from top
        load_disc_to_drive(serial_conn, drive_number=1)  # Bottom tray

        print("All drives loaded successfully.")

        print("Unloading discs from drives in reverse order...")
        # Unload discs sequentially from bottom to top
        unload_disc_to_bin(serial_conn, drive_number=1)  # Bottom tray
        unload_disc_to_bin(serial_conn, drive_number=2)  # Third from top
        unload_disc_to_bin(serial_conn, drive_number=3)  # Second from top
        unload_disc_to_bin(serial_conn, drive_number=4)  # Top tray

        print("All drives unloaded successfully.")

def detect_hard_drive_path():
    """Automatically detect the external hard drive path under /media/lf/."""
    base_path = "/media/lf/"
    if not os.path.exists(base_path):
        raise FileNotFoundError(f"Base path {base_path} does not exist. Ensure the drive is mounted.")

    # Find the first directory under /media/lf/
    for item in os.listdir(base_path):
        full_path = os.path.join(base_path, item)
        if os.path.isdir(full_path):
            print(f"Detected external hard drive: {full_path}")
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

def read_dvd(drive_number, destination_path):
    """Read data from a DVD in the specified drive and copy it to the destination."""
    drive_name = DRIVE_NAMES[drive_number - 1]
    mount_point = f"/mnt/{drive_name}"
    os.makedirs(mount_point, exist_ok=True)
    os.chmod(mount_point, 0o777)  # Set universal permissions for the mount point

    try:
        # Wait for a DVD to be inserted
        print(f"Waiting for a DVD to be inserted into Drive {drive_name}...")
        for attempt in range(50):  # Retry up to 50 times with 0.5s delay
            result = subprocess.run(["blkid", f"/dev/{drive_name}"], capture_output=True, text=True)
            if result.returncode == 0:  # blkid returns 0 if the drive has media
                print(f"DVD detected in Drive {drive_name}. Proceeding with mount.")
                break
            time.sleep(0.5)
        else:
            raise TimeoutError(f"No DVD detected in Drive {drive_name} after multiple attempts.")

        # Mount the DVD
        subprocess.run(["mount", f"/dev/{drive_name}", mount_point], check=True)
        print(f"Mounted {drive_name} at {mount_point}")

        # Get the disc name
        disc_name = subprocess.run(["blkid", "-o", "value", "-s", "LABEL", f"/dev/{drive_name}"],
                                   capture_output=True, text=True).stdout.strip() or f"DVD_{drive_number}"

        # Create a unique folder for the DVD in the RIPPING directory
        folder_path = generate_unique_folder_path(destination_path, disc_name)
        os.makedirs(folder_path)
        os.chmod(folder_path, 0o777)  # Set universal permissions

        # Copy data from DVD to the folder
        errors = []
        for root, _, files in os.walk(mount_point):
            for file in files:
                src = os.path.join(root, file)
                dest = os.path.join(folder_path, os.path.relpath(src, mount_point))
                try:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    os.chmod(os.path.dirname(dest), 0o777)  # Set permissions for intermediate directories
                    shutil.copy2(src, dest)
                    os.chmod(dest, 0o777)  # Set permissions for copied files
                except Exception as e:
                    errors.append(f"Failed to copy {src}: {e}")

        # Write errors to a log file
        if errors:
            log_path = os.path.join(folder_path, "errors.log")
            with open(log_path, "w") as log_file:
                log_file.write("\n".join(errors))
            os.chmod(log_path, 0o777)  # Set permissions for the log file
            print(f"Errors logged to {log_path}")

        print(f"DVD {disc_name} successfully read to {folder_path}")

    except Exception as e:
        print(f"Error processing DVD in Drive {drive_number}: {e}")
    finally:
        # Unmount the drive
        subprocess.run(["umount", mount_point], check=True)
        os.rmdir(mount_point)
        print(f"Unmounted {drive_name} and removed {mount_point}")

def process_drive(serial_conn, drive_number, destination_path, lock):
    """Process a single drive: read data and handle autoloader."""
    while True:
        try:
            # Acquire lock before interacting with the autoloader
            with lock:
                # Load a disc into the drive
                if not load_disc_to_drive(serial_conn, drive_number):
                    print(f"Stopping processing for Drive {drive_number}: No discs left in input bins.")
                    break

            # Read data from the drive
            read_dvd(drive_number, destination_path)

            # Acquire lock before interacting with the autoloader
            with lock:
                # Unload the disc and move it to an output bin
                if not unload_disc_to_bin(serial_conn, drive_number):
                    print(f"Stopping processing for Drive {drive_number}: Output bins are full.")
                    break
        except Exception as e:
            print(f"Error in drive {drive_number} processing: {e}")
            break



def main():
    """Main function to orchestrate the DVD processing."""
    destination_path = detect_hard_drive_path()
    print(f"Using {destination_path} as the destination for DVD contents.")

    with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as serial_conn:
        processes = []
        for drive_number in range(1, 5):  # Drives 1 through 4
            process = Process(target=process_drive, args=(serial_conn, drive_number, destination_path, operation_lock))
            processes.append(process)
            process.start()

        for process in processes:
            process.join()

    print("All discs processed successfully.")

if __name__ == "__main__":
    main()

