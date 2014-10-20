# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

.PHONY: test test_deps

run:
	python run.py

test: test_deps
	@python -m unittest discover
	@flake8 --max-line-length=110 .

test_deps:
	pip install -e .[tests]

coverage: test_deps
	rm -f .coverage
	coverage run --source=. -m unittest discover
	coverage report -m --omit=test\*,run\*.py
