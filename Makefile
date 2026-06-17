# PTCG ActiveGraph — common commands.
# Run `make help` for a list.

PYTHON ?= python3
DECK   ?= deck.csv
GAMES  ?= 20

.PHONY: help test test-v lint selfplay tournament report submission verify-submission \
	inspect-cards smoke demo resolve-deck record-schema first-run clean \
	ag-summary plan-experiments generate-candidates run-experiments rank-candidates \
	report-site queue-submissions fetch-kaggle-status lab-batch

LIMIT  ?= 8

help:  ## Show this help.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

test:  ## Run the unit test suite.
	$(PYTHON) -m pytest

test-v:  ## Run tests verbosely.
	$(PYTHON) -m pytest -v

demo:  ## Show main.py's built-in demo decision (no cabt needed).
	$(PYTHON) main.py

resolve-deck:  ## Resolve a real deck.csv from sample/provided/generated sources.
	$(PYTHON) scripts/resolve_deck.py

smoke:  ## Run the cabt/kaggle smoke test (one full self-play game; needs cabt).
	$(PYTHON) scripts/kaggle_smoke_test.py --deck $(DECK) --games 1

record-schema:  ## Record the real cabt option schema via self-play (needs cabt).
	$(PYTHON) scripts/record_schema.py --games $(GAMES) --deck $(DECK)

first-run:  ## Preflight chain: tests -> resolve deck -> verify submission.
	$(PYTHON) -m pytest -q
	$(PYTHON) scripts/resolve_deck.py || true
	$(PYTHON) scripts/package_submission.py --verify-only

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

ag-summary:  ## Summarize the ActiveGraph lab event stream.
	$(PYTHON) scripts/ag_event.py summary

plan-experiments:  ## List candidate experiments by priority (testable vs blocked).
	$(PYTHON) scripts/plan_experiments.py

generate-candidates:  ## Generate candidate branches into experiments/runs/. LIMIT= configurable.
	$(PYTHON) scripts/generate_candidates.py --limit $(LIMIT)

run-experiments:  ## Locally evaluate candidates vs the v1 control (needs cabt). GAMES= configurable.
	$(PYTHON) scripts/run_experiment_batch.py --games $(GAMES)

rank-candidates:  ## Rank evaluated candidates and write latest_ranking.{json,md}.
	$(PYTHON) scripts/rank_candidates.py

report-site:  ## Build the HTML report site + Markdown summary.
	$(PYTHON) scripts/build_report_site.py

queue-submissions:  ## Build the submission queue (DRY-RUN; never uploads).
	$(PYTHON) scripts/queue_submissions.py --dry-run

fetch-kaggle-status:  ## Read-only Kaggle submission status (needs credentials).
	$(PYTHON) scripts/fetch_kaggle_status.py

lab-batch:  ## Full lab loop: plan -> generate -> run -> rank -> report -> queue (dry-run).
	$(PYTHON) scripts/plan_experiments.py
	$(PYTHON) scripts/generate_candidates.py --limit $(LIMIT)
	$(PYTHON) scripts/run_experiment_batch.py --games $(GAMES)
	$(PYTHON) scripts/rank_candidates.py
	$(PYTHON) scripts/build_report_site.py
	$(PYTHON) scripts/queue_submissions.py --dry-run
