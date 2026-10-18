"""Runs author stage jobs under a lease; recovers jobs whose worker died."""

import asyncio
import logging

from app.core.authoring import jobs
from app.core.authoring.pipeline import ESTIMATE_USD, HANDLERS, StageContext, StageError, record_output
from app.core.campaigns import Conflict
from app.db.models import AuthorJob, AuthorProject

log = logging.getLogger(__name__)


class AuthorRunner:
    def __init__(self, svc, handlers=None, interval: float = 5.0):
        self.svc = svc
        self.handlers = handlers if handlers is not None else HANDLERS
        self.interval = interval
        self._task: asyncio.Task | None = None

    async def run_due(self, maker=None) -> None:
        maker = maker or self.svc.maker
        async with maker() as s:
            ids = await jobs.due_job_ids(s)
        for job_id in ids:
            await self.prepare(job_id)

    async def prepare(self, job_id: str) -> None:
        maker = self.svc.maker
        async with maker() as s:
            token = await jobs.claim(s, job_id)
            await s.commit()
            if token is None:
                return
            job = await s.get(AuthorJob, job_id)
            project = await s.get(AuthorProject, job.project_id)
            handler = self.handlers.get(job.stage)
            if handler is None:
                await self._end(s, job_id, token, "blocked", error_code="stage_unavailable")
                return
            if not await jobs.reserve(s, project, job_id, ESTIMATE_USD.get(job.stage, 0.0)):
                await self._end(s, job_id, token, "blocked", error_code="budget_exhausted")
                return
            await s.commit()
            ctx = StageContext(
                svc=self.svc,
                project_id=project.id,
                world_id=project.workspace_campaign_id,
                job_id=job_id,
                stage=job.stage,
            )
            await s.rollback()  # сетевой вызов не держит транзакцию
        try:
            result = await handler(ctx)
        except StageError as exc:
            await self._finish(job_id, token, "failed", error_code=exc.code)
            return
        except Exception:  # noqa: BLE001 — сбой этапа не должен ронять сервер
            log.exception("этап автора %s не выполнен", job_id)
            await self._finish(job_id, token, "failed", error_code="internal_error")
            return
        async with maker() as s:
            job = await s.get(AuthorJob, job_id)
            project = await s.get(AuthorProject, job.project_id)
            if job.lease_token != token:  # lease перехвачен: результат устарел
                return
            try:
                await record_output(s, project, job, result)
            except (StageError, Conflict) as exc:
                await s.rollback()
                await self._finish(job_id, token, "stale", error_code=getattr(exc, "code", "stale_revision"))
                return
            if await jobs.finish(s, job_id, token, "ready", result=result):
                await s.commit()
            else:
                await s.rollback()

    async def _finish(self, job_id, token, status, *, error_code=None):
        async with self.svc.maker() as s:
            await self._end(s, job_id, token, status, error_code=error_code)

    @staticmethod
    async def _end(s, job_id, token, status, *, error_code=None):
        await jobs.finish(s, job_id, token, status, error_code=error_code)
        await s.commit()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_due()
            except Exception:  # noqa: BLE001
                log.exception("восстановление этапов автора не удалось")
            await asyncio.sleep(self.interval)
