#!/usr/bin/env python

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

short_description = 'Global LRU cache decorator'
try:
    description = open('README.md').read()
except IOError:
    description = short_description

try:
    license = open('LICENSE').read()
except IOError:
    license = 'MIT License'

setup(
    name='global_lru_cache',
    packages=['global_lru_cache'],  # this must be the same as the name above
    version='1.0',
    description=short_description,
    author='Guy Kisel',
    author_email='guy.kisel@gmail.com',
    url='https://github.com/guykisel/global_lru_cache',
    keywords='lru cache memoize decorator',  # arbitrary keywords
    classifiers=[],
    install_requires=['psutil', 'decorator'],
    long_description=description,
    license=license,
)
