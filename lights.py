#!/usr/bin/env python3.7
#
# pylint: disable=missing-docstring

import argparse
import logging
import random
import signal
import time

from datetime import datetime
from datetime import timedelta

import RPi.GPIO as gpio
import gevent
import pytz
import requests

logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)

SLEEP_TIME = 7
LOCAL_TZ = 'America/Los_Angeles'
PORTS = (9, 11, 0, 5, 6, 13, 19, 26)

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

  def __repr__(self):
    return '{*}'

ALLMATCH = AllMatch()

class Event(object):
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
    return (tm1.minute in self.mins and
            tm1.hour in self.hours and
            tm1.day in self.days and
            tm1.month in self.months and
            tm1.weekday() in self.daysofweek)

  def check(self, tm1):
    """Check and run action if needed"""
    if self.matchtime(tm1):
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
                        self.hours, self.days, self.months, self.daysofweek )

class Task(Event):
  """Like an Event but only run once"""
  def __init__(self, *args, **kwargs):
    super(Task, self).__init__(*args, **kwargs)
    self.has_run = False

  def check(self, tm1):
    if self.has_run:
      logging.debug('%r has already run', self)
      return
    if self.matchtime(tm1):
      self.has_run = True
      self.action(**self.kwargs)


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
    gevent.spawn_later(sec, self._check)

  def run(self):
    """Run the cron forever"""
    self._check()
    while True:
      gevent.sleep(SLEEP_TIME)
      garbage = [t for t in self.events if isinstance(t, Task) and t.has_run]
      for tsk in garbage:
        self.delete(tsk)

  def append(self, event):
    if event not in self.events:
      self.events.append(event)
    else:
      logging.debug('already in the list: %r', event)

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
    log_msg = []
    for port in ports:
      if port in self._ports:
        log_msg.append("{:d}/{:02d}".format(PORTS.index(port), port))
        gpio.output(port, gpio.HIGH)
        time.sleep(sleep)
    logging.info("Ports OFF [%s]", ','.join(log_msg))

  def on(self, ports=PORTS, sleep=0):
    log_msg = []
    for port in ports:
      if port in self._ports:
        log_msg.append("{:d}/{:02d}".format(PORTS.index(port), port))
        gpio.output(port, gpio.LOW)
        time.sleep(sleep)
    logging.info("Ports ON [%s]", ','.join(log_msg))

  def random(self, count=25, ports=PORTS):
    logging.info('Random - count:%d', count)
    ports = [p for p in ports if p in self._ports]
    if not ports:
      return
    for _ in range(count):
      port = random.choice(ports)
      gpio.output(port, gpio.LOW)
      time.sleep(.05)
      gpio.output(port, gpio.HIGH)
      time.sleep(.05)

def light_show(lights):
  sun = Sunset()
  tzone = pytz.timezone(LOCAL_TZ)
  now = datetime.now(tz=tzone)
  tomorrow = now.date() + timedelta(days=1)
  midnight = tzone.localize(datetime.combine(tomorrow, datetime.min.time()))

  lights.off()
  time.sleep(2)
  lights.random(64)
  if sun.sunset < now < midnight:
    lights.on()

def sig_handler(sig, frame):
  logging.debug('Caught signal: %d', sig)
  try:
    for event in cron.events:
      logging.info('%r', event)
  except NameError as err:
    logging.error(err)

def add_sunset_task(cron, lights):
  sun = Sunset()
  logging.info('Sunset at: %s', sun.sunset.time())
  task = Task(lights.on, sun.sunset.minute, sun.sunset.hour)
  cron.append(task)
  logging.info('Add task %r', task)

def automation(lights):
  global cron
  sun = Sunset()
  now = datetime.now(tz=pytz.timezone(LOCAL_TZ))

  # If the service is started after sunset, turn on the lights.
  if now > sun.sunset:
    lights.on()
  else:
    lights.off()

  cron = CronTab(
      Event(lights.off, 10, 23), # Turn off the lights at 11:10pm
      Event(light_show, 0, [21, 22, 23], lights=lights) # Light show every hour after sunset
  )
  cron.append(Event(add_sunset_task, 0, (2, 8, 14, 20), cron=cron, lights=lights))
  add_sunset_task(cron, lights)
  cron.run()

def main():
  lights = Lights()
  parser = argparse.ArgumentParser(description='Garden lights')
  on_off = parser.add_mutually_exclusive_group(required=True)
  on_off.add_argument('--off', action="store_true", help='Turn off all the lights')
  on_off.add_argument('--on', action="store_true", help='Turn on all the lights')
  on_off.add_argument('--random', type=int, default=25, help='Random sequence')
  on_off.add_argument('--cron', action="store_true", help='Automatic mode')
  pargs = parser.parse_args()
  signal.signal(signal.SIGUSR1, sig_handler)

  if pargs.cron:
    automation(lights)
  elif pargs.off:
    lights.off()
  elif pargs.on:
    lights.on()
  elif pargs.random:
    lights.random(pargs.random)

if __name__ == "__main__":
  main()
