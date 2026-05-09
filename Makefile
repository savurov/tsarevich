SHELL := /bin/bash

.PHONY: init run

init:
	python -m venv .venv
	.venv/bin/pip install -r requirements.txt

run:
	set -a && source .env && set +a && .venv/bin/python src/main.py
