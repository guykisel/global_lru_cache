global_lru_cache
================

Python global LRU cache memoization decorator.


Installation
--------------------
`pip install global_lru_cache`


What is a global LRU cache?
================
There are a lot of great Python LRU caches available. Python 3 has [functools.lru_cache](https://docs.python.org/3/library/functools.html#functools.lru_cache) built in, and it's also been [backported to Python 2](http://code.activestate.com/recipes/578078-py26-and-py30-backport-of-python-33s-lru-cache/). There's also [pylru](https://github.com/jlhutch/pylru), [cachetools](https://github.com/tkem/cachetools), [lru-dict](https://github.com/amitdev/lru-dict), [repoze.lru](https://github.com/repoze/repoze.lru), and more out there. 

What all of these caches have in common is that when used as a function decorator, they maintain a separate cache for each decorated function, and you can usually only specify a maximum number of cache entries, without regard to actual size in memory. This is probably more than enough for the vast majority of use cases, but in some circumstances, it's more convenient to have a globally shared cache that automatically manages its size relative to available system memory. This can be useful, for example, when caching very large queries from very slow databases. If your cache ends up using significant percentages of system memory, you want to make sure you don't use too much memory, especially if you are sharing the system with other processes.

I was unable to find an existing implementation of such a cache, so I've taken some basic open source code I found online and modified it to suit my needs. The result is a library with a simple decorator that takes no arguments and manages all of your cached data as a single cache. I've called it an LRU cache, but when invalidating cache entries it actually uses a scoring function that takes into account time last accessed, size in memory of the cache entry, and duration of the cached function call. 


Usage
================
```python
from global_lru_cache import memoized

@memoized
def slow_function(arg1, arg2):
  time.sleep(30)
  return arg1 * arg2
```





