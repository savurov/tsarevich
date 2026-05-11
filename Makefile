SHELL := /bin/bash

.PHONY: init run

init:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

run:
	rm -f database.sqlite3 database.sqlite3-shm database.sqlite3-wal
	set -a && source .env && set +a && .venv/bin/watchfiles '.venv/bin/python src/main.py' src
