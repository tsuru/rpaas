# -*- coding: utf-8 -*-

# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.
import codecs

from setuptools import setup, find_packages

README = codecs.open('README.rst', encoding='utf-8').read()

setup(
    name="tsuru-rpaas",
    version="0.4.1",
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
        "acme==0.9.3",
        "amqp==1.4.9",
        "anyjson==0.3.3",
        "asn1crypto==1.4.0",
        "Babel==2.3.4",
        "backports.ssl-match-hostname==3.7.0.1",
        "billiard==3.3.0.23",
        "blinker==1.4",
        "boto==2.25.0",
        "celery[redis]==3.1.23",
        "certbot==0.9.3",
        "certifi==2017.4.17",
        "cffi==1.8.3",
        "chardet==3.0.4",
        "click==7.1.2",
        "ConfigArgParse==1.2.3",
        "configobj==5.0.6",
        "cryptography==2.1.4",
        "enum34==1.1.10",
        "Flask==0.12.4",
        "flower==0.9.1",
        "futures==3.3.0",
        "gevent==1.1b6",
        "GloboNetworkAPI==0.8.1",
        "greenlet==0.4.17",
        "gunicorn==19.5.0",
        "idna==2.6",
        "ipaddress==1.0.23",
        "itsdangerous==1.1.0",
        "Jinja2==2.11.2",
        "kombu==3.0.37",
        "letsencrypt==0.7.0",
        "MarkupSafe==1.1.1",
        "ndg-httpsclient==0.5.1",
        "parsedatetime==2.1",
        "pbr==3.1.1",
        "pyasn1==0.4.8",
        "pycparser==2.20",
        "pymongo==3.3.0",
        "pyOpenSSL==17.5.0",
        "pyRFC3339==1.1",
        "python-consul==0.6.1",
        "python2-pythondialog==3.5.1",
        "pytz==2020.4",
        "raven==4.2.3",
        "redis==2.10.6",
        "requests==2.18.4",
        "six==1.15.0",
        "tornado==4.2",
        "tsuru-hm==0.6.18",
        "tsuru-rpaas==0.4.1",
        "urllib3==1.22",
        "Werkzeug==0.11.15",
        "zope.component==4.6.2",
        "zope.deferredimport==4.3.1",
        "zope.deprecation==4.4.0",
        "zope.event==4.5.0",
        "zope.hookable==5.0.1",
        "zope.interface==4.3.3",
        "zope.proxy==4.3.5",
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
