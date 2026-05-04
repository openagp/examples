.PHONY: demo install clean

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

demo: install
	@$(PY) demo.py

install: $(VENV)/.installed

$(VENV)/.installed: requirements.txt
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(PIP) install --quiet --upgrade pip
	@$(PIP) install --quiet -r requirements.txt
	@touch $(VENV)/.installed

clean:
	@rm -rf output $(VENV) __pycache__
	@echo "cleaned"
