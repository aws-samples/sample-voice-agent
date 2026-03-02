#!/bin/bash
# Voice agent container entrypoint
# Supports two modes:
#   SERVICE_MODE=true: Run HTTP server for always-on service (handles multiple calls)
#   SERVICE_MODE=false/unset: Run single ECS task (one call per container)

set -e

if [ "$SERVICE_MODE" = "true" ]; then
    echo "Starting voice agent in SERVICE mode (HTTP server on port ${SERVICE_PORT:-8080})"
    exec python -m app.service_main
else
    echo "Starting voice agent in TASK mode (single call)"
    exec python -m app.ecs_main
fi
