use Device::SerialPort;

my $DONE = 0;

my $ob = new Device::SerialPort("/dev/ttyUSB0") || die;
$ob->user_msg(1);
$ob->error_msg(1);

$ob->baudrate(38400);
$ob->parity("none");
$ob->parity_enable(0);
$ob->databits(8);
$ob->stopbits(1);
$ob->handshake('rts');

$ob->write_settings || undef $ob;

print $ARGV[0] . "\n";

$ob->write("\x1B" . $ARGV[0]);

while(!$DONE) {
if(my $result = $ob->input) {
$result =~ s/\x1B/+/g;
$result =~ s/\x04/=/g;
print $result . "\n";
$DONE++;
}
select undef, undef, undef, 0.25; # short sleep
}
undef $ob;
