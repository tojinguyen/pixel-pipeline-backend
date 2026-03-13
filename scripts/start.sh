#!/bin/sh
set -e

echo "Running database migrations..."
uv run alembic upgrade head
echo "Database migrations completed successfully."

# Execute the container's main process (passed via CMD/command)
exec "$@"
