"""Telegram-independent job application preparation and approval workflow."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from app.models.email import EmailStatus, EmailTone, SendResult
from app.models.job_application import (
    CandidateProfile,
    EmailAttachment,
    JobApplicationRequest,
    JobRequirements,
    PreparedEmail,
    RequirementMatchResult,
)
from app.services.attachment import CVAttachmentService
from app.services.candidate_profile import CandidateProfileService
from app.services.job_application_generator import JobApplicationEmailGenerator
from app.services.job_requirements import (
    CandidateRequirementMatcher,
    DeterministicJobRequirementExtractor,
)
from app.services.validation import (
    validate_email,
    validate_text,
)
from app.workflows.general_email import (
    ApprovalOutcome,
    DraftMode,
    GeneralEmailSession,
    GeneralEmailWorkflow,
    WorkflowStateError,
)


LOGGER = logging.getLogger(__name__)
MAX_COMPANY_NAME_LENGTH = 200
MAX_ROLE_LENGTH = 200
MAX_JOB_DESCRIPTION_LENGTH = 12_000


@dataclass(frozen=True, slots=True)
class JobApplicationResources:
    profile: CandidateProfile
    attachment: EmailAttachment


@dataclass(frozen=True, slots=True)
class JobApplicationSession:
    """Immutable job-specific state wrapping the shared approval session."""

    request: JobApplicationRequest
    profile: CandidateProfile
    requirements: JobRequirements
    match_result: RequirementMatchResult
    attachment: EmailAttachment
    tone: EmailTone
    approval: GeneralEmailSession

    @property
    def prepared_email(self) -> PreparedEmail:
        return PreparedEmail(
            draft=self.approval.draft,
            attachments=(self.attachment,),
        )

    @property
    def draft_mode(self) -> DraftMode:
        return self.approval.draft_mode


@dataclass(frozen=True, slots=True)
class JobApplicationApprovalOutcome:
    session: JobApplicationSession
    result: SendResult
    duplicate: bool = False


class JobApplicationWorkflow:
    """Compose profile, matching, generation, attachment, and shared approval."""

    def __init__(
        self,
        *,
        profile_service: CandidateProfileService,
        attachment_service: CVAttachmentService,
        requirement_extractor: DeterministicJobRequirementExtractor,
        matcher: CandidateRequirementMatcher,
        approval_workflow: GeneralEmailWorkflow,
    ) -> None:
        self._profile_service = profile_service
        self._attachment_service = attachment_service
        self._requirement_extractor = requirement_extractor
        self._matcher = matcher
        self._approval_workflow = approval_workflow

    async def prepare_resources(self) -> JobApplicationResources:
        profile = await self._profile_service.get_profile()
        attachment = await self._attachment_service.prepare()
        return JobApplicationResources(profile=profile, attachment=attachment)

    def start_manual(
        self,
        *,
        request: JobApplicationRequest,
        resources: JobApplicationResources,
        subject: str,
        body: str,
    ) -> JobApplicationSession:
        validated_request = self._validate_request(request)
        requirements, match_result = self._analyze(
            validated_request,
            resources.profile,
        )
        approval = self._approval_workflow.start_manual(
            recipient=validated_request.company_email,
            subject=subject,
            body=body,
        )
        approval = self._with_attachment(approval, resources.attachment)
        LOGGER.info("Manual job application draft generated")
        return JobApplicationSession(
            request=validated_request,
            profile=resources.profile,
            requirements=requirements,
            match_result=match_result,
            attachment=resources.attachment,
            tone=EmailTone.PROFESSIONAL,
            approval=approval,
        )

    async def start_ai(
        self,
        *,
        request: JobApplicationRequest,
        resources: JobApplicationResources,
        generator: JobApplicationEmailGenerator,
        tone: EmailTone,
    ) -> JobApplicationSession:
        validated_request = self._validate_request(request)
        requirements, match_result = self._analyze(
            validated_request,
            resources.profile,
        )
        draft = await generator.generate(
            request=validated_request,
            profile=resources.profile,
            requirements=requirements,
            match_result=match_result,
            tone=tone,
        )
        approval = GeneralEmailSession(
            request=None,
            draft=replace(
                draft,
                recipient=validated_request.company_email,
                attachments=(resources.attachment.file_path,),
                status=EmailStatus.PREVIEWED,
            ),
            draft_mode=DraftMode.AI,
        )
        LOGGER.info("AI job application draft generated")
        return JobApplicationSession(
            request=validated_request,
            profile=resources.profile,
            requirements=requirements,
            match_result=match_result,
            attachment=resources.attachment,
            tone=tone,
            approval=approval,
        )

    async def regenerate(
        self,
        session: JobApplicationSession,
        generator: JobApplicationEmailGenerator,
    ) -> JobApplicationSession:
        if session.draft_mode is not DraftMode.AI:
            raise WorkflowStateError("Manual applications cannot be regenerated.")
        requirements, match_result = self._analyze(session.request, session.profile)
        draft = await generator.generate(
            request=session.request,
            profile=session.profile,
            requirements=requirements,
            match_result=match_result,
            tone=session.tone,
        )
        approval = replace(
            session.approval,
            draft=replace(
                draft,
                recipient=session.request.company_email,
                attachments=(session.attachment.file_path,),
                status=EmailStatus.PREVIEWED,
            ),
        )
        LOGGER.info("Job application draft regenerated")
        return replace(
            session,
            requirements=requirements,
            match_result=match_result,
            approval=approval,
        )

    def edit_recipient(
        self,
        session: JobApplicationSession,
        company_email: str,
    ) -> JobApplicationSession:
        approval = self._approval_workflow.edit_recipient(
            session.approval,
            company_email,
        )
        request = replace(session.request, company_email=approval.draft.recipient)
        return replace(session, request=request, approval=approval)

    def edit_subject(
        self,
        session: JobApplicationSession,
        subject: str,
    ) -> JobApplicationSession:
        return replace(
            session,
            approval=self._approval_workflow.edit_subject(session.approval, subject),
        )

    def edit_body(
        self,
        session: JobApplicationSession,
        body: str,
    ) -> JobApplicationSession:
        return replace(
            session,
            approval=self._approval_workflow.edit_body(session.approval, body),
        )

    def edit_company(
        self,
        session: JobApplicationSession,
        company_name: str,
    ) -> JobApplicationSession:
        request = replace(
            session.request,
            company_name=validate_text(
                company_name,
                field_name="Company name",
                max_length=MAX_COMPANY_NAME_LENGTH,
            ),
        )
        return self._replace_request_and_analysis(session, request)

    def edit_role(
        self,
        session: JobApplicationSession,
        role: str,
    ) -> JobApplicationSession:
        request = replace(
            session.request,
            role=validate_text(
                role,
                field_name="Role",
                max_length=MAX_ROLE_LENGTH,
            ),
        )
        return self._replace_request_and_analysis(session, request)

    def edit_job_description(
        self,
        session: JobApplicationSession,
        job_description: str,
    ) -> JobApplicationSession:
        request = replace(
            session.request,
            job_description=validate_text(
                job_description,
                field_name="Job description",
                max_length=MAX_JOB_DESCRIPTION_LENGTH,
            ),
        )
        return self._replace_request_and_analysis(session, request)

    async def approve(
        self,
        session: JobApplicationSession,
    ) -> JobApplicationApprovalOutcome:
        outcome: ApprovalOutcome = await self._approval_workflow.approve(
            session.approval
        )
        LOGGER.info("Job application approved")
        return JobApplicationApprovalOutcome(
            session=replace(session, approval=outcome.session),
            result=outcome.result,
            duplicate=outcome.duplicate,
        )

    def cancel(self, session: JobApplicationSession | None = None) -> None:
        self._approval_workflow.cancel(session.approval if session else None)
        LOGGER.info("Job application workflow cancelled")

    def _replace_request_and_analysis(
        self,
        session: JobApplicationSession,
        request: JobApplicationRequest,
    ) -> JobApplicationSession:
        requirements, match_result = self._analyze(request, session.profile)
        return replace(
            session,
            request=request,
            requirements=requirements,
            match_result=match_result,
        )

    def _analyze(
        self,
        request: JobApplicationRequest,
        profile: CandidateProfile,
    ) -> tuple[JobRequirements, RequirementMatchResult]:
        requirements = self._requirement_extractor.extract(request.job_description)
        match_result = self._matcher.match(profile, requirements)
        return requirements, match_result

    @staticmethod
    def _with_attachment(
        approval: GeneralEmailSession,
        attachment: EmailAttachment,
    ) -> GeneralEmailSession:
        return replace(
            approval,
            draft=replace(
                approval.draft,
                attachments=(attachment.file_path,),
                status=EmailStatus.PREVIEWED,
            ),
        )

    @staticmethod
    def _validate_request(request: JobApplicationRequest) -> JobApplicationRequest:
        return JobApplicationRequest(
            company_email=validate_email(request.company_email),
            company_name=validate_text(
                request.company_name,
                field_name="Company name",
                max_length=MAX_COMPANY_NAME_LENGTH,
            ),
            role=validate_text(
                request.role,
                field_name="Role",
                max_length=MAX_ROLE_LENGTH,
            ),
            job_description=validate_text(
                request.job_description,
                field_name="Job description",
                max_length=MAX_JOB_DESCRIPTION_LENGTH,
            ),
        )
