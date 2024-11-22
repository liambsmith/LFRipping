use Device::SerialPort;

# Open the serial port
my $ob = new Device::SerialPort("/dev/ttyUSB0") || die "Failed to open port: $!\n";

# Set serial port parameters
$ob->baudrate(38400);
$ob->parity("none");
$ob->databits(8);
$ob->stopbits(1);
$ob->handshake('none');

# Apply settings
$ob->write_settings || undef $ob;

# Send the string 1b2166403143 (hex values)
$ob->write("\x1B\x21\x66\x40\x31\x43");

# Timeout settings (in seconds)
my $timeout = 5;  # 5-second timeout
my $start_time = time();

# Loop to read response with timeout
while (1) {
    if (my $result = $ob->input) {
        $result =~ s/\x1B/\+/g;  # Replace ESC with '+'
        $result =~ s/\x04/\=/g;  # Replace EOT with '='
        print "Received: $result\n";
        last;  # Exit loop when response is received
    }

    # Check if timeout has occurred
    if (time() - $start_time > $timeout) {
        print "Timeout reached. No response received.\n";
        last;  # Exit loop after timeout
    }

    # Sleep for a short period before checking again
    select undef, undef, undef, 0.25;
}

# Clean up and close the serial port
undef $ob;
