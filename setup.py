# -*- coding: utf-8 -*-

# Copyright 2014 hm authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.
import codecs

from setuptools import setup, find_packages

from rpaas import __version__

README = codecs.open('README.rst', encoding='utf-8').read()

setup(
    name="tsuru-rpaas",
    version=__version__,
    description="Reverse proxy as-a-service API for Tsuru PaaS",
    long_description=README,
    author="Tsuru",
    author_email="tsuru@corp.globo.com",
    classifiers=[
        "Programming Language :: Python :: 2.7",
    ],
    packages=find_packages(exclude=["docs", "tests"]),
    include_package_data=True,
    install_requires=[
        "Flask==0.9",
        "requests==2.4.3",
        "gunicorn==0.17.2",
        "tsuru-hm==0.1.3",
        "celery[redis]",
        "flower==0.7.3",
    ],
    extras_require={
        'tests': [
            "mock==1.0.1",
            "flake8==2.1.0",
            "coverage==3.7.1",
            "freezegun==0.1.16",
        ]
    },
)
