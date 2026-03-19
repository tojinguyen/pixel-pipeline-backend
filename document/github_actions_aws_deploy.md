# GitHub Actions auto deploy to AWS EC2

This project includes the workflow `.github/workflows/deploy-aws-ec2.yml`.

## Trigger

- Auto trigger: when a Pull Request into `main` is closed and merged.
- Manual trigger: from GitHub Actions via `workflow_dispatch`.

## Required repository secrets

Set these in **GitHub repository settings** -> **Secrets and variables** -> **Actions**:

- `AWS_EC2_HOST`: Public DNS or public IP of your EC2.
- `AWS_EC2_USER`: SSH username on EC2 (for example: `ubuntu` or `ec2-user`).
- `AWS_EC2_SSH_PRIVATE_KEY`: Private key content used to SSH from GitHub Actions.
- `AWS_EC2_PORT` (optional): SSH port, default is `22`.
- `EC2_APP_DIR` (optional): Absolute path of the repo on EC2, default is `/opt/pixel-pipeline-backend`.

## Server requirements

Your EC2 instance should already have:

- Git
- Docker
- Docker Compose (`docker compose` or `docker-compose`)
- This repository cloned at `EC2_APP_DIR`
- Runtime env file prepared (for example `.env`)

## What the deploy job does

1. SSH to EC2
2. Move to `EC2_APP_DIR`
3. Pull latest `main`:
   - `git fetch origin main`
   - `git checkout main`
   - `git reset --hard origin/main`
4. Rebuild and restart services:
   - `docker compose up -d --build --remove-orphans`
5. Cleanup dangling images:
   - `docker image prune -f`
