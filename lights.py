#!/usr/bin/env python3.7
#
import RPi.GPIO as gpio
import argparse
import gevent
import itertools
import logging
import pytz
import random
import requests
import time

from datetime import datetime
from datetime import timedelta

logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)

SLEEP_TIME = 53
LOCAL_TZ = 'America/Los_Angeles'
PORTS = [9, 11, 0, 5, 6, 13, 19, 26]

LATITUDE = 37.4591
LONGITUDE = -122.2474

def to_set(obj):
  if isinstance(obj, int):
    return set([obj])  # Single item
  if not isinstance(obj, set):
    obj = set(obj)
  return obj


class Sunset(object):
  __cache = {}

  def __init__(self):
    lat, lng = (LATITUDE, LONGITUDE)
    now = datetime.now()

    if now.date() in Sunset.__cache:
      self._sun = self.__cache[now.date()]
      return

    params = dict(lat=lat, lng=lng, formatted=0,
                  date=now.strftime('%Y-%m-%d'))
    url = 'https://api.sunrise-sunset.org/json'
    try:
      resp = requests.get(url=url, params=params)
      data = resp.json()
    except Exception as err:
      logging.error(err)
      raise

    tzone = pytz.timezone(LOCAL_TZ)
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

  def __hash__(self):
    return hash(tuple(sorted(self.__dict__.items())))

allMatch = AllMatch()

class Event(object):
  """The Actual Event Class"""
  def __init__(self, action, minute=allMatch, hour=allMatch,
               day=allMatch, month=allMatch, daysofweek=allMatch,
               *args, **kwargs):
    self.mins = to_set(minute)
    self.hours = to_set(hour)
    self.days = to_set(day)
    self.months = to_set(month)
    self.daysofweek = to_set(daysofweek)
    self.action = action
    self.args = args
    self.kwargs = kwargs

  def matchtime(self, tm1):
    """Return True if this event should trigger at the specified datetime"""
    return (
      tm1.minute in self.mins and
      tm1.hour in self.hours and
      tm1.day in self.days and
      tm1.month in self.months and
      tm1.weekday() in self.daysofweek
    )

  def check(self, tm1):
    """Check and run action if needed"""
    if self.matchtime(tm1):
      self.action(*self.args, **self.kwargs)

  def __eq__(self, other):
    return (
      self.action == other.action and
      self.mins == other.mins and
      self.hours == other.hours and
      self.days == other.days and
      self.months == other.months and
      self.daysofweek == other.daysofweek
    )


class Task(Event):
  """Like an Event but only run once"""
  def __init__(self, *args, **kwargs):
    super(Task, self).__init__(*args, **kwargs)
    self.has_run = False

  def check(self, tm1):
    if self.has_run:
      logging.debug('Task: %r has already run', self)
      return
    if self.matchtime(tm1):
      self.has_run = True
      self.action(*self.args, **self.kwargs)


class CronTab(object):
  """The crontab implementation"""
  def __init__(self, *events):
    self.events = list()
    for event in events:
      self.append(event)

  def _check(self):
    """Check all events in separate greenlets"""
    tm1 = datetime(*datetime.now().timetuple()[:5])
    for event in self.events:
      gevent.spawn(event.check, tm1)

    tm1 += timedelta(minutes=1)
    sec = (tm1 - datetime.now()).seconds + 1
    job = gevent.spawn_later(sec, self._check)

  def run(self):
    """Run the cron forever"""
    self._check()
    while True:
      gevent.sleep(SLEEP_TIME)
      garbage = [t for t in self.events if isinstance(t, Task) and t.has_run]
      for task in garbage:
        self.delete(task)

  def append(self, event):
    if event not in self.events:
      self.events.append(event)
    else:
      logging.debug('event already in the list')

  def delete(self, event):
    try:
      pos = self.events.index(event)
      del self.events[pos]
      logging.debug('Deleting: %r', event)
    except ValueError:
      logging.debug('%r not found', event)


class Lights(object):

  def __init__(self, ports=PORTS):
    self._ports = ports
    gpio.setwarnings(False)
    gpio.setmode(gpio.BCM)
    for port in self._ports:
      gpio.setup(port, gpio.OUT)

  def off(self, ports=PORTS, sleep=0):
    for port in ports:
      if port in self._ports:
        logging.info('Port %d OFF', port)
        gpio.output(port, gpio.HIGH)
        time.sleep(sleep)

  def on(self, ports=PORTS, sleep=0):
    now = datetime.now()
    for port in ports:
      if port in self._ports:
        logging.info('Port %d ON', port)
        gpio.output(port , gpio.LOW)
        time.sleep(sleep)

  def random(self, count=25):
    logging.info('random - count:%d', count)
    for _ in range(count):
      port = random.choice(PORTS)
      gpio.output(port, gpio.LOW)
      time.sleep(.05)
      gpio.output(port, gpio.HIGH)
      time.sleep(.05)

def Right():
  logging.info('Right')
  ports = PORTS[::-1]
  lg = len(ports)
  for i in range(3):
    for i in range(lg):
      gpio.output(ports[i], gpio.LOW)
      time.sleep(.5)
    for i in range(lg):
      gpio.output(ports[i], gpio.HIGH)
      time.sleep(.5)
  time.sleep(.5)

def Left():
  logging.info('Left')
  for i in range(3):
    for i in range(len(PORTS)):
      gpio.output(PORTS[i], gpio.LOW)
      time.sleep(.5)
    for i in range(len(PORTS)):
      gpio.output(PORTS[i], gpio.HIGH)
      time.sleep(.5)
  time.sleep(.5)

def task():
  logging.debug('task running')
  time.sleep(4)
  logging.debug('task done')

def add_sunset_task(cron=None, lights=None):
  sun = Sunset()
  logging.info('Sunset at: %s', sun.sunset.isoformat())
  cron.append(Task(lights.on, sun.sunset.minute, sun.sunset.hour))

def main():
  lights = Lights()
  parser = argparse.ArgumentParser(description='Garden lights')
  on_off = parser.add_mutually_exclusive_group()
  on_off.add_argument('--off', action="store_true", help='Turn off all the lights')
  on_off.add_argument('--on', action="store_true", help='Turn on all the lights')
  on_off.add_argument('--random', action="store_true", help='Random sequence')
  pargs = parser.parse_args()

  if pargs.off:
    lights.off()
    return
  if pargs.on:
    lights.on()
    return
  if pargs.random:
    lights.random()
    return

  cron = CronTab()
  cron.append(Task(add_sunset_task, cron=cron, lights=lights))
  cron.append(Event(lights.off, 59, 23))
  cron.append(Event(add_sunset_task, 0, [2, 14], cron=cron, lights=lights))
  cron.append(Event(lights.random))
  cron.run()

if __name__ == "__main__":
  main()
