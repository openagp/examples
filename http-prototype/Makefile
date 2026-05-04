.PHONY: install plane vendor demo clean

VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip
UVI  := $(VENV)/bin/uvicorn

# Default target: run the full demo end-to-end.
demo: install
	@echo ""
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo "  AGP HTTP prototype — running plane + vendor end-to-end"
	@echo "═══════════════════════════════════════════════════════════════════"
	@rm -f ledger.db
	@$(UVI) plane:app --host 127.0.0.1 --port 8000 --log-level warning & \
	  PLANE_PID=$$!; \
	  sleep 1.5; \
	  echo "  plane up at http://127.0.0.1:8000  (pid $$PLANE_PID)"; \
	  echo "  dashboard:    http://127.0.0.1:8000/"; \
	  echo ""; \
	  $(PY) vendor.py --include-forged --delay 0.4; \
	  echo ""; \
	  echo "  ─── leaving plane running for 30s so you can poke at the dashboard"; \
	  echo "  ─── press Ctrl-C to stop early"; \
	  sleep 30; \
	  kill $$PLANE_PID 2>/dev/null; \
	  echo "  plane stopped"

# Run plane only, in foreground (for opening the dashboard yourself).
plane: install
	@$(UVI) plane:app --host 127.0.0.1 --port 8000 --reload

# Run vendor only (against an already-running plane).
vendor: install
	@$(PY) vendor.py

# Run vendor with a longer "burst" of random extras (for stress-testing the dashboard).
burst: install
	@$(PY) vendor.py --burst 20 --delay 0.2 --include-forged

install: $(VENV)/.installed

$(VENV)/.installed: requirements.txt
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(PIP) install --quiet --upgrade pip
	@$(PIP) install --quiet -r requirements.txt
	@touch $(VENV)/.installed

clean:
	@rm -rf $(VENV) ledger.db __pycache__ *.egg-info
	@echo "cleaned"
