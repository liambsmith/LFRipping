import serial
import time

# Configuration
SERIAL_PORT = "/dev/ttyUSB0"  # Serial port for autoloader communication
BAUD_RATE = 38400
BIN_CAPACITY = 108  # Maximum number of discs per bin
LOG_FILE = "offset.txt"  # File to log offset data

# Helper Functions
def send_command(serial_conn, command):
    """Send a command to the autoloader and read the response."""
    command_bytes = b"\x1B" + command.encode("ascii")
    serial_conn.write(command_bytes)
    while True:
        response = serial_conn.read_until(expected=b"\x04").decode("ascii")
        response = response.replace("\x1B", "+").replace("\x04", "=").strip()
        if response:
            return response

def get_bin_offset(serial_conn, bin_num):
    """Query the offset value for a specific bin."""
    command = f"!f020{bin_num}C"
    response = send_command(serial_conn, command)
    try:
        offset = int(response[5:10], 16)  # Extract and convert the offset to decimal
        return offset
    except ValueError:
        print(f"Error parsing offset for Bin {bin_num + 1}: {response}")
        return None

def transfer_disc(serial_conn, from_bin, to_bin):
    """Transfer a single disc from one bin to another."""
    print(f"Transferring disc from Bin {from_bin} to Bin {to_bin}...")

    # Pick a disc from the source bin
    grab_command = f"!f120{from_bin - 1}2C"
    response = send_command(serial_conn, grab_command)
    if "+!f10C" in response:
        print(f"No disc available in Bin {from_bin}.")
        return False
    elif "+!f11C" in response:
        print(f"Disc picked up from Bin {from_bin}.")

    # Place the disc into the destination bin
    place_command = f"!f120{to_bin - 1}1C"
    send_command(serial_conn, place_command)
    print(f"Disc placed into Bin {to_bin}.")
    return True

def log_offsets(serial_conn, count_bin1, count_bin2, log_file):
    """Log offset values for both bins."""
    with open(log_file, "a") as f:
        for bin_num, count in [(1, count_bin1), (2, count_bin2)]:
            offset = get_bin_offset(serial_conn, bin_num - 1)
            if offset is not None:
                f.write(f"{bin_num},{count},{offset}\n")
                print(f"Logged: Bin {bin_num}, Count {count}, Offset {offset}")

# Main Process
def measure_offsets():
    """Automate the offset measurement process."""
    with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as serial_conn:
        print("Starting offset measurement...")
        with open(LOG_FILE, "w") as f:
            f.write("Bin,Count,Offset\n")  # Write CSV header

        # Initial measurement: Pick and place back on Bin 1
        print("Performing initial measurement...")
        if transfer_disc(serial_conn, from_bin=1, to_bin=1):
            log_offsets(serial_conn, count_bin1=BIN_CAPACITY, count_bin2=0, log_file=LOG_FILE)
        else:
            print("Initial measurement failed. Exiting.")
            return

        # Begin with 108 discs in Bin 1 and 0 in Bin 2
        count_bin1 = BIN_CAPACITY
        count_bin2 = 0

        for _ in range(BIN_CAPACITY):
            # Log offsets before the transfer
            log_offsets(serial_conn, count_bin1, count_bin2, LOG_FILE)

            # Transfer a disc from Bin 1 to Bin 2
            if not transfer_disc(serial_conn, from_bin=1, to_bin=2):
                print("No more discs to transfer. Exiting.")
                break

            # Update disc counts
            count_bin1 -= 1
            count_bin2 += 1

        # Log final offsets after all transfers
        log_offsets(serial_conn, count_bin1, count_bin2, LOG_FILE)

    print("Offset measurement complete. Data saved to offset.txt.")

if __name__ == "__main__":
    measure_offsets()

