#!/usr/bin/env python3.7
#
import RPi.GPIO as gpio
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

SLEEP_TIME = 60
LOCAL_TZ = 'America/Los_Angeles'
PORTS = [9, 11, 0, 5, 6, 13, 19, 26]

def conv_to_set(obj):
  """Converts to set allowing single integer to be provided"""
  if isinstance(obj, int):
    return set([obj])  # Single item
  if not isinstance(obj, set):
    obj = set(obj)
  return obj


class Sunset(object):
  def __init__(self):
    self._sun = {}
    lat, lng = (37.4591, -122.2474)
    now = datetime.now()

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
    for key, val in data['results'].items():
      if key == 'day_length':
        self._sun[key] = val
      else:
        self._sun[key] = datetime.fromisoformat(val).astimezone(tzone)

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
    self.mins = conv_to_set(minute)
    self.hours = conv_to_set(hour)
    self.days = conv_to_set(day)
    self.months = conv_to_set(month)
    self.daysofweek = conv_to_set(daysofweek)
    self.action = action
    self.args = args
    self.kwargs = kwargs

  def matchtime(self, t1):
    """Return True if this event should trigger at the specified datetime"""
    return ((t1.minute     in self.mins) and
            (t1.hour       in self.hours) and
            (t1.day        in self.days) and
            (t1.month      in self.months) and
            (t1.weekday()  in self.daysofweek))

  def check(self, t):
    """Check and run action if needed"""
    if self.matchtime(t):
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

  def __hash__(self):
    return id(self)

class Task(Event):
  """Like an Event but only run once"""
  def __init__(self, *args, **kwargs):
    super(Task, self).__init__(*args, **kwargs)
    self.has_run = False

  def check(self, t):
    if self.has_run:
      logging.debug('Task: %r has already run', self)
      return
    if self.matchtime(t):
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
    t1 = datetime(*datetime.now().timetuple()[:5])
    for event in self.events:
      gevent.spawn(event.check, t1)

    t1 += timedelta(minutes=1)
    s1 = (t1 - datetime.now()).seconds + 1
    job = gevent.spawn_later(s1, self._check)

  def run(self):
    """Run the cron forever"""
    self._check()
    while True:
      gevent.sleep(60)
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

  def __init__(self, start_time=None, stop_time=None, ports=PORTS):
    self._ports = ports
    self._start_time = start_time
    self._stop_time = stop_time

    gpio.setmode(gpio.BCM)
    for port in self._ports:
      gpio.setup(port, gpio.OUT)
    self.off(self._ports)

  def off(self, ports=PORTS):
    logging.info('all off')
    for port in ports:
      if port in self._ports:
        gpio.output(port, gpio.HIGH)

  def on(self, ports=PORTS):
    now = datetime.now()
    if self._start_time is None or self._start_time < now < self._stop_time:
      logging.info('all on')
      for port in ports:
        if port in self._ports:
          gpio.output(port , gpio.LOW)
    else:
      logging.warning('all on outside time bounderies')

  def random(self, count=25):
    if self._stop_time is None or self._stop_time < now < self._stop_time:
      logging.info('random - count:%d', count)
      self.off()
      for _ in range(count):
        port = random.choice(PORTS)
        gpio.output(port, gpio.LOW)
        time.sleep(.05)
        gpio.output(port, gpio.HIGH)
        time.sleep(.05)
      self.on()
    else:
      logging.warning('random outside time bounderies')

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
  logging.debug('Sunset at: %s', sun.sunset.isoformat())
  cron.append(Task(lights.on, sun.sunset.minute, sun.sunset.hour))

def main():
  lights = Lights()
  cron = CronTab()

  cron.append(Task(add_sunset_task, cron=cron, lights=lights))
  cron.append(Event(lights.off, 59, 23))
  cron.append(Event(add_sunset_task, 0, [2, 14], cron=cron, lights=lights))
  cron.run()


if __name__ == "__main__":
  main()
