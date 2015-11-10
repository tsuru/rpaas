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
    zip_safe = False,
    install_requires=[
        "setuptools==18.4",
        "Flask==0.9",
        "requests==2.4.3",
        "gunicorn==0.17.2",
        "tsuru-hm==0.4.1",
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
"Flask==0.9",
"GloboNetworkAPI==0.2.2",
"Jinja2==2.8",
"MarkupSafe==0.23",
"Werkzeug==0.10.4",
"amqp==1.4.6",
"anyjson==0.3.3",
"backports.ssl-match-hostname==3.4.0.2",
"billiard==3.3.0.20",
"boto==2.25.0",
"celery==3.1.18",
"certifi==2015.9.6.2",
"cffi==1.2.1",
"configobj==5.0.6",
"cryptography==1.0.1",
"enum34==1.0.4",
"flower==0.7.3",
"funcsigs==0.4",
"gunicorn==0.17.2",
"idna==2.0",
"ipaddress==1.0.14",
"kombu==3.0.26",

"mock==1.3.0",
"ndg-httpsclient==0.4.0",
"parsedatetime==1.5",
"pbr==1.8.1",
"psutil==3.2.2",
"pyOpenSSL==0.15.1",
"pyRFC3339==0.2",
"pyasn1==0.1.8",
"pycparser==2.14",
"pymongo==2.6.3",
"pyparsing==2.0.3",
"python2-pythondialog==3.3.0",
"pytz==2015.6",
"redis==2.10.3",
"requests==2.4.3",
"six==1.9.0",
"tornado==4.2.1",
"tsuru-hm==0.3.0",
"wsgiref==0.1.2",
"zope.component==4.2.2",
"zope.event==4.0.3",
"zope.interface==4.1.3",
"ConfigArgParse==0.9.3",
"ndg-httpsclient==0.4.0",
"pyOpenSSL==0.15.1",
"pyRFC3339==0.2",
"mock==1.3.0",
"funcsigs==0.4",
"pbr==1.8.1",

"acme==0.0.0.dev20151108",

"configobj==5.0.6",
"parsedatetime==1.5",
"psutil==3.2.2",
"python2-pythondialog==3.3.0",

"letsencrypt==0.0.0.dev20151108",

"pyparsing==2.0.3",

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
