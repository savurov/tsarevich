SHELL := /bin/bash

.PHONY: init run

init:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

run:
	set -a && source .env && set +a && .venv/bin/watchfiles '.venv/bin/python src/main.py' src
