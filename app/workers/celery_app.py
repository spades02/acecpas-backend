"""
AceCPAs Backend - Celery Application
Async task queue configuration for background processing.
"""
from celery import Celery

from app.config import get_settings

settings = get_settings()

# Create Celery app
celery_app = Celery(
    "acecpas",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Task expiration
    task_soft_time_limit=600,   # 10 minutes soft limit
    task_time_limit=900,        # 15 minutes hard limit
    result_expires=86400,       # Results expire after 24 hours
    
    # Worker settings
    worker_prefetch_multiplier=1,  # One task at a time for heavy processing
    worker_concurrency=2,          # Number of concurrent workers
    
    # Retry settings
    task_acks_late=True,           # Acknowledge after completion
    task_reject_on_worker_lost=True,
    
    # Routing
    task_routes={
        "app.workers.tasks.process_gl_file": {"queue": "ingestion"},
        "app.workers.tasks.run_mapper_agent": {"queue": "ai"},
        "app.workers.tasks.run_auditor_agent": {"queue": "ai"},
    },
    
    # Default queue
    task_default_queue="default",
)
