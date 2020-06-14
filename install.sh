#!/bin/bash
#
# (c) W6BSD Fred Cirera.
# https://github.com/0x9900/lights.git
#

if [[ $(id -u) != 0 ]]; then
    echo "Use sudo to run this command"
    exit 1
fi
echo 'Installing lights.py'
cp lights.py /usr/local/bin/lights
chmod a+x /usr/local/bin/lights

if [[ ! -f /etc/lights.json ]]; then
    cp lights-example.json /etc/lights.json
    echo "**********************************************************************"
    echo "*  Installing a new configuration file into /etc/lights.json"
    echo "*  Don't forget to edit that file"
    echo "**********************************************************************"
fi

echo 'Installing the lights service'
cp lights.service /lib/systemd/system/lights.service

echo 'Starting the service'
systemctl stop lights.service
sleep 1
systemctl enable lights.service
systemctl start lights.service
sleep 2
systemctl status lights.service
