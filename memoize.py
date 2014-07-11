#!/usr/bin/env python
# -*- coding: utf-8 -*-
# ###################################################################################################
#
# The MIT License (MIT)
#
# Copyright (c) 2014 Guy Kisel
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
# ###################################################################################################
#
# This file incorporates work covered by the following copyrights and
# permission notices:
#
# ###################################################################################################
#
# From http://micheles.googlecode.com/hg/decorator/documentation.html
#
# Copyright (c) 2005-2012, Michele Simionato All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted
# provided that the following conditions are met:
#
# Redistributions of source code must retain the above copyright notice, this list of
# conditions and the following disclaimer. Redistributions in bytecode form must reproduce
# the above copyright notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDERS
# OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY
# OF SUCH DAMAGE.
#
# ###################################################################################################
#
# From http://code.activestate.com/recipes/577504/
#
# The MIT License (MIT)
#
# Copyright (c) 2010 Raymond Hettinger
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
####################################################################################################


from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import print_function

import collections
import time
import threading
from threading import RLock
import sys
import functools
import random
from sys import getsizeof, stderr
from itertools import chain
from collections import deque
import gc

try:
    from reprlib import repr
except ImportError:
    pass

from decorator import decorator
import psutil


def memoized(f):
    """
    Memoize the decorated function.

    @memoized
    def foo(bar):
        return bar
    """
    GlobalCache._caches[f] = {}
    GlobalCache._locks[f] = RLock()

    return decorator(GlobalCache.memoize, f)


class GlobalCache(object):
    """
    Global cache. Implemented as a singleton.

    I know, singletons are terrible. However, system RAM is basically a
    singleton, so the cache might as well be one too.
    """
    _cache = deque()
    _lock = RLock()
    target_memory_use_ratio = 1.0
    _monitor_thread = None
    _stop_thread = threading.Event()
    _monitor_lock = RLock()
    _caches = dict()
    _locks = dict()

    @classmethod
    def clear_cache(cls):
        """
        Clear all of the existing cache entries.
        """
        monitor_running = False
        if cls._monitor_thread:
            monitor_running = cls._monitor_thread.is_alive()
            cls.stop_cache_monitor()
        with cls._monitor_lock, cls._lock:
            while cls._cache:
                cls._cache.pop().delete()
        if monitor_running:
            cls.start_cache_monitor()

    @classmethod
    def shrink_cache(cls, target_memory_use_ratio=None):
        """
        Calculate the current size of our global cache, get the current size of free memory,
        and delete cache entries until the ratio of cache size to free memory is under the
        target ratio.
        """
        cleanup = False
        if not target_memory_use_ratio:
            target_memory_use_ratio = cls.target_memory_use_ratio
        with cls._lock:
            if cls.memory_usage_ratio() > target_memory_use_ratio:
                cleanup = True
                cls._cache = deque(
                    sorted(cls._cache, key=lambda i: i.score, reverse=True))
            start = time.time()
            while (cls.memory_usage_ratio() > target_memory_use_ratio
                   and time.time() - start < 1 and cls._cache):
                try:
                    cls._cache.pop().delete()
                except IndexError:
                    break
            if cleanup:
                gc.collect()

    @classmethod
    def memory_usage_ratio(cls):
        """
        Calculate the ratio of used RAM to available RAM.

        The ratio is designed to reserve at least a tenth of available
        system memory no matter what.
        """
        with cls._lock:
            ratio = float(
                1.0 * _total_size(cls._cache) /
                (psutil.virtual_memory().available - (
                    psutil.virtual_memory().total / 10)))
            if ratio < 0:
                return sys.maxint
            return ratio

    @classmethod
    def memoize(cls, func, *args, **kw):
        """
        Cache the results of calling func with args and kw. Return cached
        results if possible. Maintain a dynamically sized cache based on
        function execution time and the available free memory ratio.

        You probably should use the memoized decorator instead of calling this
        directly.
        """
        with cls._locks[func], cls._lock:
            if not isinstance(args, collections.Hashable):
                result = func(*args, **kw)
                return result
            if kw:
                # frozenset is used to ensure hashability
                key = args, frozenset(kw.items())
            else:
                key = args
            # func.cache attribute added by memoize
            cache = cls._caches[func]
            try:
                if key in cache:
                    result = cache[key].result
                    cls.shrink_cache()
                    return result
            except TypeError:
                result = func(*args, **kw)
                return result

            start = time.time()
            result = func(*args, **kw)
            end = time.time()
            duration = end - start

            cache[key] = CacheEntry(func, key, duration, result,
                                    kw.get('expiration'), *args, **kw)
            cls.shrink_cache()
            cls._cache.append(cache[key])
            return result

    @classmethod
    def start_cache_monitor(cls):
        """
        Start a thread that will monitor memory usage and occasionally shrink the cache.

        Useful if you have some very slow blocking functionality in your code
        or if you won't be calling cached functions often. Only one cache
        monitor will ever run at a time.
        """
        with cls._monitor_lock:
            cls._stop_thread.clear()
            if not cls._monitor_thread:
                cls._monitor_thread = threading.Thread(target=cls._monitor)
            if not cls._monitor_thread.is_alive():
                cls._monitor_thread.daemon = True
                cls._monitor_thread.start()

    @classmethod
    def stop_cache_monitor(cls):
        """
        Stop the cache monitor thread. Blocks until the thread stops.
        """
        with cls._monitor_lock:
            cls._stop_thread.set()
            cls._monitor_thread.join()
            cls._monitor_thread = None

    @classmethod
    def _monitor(cls):
        """
        Target method of cache monitor thread.
        """
        while not cls._stop_thread.is_set():
            cls.shrink_cache()
            time.sleep(random.random() * 10)


