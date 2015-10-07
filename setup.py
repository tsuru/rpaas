# -*- coding: utf-8 -*-

# Copyright 2015 hm authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.
import codecs

from setuptools import setup, find_packages

README = codecs.open('README.rst', encoding='utf-8').read()

setup(
    name="tsuru-rpaas",
    version="0.1.0",
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
        "tsuru-hm==0.3.0",
        "celery[redis]",
        "flower==0.7.3",
        "GloboNetworkAPI==0.2.2",
        "cffi==1.2.1",
        "cryptography==1.0.1",
        "enum34==1.0.4",
        "idna==2.0",
        "ipaddress==1.0.14",
        "pyasn1==0.1.8",
        "pycparser==2.14",
    ],
    extras_require={
        'tests': [
            "mock==1.0.1",
            "flake8==2.1.0",
            "coverage==3.7.1",
            "freezegun==0.2.8",
        ]
    },
)
