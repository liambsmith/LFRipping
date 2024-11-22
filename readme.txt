How to copy disks:

1. Terminal: dmesg | grep tty
 Find what cp201x is attached to (probably ttyUSB0)
 Make sure cmdsend.pl uses ttyUSB0 or what it is if it's something else

2. Run startup # TODO automatic


To send specific commands with perl:
sudo perl cmdsend.pl '<COMMAND>'

Startup stuff:
sudo perl cmdsend.pl '!e1C'

To set up bays/find how many are in, need to grab then put for each one.
!f12002
!f12001
!f12012
!f12011
!f12022
!f12021
!f12032
!f12031



DVD Drives (top to bottom), linux drive name:
[DRIVE4]sr3
[DRIVE3]sr2
[DRIVE2]sr0
[DRIVE1]sr1

Important commands:
!f124XYC
 - X = drive number
 - Y = 0/move, 1/put, 2/grab

!f120XY
 - X = bin number - 1
 - Y = 1/put, 2/grab

Known Command List (edited from https://ragingcomputer.com/2013/03/03/rimage-dtp-4500-ras-13-serial-control-commands/):
!f:C Query Serial Number

!e0C Get Version

!e1C Get Status
!e1000000C – Ready
!e1002000C – Wait?
!e1003000C – No Disc
!e1007000C – No Drive Tray Detected

## Setup / Initialization
!f12402C Probe to Disc Drive Tray
!f10C – No Disc
!f11C – Disc Was In Drive

!f0240C Get Result of Probe to Disc Drive Tray
!f01300241C – Bottom Drive
!f01300242C – Third Drive From Top
!f01300243C – Second Drive From Top
!f01300244C – Top Drive
!f01365534C – Error

## Grabber Arm Movement
!f12600C Move To – Home Grabber Arm – Stop Above Printer
!f11C

!f12400C Move To – Above Top Drive

## Load / Unload Drives
!f12440C Move To – Drive 4 (bottom)
!f12441C Put Disc – Drive 4 (bottom)
!f12442C Grab Disc – Drive 4 (bottom)

!f12430C Move To – Drive 3
!f12431C Put Disc – Drive 3
!f12432C Grab Disc – Drive 3

!f12420C Move To – Drive 2
!f12421C Put Disc – Drive 2
!f12422C Grab Disc – Drive 2

!f12410C Move To – Drive 1 (top)
!f12411C Put Disc – Drive 1 (top)
!f12412C Grab Disc – Drive 1 (top)

## Get Disc From Bin
!f12002C Grab Disc – Bin 1
!f12012C Grab Disc – Bin 2
!f12022C Grab Disc – Bin 3

## Put Disc In Bin
!f12001C Put Disc – Bin 1
!f12011C Put Disc – Bin 2
!f12021C Put Disc – Bin 3

## Inventory Bins
!f0200C – Query Discs in Bin 1
!f01365534C – Error

!f0201C – Query Discs in Bin 2
!f01365534C – Error

!f0202C – Query Discs in Bin 3
!f01365534C – Error

## Get Grabber Arm Location
!f0220C – Query Current Location
!f01000500C – Top
!f01002585C –

## Useless Since The Printer is Crippled
!f12602C – Grab Disc – Printer Tray
!f10C –
[/text]
