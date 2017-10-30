# -*- coding: utf-8 -*-

# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.
import codecs

from setuptools import setup, find_packages

README = codecs.open('README.rst', encoding='utf-8').read()

setup(
    name="tsuru-rpaas",
    version="0.2.1",
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
        "cffi==1.8.3",
        "cryptography==2.0.3",
        "Flask==0.12",
        "requests==2.18.4",
        "gevent==1.1b6",
        "gunicorn==0.17.2",
        "tsuru-hm==0.6.10",
        "celery[redis]==3.1.23",
        "flower==0.9.1",
        "GloboNetworkAPI==0.2.2",
        "python-consul==0.6.1",
        "raven==4.2.3",
        "blinker==1.4",
        "acme==0.18.1",
        "certbot==0.18.1",
        "certifi==2016.9.26",
        "pbr==3.1.1",
        "Babel==2.3.4",
        "zope.interface==4.4.2",
        "parsedatetime==2.1",
    ],
    extras_require={
        'tests': [
            "mock==2.0.0",
            "flake8==2.1.0",
            "coverage==3.7.1",
            "freezegun==0.3.7",
        ]
    },
)
