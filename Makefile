.PHONY: build up down restart logs shell clean fclean

# ── Dev ───────────────────────────────────────────────────────────────────────

build:
	docker compose build

up:
	docker compose up -d

up-build:
	docker compose up --build

down:
	docker compose down

restart:
	docker compose restart api

# ── Logs ──────────────────────────────────────────────────────────────────────

logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

logs-minio:
	docker compose logs -f minio

# ── Shell ─────────────────────────────────────────────────────────────────────

shell:
	docker compose exec api /bin/bash

# ── Clean ─────────────────────────────────────────────────────────────────────

clean:
	docker compose down --remove-orphans

# Remove containers, volumes (wipes MinIO data), and built images
fclean:
	docker compose down --volumes --rmi local --remove-orphans