start_cache_monitor = GlobalCache.start_cache_monitor
stop_cache_monitor = GlobalCache.stop_cache_monitor
shrink_cache = GlobalCache.shrink_cache
clear_cache = GlobalCache.clear_cache


@functools.total_ordering
class CacheEntry(object):
    def __init__(self, func, key, duration, result, expiration=sys.maxint,
                 *args, **kwargs):
        self.func = func
        self.lock = GlobalCache._locks[func]
        with self.lock:
            self.key = key
            self.duration = duration
            self._result = result
            self.last_used = time.time()
            self.expiration = expiration or sys.maxint
            self.time_to_expire = time.time() + self.expiration
            self.args = args
            self.kwargs = kwargs
            self.size = _total_size(self._result)

    def delete(self):
        with self.lock:
            del self.func.cache[self.key]

    def __eq__(self, other):
        with self.lock:
            return self.score == other.score

    def __lt__(self, other):
        with self.lock:
            return self.score < other.score

    def __hash__(self):
        with self.lock:
            return self.key

    def recalculate_size(self):
        with self.lock:
            self.size = _total_size(self._result)
            return self.size

    def __sizeof__(self):
        return self.size

    @property
    def age(self):
        with self.lock:
            return time.time() - self.last_used

    @property
    def score(self):
        with self.lock:
            return (self.size * self.duration) / (self.age ** 2)

    @property
    def result(self):
        with self.lock:
            if time.time() > self.time_to_expire:
                self._result = self.func(*self.args, **self.kwargs)
                self.recalculate_size()
                self.time_to_expire = time.time() + self.expiration
            self.last_used = time.time()
            return self._result

    def __repr__(self):
        with self.func.lock:
            return '{} {} {}'.format(self.func.__name__, self.key, self.score)


def _total_size(o, handlers=None, verbose=False):
    """ Returns the approximate memory footprint an object and all of its contents.

    Automatically finds the contents of the following builtin containers and
    their subclasses:  tuple, list, deque, dict, set and frozenset.
    To search other containers, add handlers to iterate over their contents:

        handlers = {SomeContainerClass: iter,
                    OtherContainerClass: OtherContainerClass.get_elements}

    """
    handlers = handlers or {}
    dict_handler = lambda d: chain.from_iterable(d.items())
    all_handlers = {tuple: iter,
                    list: iter,
                    deque: iter,
                    dict: dict_handler,
                    set: iter,
                    frozenset: iter,
    }
    all_handlers.update(handlers)  # user handlers take precedence
    seen = set()  # track which object id's have already been seen
    default_size = getsizeof(0)  # estimate sizeof object without __sizeof__

    def sizeof(o):
        if id(o) in seen:  # do not double count the same object
            return 0
        seen.add(id(o))
        s = getsizeof(o, default_size)

        if verbose:
            print(s, type(o), repr(o), file=stderr)

        for typ, handler in all_handlers.items():
            if isinstance(o, typ):
                s += sum(map(sizeof, handler(o)))
                break
        return s

    return sizeof(o)
