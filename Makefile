PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: venv install dev test lint clean demo doctor system-install

venv:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

install: venv
	$(BIN)/pip install -e .

dev: venv
	$(BIN)/pip install -e ".[dev]"

# Install as a system-wide command (one-click script)
system-install:
	./install.sh

test:
	$(BIN)/python -m pytest -q

doctor:
	$(BIN)/python -m imount doctor

demo:
	@mkdir -p /tmp/imount_demo_src/DCIM/100APPLE /tmp/imount_demo_mnt
	@echo demo > /tmp/imount_demo_src/DCIM/100APPLE/IMG_0001.JPG
	$(BIN)/python -m imount demo /tmp/imount_demo_src /tmp/imount_demo_mnt -p /DCIM

clean:
	rm -rf build dist *.egg-info .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
