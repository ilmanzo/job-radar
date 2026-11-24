"""Pipeline execution engine."""

from typing import List, Optional

from radar.models import Job, PipelineContext, RawJob
from radar.pipeline.base import PipelineStage
from radar.pipeline.contract import ContractStage
from radar.pipeline.freshness import FreshnessStage
from radar.pipeline.keywords import KeywordWeightStage
from radar.pipeline.location import LocationStage
from radar.pipeline.profile import ProfileMatchStage
from radar.pipeline.role import RoleSeniorityStage
from radar.pipeline.salary import SalaryStage
from radar.pipeline.title import TitleFilterStage
from radar.pipeline.workmode import WorkModeStage


class PipelineEngine:
    """Orchestrates passing raw jobs through ordered filtering & scoring stages."""

    def __init__(self, stages: Optional[List[PipelineStage]] = None):
        self.stages = stages or [
            TitleFilterStage(),
            LocationStage(),
            ContractStage(),
            RoleSeniorityStage(),
            SalaryStage(),
            ProfileMatchStage(),
            KeywordWeightStage(),
            WorkModeStage(),
            FreshnessStage(),
        ]

    def process(self, raw_job: RawJob, context: PipelineContext) -> Optional[Job]:
        """Process a raw job through all stages. Returns fully scored Job or None if rejected."""
        job = Job(
            id=raw_job.id,
            company_id=raw_job.company_id,
            title=raw_job.title,
            location=raw_job.location,
            url=raw_job.url,
            content=raw_job.content,
            posted_date=raw_job.posted_date,
            first_seen=context.first_seen,
        )

        for stage in self.stages:
            result = stage.process(raw_job, job, context)
            if not result.should_continue:
                return None
            job.score += result.score_delta
            if result.tags:
                job.tags.extend(result.tags)

        return job
