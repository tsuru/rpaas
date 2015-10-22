#!/bin/sh

case $RPAAS_ROLE in
    "worker")
        celery -A rpaas.tasks worker
        ;;
    "flower")
        celery flower -A rpaas.tasks --address=0.0.0.0 --port=$PORT --basic_auth=$FLOWER_USER:$FLOWER_PASSWORD
        ;;
    *)
        gunicorn rpaas.api:api -b 0.0.0.0:$PORT --access-logfile - -t 120
        ;;
esac
