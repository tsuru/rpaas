# -*- coding: utf-8 -*-

# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.
import codecs

from setuptools import setup, find_packages

README = codecs.open('README.rst', encoding='utf-8').read()

setup(
    name="tsuru-rpaas",
    version="0.4.0",
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
        "cryptography==2.1.4",
        "pyOpenSSL==17.5.0",
        "Flask==0.12.4",
        "Werkzeug==0.11.15",
        "requests==2.18.4",
        "gevent==1.1b6",
        "gunicorn==19.5.0",
        "tsuru-hm==0.6.17",
        "celery[redis]==3.1.23",
        "flower==0.9.1",
        "GloboNetworkAPI==0.8.1",
        "python-consul==0.6.1",
        "raven==4.2.3",
        "blinker==1.4",
        "acme==0.9.3",
        "letsencrypt==0.7.0",
        "certbot==0.9.3",
        "certifi==2016.9.26",
        "pbr==3.1.1",
        "Babel==2.3.4",
        "zope.interface==4.3.3",
        "parsedatetime==2.1",
        "redis==2.10.6",
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
