#!/usr/bin/env make

# this loads $(ENV_FILE) as both makefile variables and into shell env
ENV_FILE?=.env
ifneq ($(wildcard $(ENV_FILE)),)
include $(ENV_FILE)
export $(shell sed 's/=.*//' $(ENV_FILE))
endif

.PHONY:  deps format docs

deps:
	./dependencies.py

format:
	ruff format .
	ruff check --fix .

docs:
	make -C docs html
