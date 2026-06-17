# PTCG ActiveGraph — common commands.
# Run `make help` for a list.

PYTHON ?= python3
DECK   ?= deck.csv
GAMES  ?= 20

.PHONY: help test test-v lint selfplay tournament report submission verify-submission inspect-cards smoke clean

help:  ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

test:  ## Run the unit test suite.
	$(PYTHON) -m pytest

test-v:  ## Run tests verbosely.
	$(PYTHON) -m pytest -v

smoke:  ## Run main.py's built-in smoke test.
	$(PYTHON) main.py

selfplay:  ## Run local self-play (needs cabt). GAMES=, DECK= configurable.
	$(PYTHON) scripts/run_self_play.py --games $(GAMES) --deck $(DECK)

tournament:  ## Run a round-robin tournament (needs cabt).
	$(PYTHON) scripts/run_tournament.py --deck $(DECK)

inspect-cards:  ## Inspect the card database and role tags.
	$(PYTHON) scripts/inspect_cards.py

report:  ## Generate the Strategy report draft.
	$(PYTHON) scripts/generate_report.py

verify-submission:  ## Verify main.py + deck.csv without building the tarball.
	$(PYTHON) scripts/package_submission.py --verify-only

submission:  ## Build the Kaggle submission tarball.
	$(PYTHON) scripts/package_submission.py

clean:  ## Remove generated artifacts (submissions, reports, replays, caches).
	rm -rf data/submissions/*.tar.gz data/reports/*.md
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name '.pytest_cache' -prune -exec rm -rf {} +
