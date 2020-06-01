# lights
Scheduler for garden lights.

## Python packages requirements

This program uses several python modules. On a Raspberry-Pi running
Raspbian can be installed using the `apt` tool.

Install the modules using the following commands.
```
$ sudo apt update
$ sudo apt install git
$ sudo apt install python3-dev
$ sudo apt install python3-rpi.gpio
$ sudo apt install python3-requests
$ sudo apt install python3-tz
$ sudo apt install python3-gevent
```

## Installation

Download `lights` from github. The simplest way to do it is to use the `git clone` command.

```
$ git clone https://github.com/0x9900/lights.git
```

Go to the newly created directory and use the `install.sh` script to install lights.

```
$ sudo ./install.sh
```

Don't forget to edit the configuration file `/etc/lights.json` and
specify the gpio ports you are using as well as the time zone, and
your GPS coordinates.

## Hardware

I use a simple 8 relay board managed by a Raspberry-pi Zero W and a
buck converter to lower the power from 24 Volts to the 5 volts required
by the Raspberry Pi.

The Pi-Zero has more that enough power for that task.


![Distances](misc/IMG_0624.JPG)
