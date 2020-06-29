#!/usr/bin/env python3.7
#
# pylint: disable=missing-docstring

import argparse
import logging
import os
import random
import signal
import sys
import time

from datetime import datetime
from datetime import timedelta

import RPi.GPIO as gpio
import gevent
import json
import pytz
import requests

logging.basicConfig(format='%(asctime)s %(levelname)s[%(process)d]: %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.INFO)

SLEEP_TIME = 60
CONFIG_FILE = '/etc/lights.json'
MANDATORY_FIELDS = {'ports', 'local_tz', 'latitude', 'longitude'}

def to_set(obj):
  if isinstance(obj, int):
    return set([obj])  # Single item
  if not isinstance(obj, set):
    obj = set(obj)
  return obj


class Config:
  _instance = None
  config_data = None
  def __new__(cls, *args, **kwargs):
    if cls._instance is None:
      cls._instance = super(Config, cls).__new__(cls)
      cls._instance.config_data = {}
    return cls._instance

  def __init__(self, config_file=CONFIG_FILE):
    if self.config_data:
      return
    logging.debug('Reading config file')
    if not os.path.exists(config_file):
      logging.error('Configuration file "%s" not found', config_file)
      sys.exit(os.EX_CONFIG)

    try:
      with open(CONFIG_FILE, 'r') as confd:
        lines = []
        for line in confd:
          line = line.strip()
          if not line or line.startswith('#'):
            continue
          lines.append(line)
        self.config_data = json.loads('\n'.join(lines))
    except ValueError as err:
      logging.error('Configuration error: "%s"', err)
      sys.exit(os.EX_CONFIG)

    missing_fields = self.config_data.keys() ^ MANDATORY_FIELDS
    if missing_fields != set():
      logging.error('Configuration keys "%s" are missing', missing_fields)
      sys.exit(os.EX_CONFIG)

  def __getattr__(self, attr):
    if attr not in self.config_data:
      raise AttributeError("'{}' object has no attribute '{}'".format(self.__class__, attr))
    return self.config_data[attr]


class Sunset:
  __cache = {}

  def __init__(self, timez, lat, lon):
    now = datetime.now()

    if now.date() in Sunset.__cache:
      self._sun = self.__cache[now.date()]
      return

    params = dict(lat=lat, lng=lon, formatted=0,
                  date=now.strftime('%Y-%m-%d'))
    url = 'https://api.sunrise-sunset.org/json'
    try:
      resp = requests.get(url=url, params=params, timeout=(3, 10))
      data = resp.json()
    except Exception as err:
      logging.error(err)
      raise

    tzone = pytz.timezone(timez)
    self._sun = {}
    for key, val in data['results'].items():
      if key == 'day_length':
        self._sun[key] = val
      else:
        self._sun[key] = datetime.fromisoformat(val).astimezone(tzone)

    Sunset.__cache[now.date()] = self._sun
    return

  @property
  def sunset(self):
    return self._sun['sunset']


class AllMatch(set):
  """Universal set - match everything"""
  def __contains__(self, item):
    return True

  def __repr__(self):
    return '{*}'

ALLMATCH = AllMatch()


class Event:
  """The Actual Event Class"""
  def __init__(self, action, minute=ALLMATCH, hour=ALLMATCH,
               day=ALLMATCH, month=ALLMATCH, daysofweek=ALLMATCH,
               **kwargs):
    self.mins = to_set(minute)
    self.hours = to_set(hour)
    self.days = to_set(day)
    self.months = to_set(month)
    self.daysofweek = to_set(daysofweek)
    self.action = action
    self.kwargs = kwargs

  def matchtime(self, tm1):
    """Return True if this event should trigger at the specified datetime"""

    logging.debug("%d:%r - %d:%r - %d:%r - %d:%r - %d:%r",
                  tm1.minute, self.mins,
                  tm1.hour, self.hours,
                  tm1.day, self.days,
                  tm1.month, self.months,
                  tm1.weekday(), self.daysofweek)

    return (tm1.minute in self.mins and
            tm1.hour in self.hours and
            tm1.day in self.days and
            tm1.month in self.months and
            tm1.weekday() in self.daysofweek)

  def check(self, tm1):
    """Check and run action if needed"""
    logging.debug('Event check %r', self)
    if self.matchtime(tm1):
      logging.debug('Match %r', tm1)
      self.action(**self.kwargs)

  def __eq__(self, other):
    return (self.action == other.action and
            self.mins == other.mins and
            self.hours == other.hours and
            self.days == other.days and
            self.months == other.months and
            self.daysofweek == other.daysofweek)

  def __repr__(self):
    _repr = "<{}> [{}] - mins:{!r} - hours:{!r} - days:{!r} - month:{!r} - weekdays:{!r}"
    return _repr.format(self.__class__.__name__, self.action.__name__, self.mins,
                        self.hours, self.days, self.months, self.daysofweek)

class Task(Event):
  """Like an Event but only run once"""
  def __init__(self, *args, **kwargs):
    super(Task, self).__init__(*args, **kwargs)
    self.has_run = False

  def check(self, tm1):
    logging.debug('Task check %r', self)
    if self.has_run:
      logging.debug('%r has already run', self)
      return
    if self.matchtime(tm1):
      logging.debug('Match %r', tm1)
      self.has_run = True
      self.action(**self.kwargs)


class CronTab:
  """The crontab implementation"""
  def __init__(self, *events):
    self.events = list()
    for event in events:
      self.append(event)

  def _check(self):
    """Check all events in separate greenlets"""
    tm1 = datetime(*datetime.now().timetuple()[:5])
    logging.debug('Time %r', tm1)
    for event in self.events:
      gevent.spawn(event.check, tm1)

    tm1 += timedelta(minutes=1)
    sec = (tm1 - datetime.now()).seconds + 1
    logging.debug('Next check in %d', sec)
    gevent.spawn_later(sec, self._check)

  def run(self):
    """Run the cron forever"""
    self._check()
    while True:
      gevent.sleep(SLEEP_TIME)
      garbage = [t for t in self.events if isinstance(t, Task) and t.has_run]
      for tsk in garbage:
        self.remove(tsk)

  def append(self, event):
    logging.info('CronTab add: %r', event)
    if event not in self.events:
      self.events.append(event)
    else:
      logging.warning('CronTab duplicate %r', event)

  def remove(self, event):
    try:
      pos = self.events.index(event)
      del self.events[pos]
      logging.info('CronTab remove: %r', event)
    except ValueError:
      logging.warning('CronTab not found %r', event)


class Lights:

  def __init__(self, ports):
    self._ports = ports
    gpio.setwarnings(False)
    gpio.setmode(gpio.BCM)
    for port in self._ports:
      gpio.setup(port, gpio.OUT)

  def off(self, ports=None, sleep=0.01):
    if not ports:
      ports = self._ports
    for port in ports:
      if port in self._ports:
        gpio.output(port, gpio.HIGH)
        gevent.sleep(sleep)
    logging.info("%s", self)

  def on(self, ports=None, sleep=0.01):
    if not ports:
      ports = self._ports
    for port in ports:
      if port in self._ports:
        gpio.output(port, gpio.LOW)
        gevent.sleep(sleep)
    logging.info("%s", self)

  def random(self, ports=None, count=25, delay=0.15):
    logging.info('Random - count:%d', count)
    if not ports:
      ports = self._ports[:]
    for _ in range(count):
      port = random.choice(ports)
      gpio.output(port, gpio.LOW)
      gevent.sleep(delay)
      gpio.output(port, gpio.HIGH)
      gevent.sleep(delay)

  def __str__(self):
    status = self.status().items()
    return ', '.join([f"{k:02d}:{v}" for k, v in status])

  def status(self, ports=None):
    status = {}
    st_msg = {0: 'ON', 1: 'Off'}
    if not ports:
      ports = self._ports
    for port in ports:
      status[port] = st_msg[gpio.input(port)]
    return status


def light_show(lights):
  lights.off()

  for _ in range(5):
    lights.on()
    gevent.sleep(.2)
    lights.off()
    gevent.sleep(.4)

  gevent.sleep(0.5)
  lights.random(count=64)

  for _ in range(5):
    lights.on()
    gevent.sleep(.2)
    lights.off()
    gevent.sleep(.4)

  gevent.sleep(0.5)
  lights.on()


def check_status(lights, ports=None):
  status = lights.status(ports)
  logging.info(', '.join([f"{k:02d}:{v}" for k, v in status.items()]))


def sig_dump():
  global cron
  logging.debug('Caught signal: SIGHUP')
  try:
    for event in cron.events:
      logging.info('%r', event)
  except NameError as err:
    logging.error(err)


def add_sunset_task(cron, lights):
  config = Config()
  sun = Sunset(config.local_tz, config.latitude, config.longitude)
  logging.info('Sunset at: %s', sun.sunset.time())
  task = Task(lights.on, sun.sunset.minute, sun.sunset.hour)
  cron.append(task)


def automation(lights):
  global cron

  cron = CronTab(
      Event(lights.off, 35, 22), # Turn off the lights at 10:10pm
      Event(lights.off, 0, 0), # Turn off the lights at midnight no matter what
  )
  cron.append(Event(add_sunset_task, 0, (2, 8, 14, 20), cron=cron, lights=lights))
  add_sunset_task(cron, lights)
  cron.run()


def main():
  config = Config()
  parser = argparse.ArgumentParser(description='Garden lights')
  on_off = parser.add_mutually_exclusive_group(required=True)
  on_off.add_argument('--off', nargs='*', type=int, help='Turn off all the lights')
  on_off.add_argument('--on', nargs='*', type=int, help='Turn on all the lights')
  on_off.add_argument('--status', nargs='*', type=int, help='Checkt the status of each port')
  on_off.add_argument('--random', type=int, help='Random sequence')
  on_off.add_argument('--light-show', action="store_true", help='Light show')
  on_off.add_argument('--cron', action="store_true", help='Automatic mode')
  pargs = parser.parse_args()
  gevent.signal_handler(signal.SIGHUP, sig_dump)

  lights = Lights(config.ports)

  if pargs.on is not None:
    lights.on(pargs.on)
  elif pargs.off is not None:
    lights.off(pargs.off)
  elif pargs.status is not None:
    check_status(lights, pargs.status)
  elif pargs.light_show:
    light_show(lights)
  elif pargs.cron:
    automation(lights)
  elif pargs.random:
    lights.random(count=pargs.random)

if __name__ == "__main__":
  main()
