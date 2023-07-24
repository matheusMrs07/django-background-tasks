# -*- coding: utf-8 -*-
import logging
import random
import sys
import time

from django import VERSION
from django.core.management.base import BaseCommand

from background_task.tasks import tasks, autodiscover
from background_task.utils import SignalManager
from django.db import close_old_connections as close_connection

logger = logging.getLogger(__name__)


def _configure_log_std():
    class StdOutWrapper(object):
        def write(self, s):
            logger.info(s)

    class StdErrWrapper(object):
        def write(self, s):
            logger.error(s)
    sys.stdout = StdOutWrapper()
    sys.stderr = StdErrWrapper()


class Command(BaseCommand):
    help = 'Run tasks that are scheduled to run on the queue'

    # Command options are specified in an abstract way to enable Django < 1.8 compatibility
    OPTIONS = (
        (('--duration', ), {
            'action': 'store',
            'dest': 'duration',
            'type': int,
            'default': 0,
            'help': 'Run task for this many seconds (0 or less to run forever) - default is 0',
        }),
        (('--sleep', ), {
            'action': 'store',
            'dest': 'sleep',
            'type': float,
            'default': 5.0,
            'help': 'Sleep for this many seconds before checking for new tasks (if none were found) - default is 5',
        }),
        (('--max_sleep',), {
            'action': 'store',
            'dest': 'max_sleep',
            'type': float,
            'default': 120.0,
            'help': 'Max duration of sleep - default is 120',
        }),
        (('--queue', ), {
            'action': 'store',
            'dest': 'queue',
            'help': 'Only process tasks on this named queue',
        }),
        (('--log-std', ), {
            'action': 'store_true',
            'dest': 'log_std',
            'help': 'Redirect stdout and stderr to the logging system',
        }),

    )

    if VERSION < (1, 8):
        from optparse import make_option
        option_list = BaseCommand.option_list + tuple([make_option(*args, **kwargs) for args, kwargs in OPTIONS])

    # Used in Django >= 1.8
    def add_arguments(self, parser):
        for (args, kwargs) in self.OPTIONS:
            parser.add_argument(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super(Command, self).__init__(*args, **kwargs)
        self._tasks = tasks
        self.sleep = 5
        self.default_sleep = 5
        self.max_sleep = 120

    def raise_sleep_value(self):
        new_value = self.sleep * 2
        if new_value > self.max_sleep:
            self.sleep = self.max_sleep
        else:
            self.sleep = new_value

    def set_sleep_default(self):
        self.sleep = self.default_sleep

    def handle(self, *args, **options):
        duration = options.pop('duration', 0)
        default_sleep = options.pop('sleep', 5.0)
        max_sleep = options.pop('max_sleep', 120.0)
        queue = options.pop('queue', None)
        log_std = options.pop('log_std', False)
        sig_manager = SignalManager()

        if log_std:
            _configure_log_std()

        autodiscover()

        start_time = time.time()

        if queue:
            queue = queue.split(',')

        self.sleep = default_sleep
        self.default_sleep = default_sleep
        self.max_sleep = max_sleep

        while (duration <= 0) or (time.time() - start_time) <= duration:
            if sig_manager.kill_now:
                # shutting down gracefully
                break

            if not self._tasks.run_next_task(queue):
                # there were no tasks in the queue, let's recover.
                close_connection()
                logger.debug('waiting for tasks')
                time.sleep(self.sleep)
                self.raise_sleep_value()
            else:
                self.set_sleep_default()
                # there were some tasks to process, let's check if there is more work to do after a little break.
                time.sleep(random.uniform(sig_manager.time_to_wait[0], sig_manager.time_to_wait[1]))
