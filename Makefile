VENV := .venv
PY := $(VENV)/bin/python
ALTERGO := $(VENV)/bin/altergo

.PHONY: help dev run settings config clean which global-version dev-version

help:
	@echo "altergo dev targets (isolated from your global pip install)"
	@echo ""
	@echo "  make dev               Create $(VENV)/ and install local source in editable mode"
	@echo "  make run ARGS='...'    Run local altergo with ARGS (e.g. ARGS='--settings')"
	@echo "  make settings          Shortcut: make run ARGS='--settings'"
	@echo "  make config NAME=foo   Shortcut: make run ARGS='--config --name foo'"
	@echo "  make which             Show resolved local vs global altergo paths"
	@echo "  make dev-version       Print version from $(VENV)"
	@echo "  make global-version    Print version from your global install"
	@echo "  make clean             Remove $(VENV)/"

$(ALTERGO): pyproject.toml altergo.py
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(PY) -m pip install --quiet --upgrade pip
	@$(PY) -m pip install --quiet -e .
	@touch $(ALTERGO)

dev: $(ALTERGO)
	@echo "Local altergo ready at $(ALTERGO)"

run: $(ALTERGO)
	@$(ALTERGO) $(ARGS)

settings: $(ALTERGO)
	@$(ALTERGO) --settings

config: $(ALTERGO)
	@$(ALTERGO) --config $(if $(NAME),--name $(NAME),)

which: $(ALTERGO)
	@echo "Local:  $(ALTERGO)"
	@echo "Global: $$(command -v altergo 2>/dev/null || echo '<not installed>')"

dev-version: $(ALTERGO)
	@$(ALTERGO) --version 2>/dev/null || $(PY) -c "import altergo; print(altergo.__version__)"

global-version:
	@command -v altergo >/dev/null && altergo --version 2>/dev/null || pip show altergo 2>/dev/null | awk '/^Version:/ {print $$2}'

clean:
	rm -rf $(VENV)
