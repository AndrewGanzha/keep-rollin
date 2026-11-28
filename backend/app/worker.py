import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from fastapi import FastAPI, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sentry_sdk import Client
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.db import configure_session, create_engine
from app.logging import configure_logging
from app.models import Tenant
from app.worker_jobs import JOBS, Job

logger = logging.getLogger("app.worker")
WORKER_ROLE = "keep_rollin_worker"
LOCK = text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))")
UNLOCK = text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))")


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKER_", env_file=".env", extra="ignore")

    database_url: SecretStr = Field(min_length=1)
    interval_seconds: int = Field(default=60, ge=1)
    batch_size: int = Field(default=500, ge=1, le=1000)
    sentry_dsn: SecretStr | None = None


class TenantJobFailed(RuntimeError):
    """One or more tenants could not complete the job."""


@asynccontextmanager
async def job_connection(engine: AsyncEngine, job: str) -> AsyncIterator[AsyncConnection | None]:
    key = {"key": f"keep-rollin:worker:{job}"}
    async with engine.connect() as connection:
        try:
            acquired = bool((await connection.execute(LOCK, key)).scalar_one())
            await connection.commit()
            yield connection if acquired else None
            if acquired:
                await connection.rollback()
                unlocked = (await connection.execute(UNLOCK, key)).scalar_one()
                await connection.commit()
                if not unlocked:
                    raise RuntimeError("worker advisory lock was lost")
        except BaseException:
            # Leave neither a session lock nor an uncertain transaction in the pool.
            await connection.invalidate()
            raise


def worker_session(connection: AsyncConnection, tenant_id: UUID | None = None) -> AsyncSession:
    session = AsyncSession(bind=connection, expire_on_commit=False, autoflush=False)
    configure_session(session, tenant_id=tenant_id, database_role=WORKER_ROLE)
    return session


class Worker:
    def __init__(self, engine: AsyncEngine, settings: WorkerSettings) -> None:
        self.engine = engine
        self.batch_size = settings.batch_size
        self.interval_seconds = settings.interval_seconds
        self.scheduler = AsyncIOScheduler(job_defaults={"coalesce": True, "max_instances": 1})
        self.accepting = True
        self.running: set[asyncio.Task[None]] = set()
        self.sentry = (
            Client(
                dsn=settings.sentry_dsn.get_secret_value(),
                default_integrations=False,
                auto_enabling_integrations=False,
                include_local_variables=False,
            )
            if settings.sentry_dsn
            else None
        )
        self.registry = CollectorRegistry()
        self.runs = Counter(
            "worker_job_runs",
            "Finished runs by outcome",
            ("job", "outcome"),
            registry=self.registry,
        )
        self.errors = Counter("worker_job_errors", "Failed runs", ("job",), registry=self.registry)
        self.duration = Histogram(
            "worker_job_duration_seconds",
            "Job wall-clock time",
            ("job",),
            registry=self.registry,
        )
        self.processed = Counter(
            "worker_job_records_processed",
            "Committed operations",
            ("job",),
            registry=self.registry,
        )
        for job in JOBS:
            for outcome in ("success", "failed", "skipped"):
                self.runs.labels(job, outcome)
            self.errors.labels(job)
            self.duration.labels(job)
            self.processed.labels(job)

    def start(self) -> None:
        for name, job in JOBS.items():
            self.scheduler.add_job(
                self.run,
                "interval",
                args=(name, job),
                id=name,
                seconds=self.interval_seconds,
                next_run_time=datetime.now(UTC),
            )
        self.scheduler.start()

    async def close(self) -> None:
        self.accepting = False
        try:
            if self.scheduler.running:
                self.scheduler.pause()
            if self.running:
                # APScheduler 3 cancels futures at shutdown, even with wait=True.
                await asyncio.gather(*self.running, return_exceptions=True)
        finally:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            try:
                if self.sentry is not None:
                    await asyncio.to_thread(self.sentry.close, 2)
            finally:
                await self.engine.dispose()

    async def ready(self) -> bool:
        try:
            async with (
                asyncio.timeout(2),
                self.engine.connect() as connection,
                worker_session(connection) as session,
                session.begin(),
            ):
                await session.execute(select(Tenant.id).where(Tenant.is_active).limit(1))
        except Exception:
            return False
        return True

    async def run(self, name: str, job: Job) -> None:
        if not self.accepting:
            return
        task = asyncio.current_task()
        assert task is not None
        self.running.add(task)
        started = perf_counter()
        trace_id = uuid4().hex
        fields = {"job": name, "trace_id": trace_id}
        outcome = "success"
        try:
            async with job_connection(self.engine, name) as connection:
                if connection is None:
                    outcome = "skipped"
                else:
                    await self._process_tenants(connection, name, job, trace_id)
        except Exception as error:
            outcome = "failed"
            self.errors.labels(name).inc()
            logger.error("worker job failed", extra={**fields, "error_type": type(error).__name__})
            if self.sentry is not None:
                self.sentry.capture_event(
                    {
                        "message": "worker job failed",
                        "level": "error",
                        "tags": {**fields, "error_type": type(error).__name__},
                    }
                )
        finally:
            self.running.remove(task)
            self.runs.labels(name, outcome).inc()
            self.duration.labels(name).observe(perf_counter() - started)
            if outcome != "failed":
                logger.info("worker job finished", extra={**fields, "outcome": outcome})

    async def _process_tenants(
        self, connection: AsyncConnection, name: str, job: Job, trace_id: str
    ) -> None:
        async with worker_session(connection) as session, session.begin():
            tenants = (
                await session.scalars(select(Tenant.id).where(Tenant.is_active).order_by(Tenant.id))
            ).all()
            now: datetime = (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
        failed = False
        for tenant_id in tenants:
            try:
                while self.accepting:
                    async with worker_session(connection, tenant_id) as session, session.begin():
                        await session.execute(text("SET LOCAL lock_timeout = '5s'"))
                        await session.execute(text("SET LOCAL statement_timeout = '25s'"))
                        processed = await job(session, now, self.batch_size, trace_id)
                    self.processed.labels(name).inc(processed)
                    if not processed:
                        break
            except Exception as error:
                # An invalidated connection has lost its advisory lock.
                if connection.invalidated:
                    raise
                failed = True
                logger.error(
                    "worker tenant failed",
                    extra={
                        "job": name,
                        "trace_id": trace_id,
                        "tenant_id": tenant_id,
                        "error_type": type(error).__name__,
                    },
                )
        if failed:
            raise TenantJobFailed


def create_app(settings: WorkerSettings | None = None) -> FastAPI:
    settings = settings if settings is not None else WorkerSettings()
    configure_logging("app.worker")
    worker = Worker(create_engine(settings.database_url.get_secret_value()), settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            worker.start()
            yield
        finally:
            await worker.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready() -> Response:
        return Response(status_code=200 if await worker.ready() else 503)

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(worker.registry), media_type=CONTENT_TYPE_LATEST)

    return app
