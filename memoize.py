#!/usr/bin/env python
# -*- coding: utf-8 -*-
####################################################################################################
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
####################################################################################################
#
# This file incorporates work covered by the following copyrights and
# permission notices:
#
####################################################################################################
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
####################################################################################################
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

try:
    from reprlib import repr
except ImportError:
    pass

from decorator import decorator
import psutil

MEMOIZED_FUNCS = set()
CACHES = []
MASTER_CACHE = []
MASTER_LOCK = RLock()
TARGET_MEMORY_USE_RATIO = 1.0


class CacheMonitor(threading.Thread):
    """Thread to monitor cache size even when the main thread is blocked."""

    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True

    def run(self):
        global MASTER_LOCK
        while True:
            with MASTER_LOCK:
                shrink_cache()
            time.sleep(random.random() * 10)

MONITOR = CacheMonitor()


def start_cache_monitor():
    """Make sure only one cache monitor can be running at a time."""
    if not any(isinstance(thread, CacheMonitor) for thread in threading.enumerate()):
        MONITOR.start()


@functools.total_ordering
class CacheEntry(object):
    def __init__(self, func, key, duration, result, expiration=sys.maxint, *args, **kwargs):
        self.func = func
        self.key = key
        self.duration = duration
        self._result = result
        self.last_used = time.time()
        self.expiration = expiration or sys.maxint
        self.time_to_expire = time.time() + self.expiration
        self.args = args
        self.kwargs = kwargs
        self.size = _total_size(self._result)

    def __eq__(self, other):
        return self.score == other.score

    def __lt__(self, other):
        return self.score < other.score

    def __hash__(self):
        return self.key

    def recalculate_size(self):
        self.size = _total_size(self._result)
        return self.size

    @property
    def age(self):
        return time.time() - self.last_used

    @property
    def score(self):
        return (self.size * self.duration) / (self.age ** 2)

    @property
    def result(self):
        if time.time() > self.time_to_expire:
            self._result = self.func(*self.args, **self.kwargs)
            self.recalculate_size()
            self.time_to_expire = time.time() + self.expiration
        self.last_used = time.time()
        return self._result

    def __repr__(self):
        return '{} {} {}'.format(self.func.__name__, self.key, self.score)


def _memoize(func, *args, **kw):
    """
    Cache the results of calling func with args and kw. Return cached
    results if possible. Maintain a dynamically sized cache based on
    function execution time and the available free memory ratio.

    You probably should use the memoized decorator instead of calling this
    directly.
    """
    global MASTER_LOCK
    global MASTER_CACHE
    with func.lock, MASTER_LOCK:
        if not isinstance(args, collections.Hashable):
            result = func(*args, **kw)
            return result
        if kw:
            # frozenset is used to ensure hashability
            key = args, frozenset(kw.items())
        else:
            key = args
        # func.cache attribute added by memoize
        cache = func.cache
        try:
            if key in cache:
                result = cache[key].result
                shrink_cache()
                return result
        except TypeError:
            result = func(*args, **kw)
            return result

        start = time.time()
        result = func(*args, **kw)
        end = time.time()
        duration = end - start

        cache[key] = CacheEntry(func, key, duration, result, kw.get('expiration'), *args, **kw)
        shrink_cache()
        MASTER_CACHE.append(cache[key])
        return result


def shrink_cache(memory_use_ratio=TARGET_MEMORY_USE_RATIO):
    """
    Calculate the current size of our global cache, get the current size of free memory,
    and delete cache entries until the ratio of cache size to free memory is under the
    target ratio.
    """
    global MASTER_CACHE
    global MASTER_LOCK
    with MASTER_LOCK:
        size_ratio = float((1.0 * _total_size(MASTER_CACHE)) / psutil.virtual_memory().free)
        if size_ratio > memory_use_ratio:
            MASTER_CACHE = sorted(MASTER_CACHE, key=lambda i: i.score, reverse=True)
        start = time.time()
        while size_ratio > memory_use_ratio and time.time() - start < 5:
            try:
                to_delete = MASTER_CACHE.pop()
            except IndexError:
                break
            del to_delete.func.cache[to_delete.key]
            size_ratio = ((TARGET_MEMORY_USE_RATIO * _total_size(MASTER_CACHE)) /
                          psutil.virtual_memory().free)


def memoized(f):
    """
    Memoize the decorated function.

    @memoized
    def foo(bar):
        return bar
    """
    f.cache = {}
    f.lock = RLock()
    return decorator(_memoize, f)


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
