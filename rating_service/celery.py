import os
from celery import Celery

broker = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@rabbitmq:5672//")

app = Celery("rating", broker=broker, backend="rpc://")