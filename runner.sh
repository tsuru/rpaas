#!/bin/sh

case $RPAAS_ROLE in
    "worker")
        celery -A rpaas.tasks worker
        ;;
    "flower")
        celery flower -A rpaas.tasks
        ;;
    *)
        gunicorn rpaas.api:api -b 0.0.0.0:$PORT
        ;;
esac
