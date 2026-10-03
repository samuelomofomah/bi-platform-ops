.PHONY: install lint test demo image

install:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements-dev.txt

lint:
	.venv/bin/ruff check .
	bash -n scripts/linux_health.sh

test:
	.venv/bin/python -m unittest -v

# Full run with no real servers: three days of snapshots, a backup, a refresh, then the report.
demo:
	rm -f demo.db
	BIOPS_MOCK=1 BIOPS_DB=demo.db .venv/bin/python -m biops health
	for d in 2026-10-01 2026-10-02 2026-10-03; do BIOPS_MOCK=1 BIOPS_DB=demo.db .venv/bin/python -m biops collect --date $$d; done
	BIOPS_MOCK=1 BIOPS_DB=demo.db .venv/bin/python -m biops backup
	BIOPS_MOCK=1 BIOPS_DB=demo.db .venv/bin/python -m biops refresh
	BIOPS_MOCK=1 BIOPS_DB=demo.db .venv/bin/python -m biops report

image:
	docker build -t bi-platform-ops:local .
