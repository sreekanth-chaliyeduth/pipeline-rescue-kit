.PHONY: up down verify clean secrets demo

VERIFY_ARGS ?=

up:
	./harness/scripts/up.sh

down:
	docker compose -f harness/docker-compose.yml down --remove-orphans

# Set PRK_VERIFY_EVID to choose the evidence directory, for example
# PRK_VERIFY_EVID=evidence/task-1.3a/verify make verify
# Add VERIFY_ARGS=--overwrite to replace an existing verification.json.
verify:
	python3 harness/scripts/verify.py $(VERIFY_ARGS)

demo:
	python3 harness/scripts/demo.py

clean:
	./harness/scripts/bootstrap-secrets.sh
	docker compose -f harness/docker-compose.yml down --remove-orphans -v
	rm -rf .secrets

secrets:
	./harness/scripts/bootstrap-secrets.sh
