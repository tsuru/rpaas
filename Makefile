# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

.PHONY: test deps

run: deps
	python ./rpaas/api.py

worker: deps
	celery -A rpaas.tasks worker

flower: deps
	celery flower -A rpaas.tasks

test: deps
	@python -m unittest discover
	@flake8 --max-line-length=110 .

deps:
	pip install -e .[tests]

coverage: deps
	rm -f .coverage
	coverage run --source=. -m unittest discover
	coverage report -m --omit=test\*,run\*.py
