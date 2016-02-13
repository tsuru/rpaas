# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

.PHONY: test deps

clean_pycs:
	find . -name \*.pyc -delete

run: deps
	python ./rpaas/api.py

worker: deps
	celery -A rpaas.tasks worker

flower: deps
	celery flower -A rpaas.tasks

start-consul:
	consul agent -server -bind 127.0.0.1 -bootstrap-expect 1 -data-dir /tmp/consul -config-file etc/consul.conf -node=rpaas-test &
	while ! consul info; do sleep 1; done

test: clean_pycs deps
	@python -m unittest discover
	@flake8 --max-line-length=110 .

deps:
	pip install -e .[tests]

coverage: deps
	rm -f .coverage
	coverage run --source=. -m unittest discover
	coverage report -m --omit=test\*,run\*.py
