SHELL := /bin/bash
DB ?= data/database.sqlite3

.PHONY: init run admin

init:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

run:
	rm -f database.sqlite3 database.sqlite3-shm database.sqlite3-wal
	set -a && source .env && set +a && .venv/bin/watchfiles '.venv/bin/python src/main.py' src

admin:
	@sqlite3 $(DB) "UPDATE users SET is_admin = 1;"
	@echo "ты теперь адмиииин, тьмаффки тебя! <3"
