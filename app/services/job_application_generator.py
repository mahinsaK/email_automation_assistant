"""Specialized truthful job application email generation strategies."""

from __future__ import annotations

import logging
import re
from typing import Protocol

from pydantic import ValidationError

from app.models.email import EmailDraft, EmailTone
from app.models.job_application import (
    CandidateProfile,
    JobApplicationRequest,
    JobRequirements,
    RequirementMatchResult,
)
from app.prompts.job_application import build_job_application_prompts
from app.services.ai.base import (
    AIProviderError,
    AIResponseValidationError,
    LLMProvider,
)
from app.services.ai.models import AIEmailOutput
from app.services.user_email_generator import UserAIProviderResolver


LOGGER = logging.getLogger(__name__)


class JobApplicationEmailGenerator(Protocol):
    """Generate an application draft from grounded job and candidate data."""

    async def generate(
        self,
        *,
        request: JobApplicationRequest,
        profile: CandidateProfile,
        requirements: JobRequirements,
        match_result: RequirementMatchResult,
        tone: EmailTone,
    ) -> EmailDraft:
        ...


class DeterministicJobApplicationGenerator:
    """Create a predictable application using matched profile facts only."""

    async def generate(
        self,
        *,
        request: JobApplicationRequest,
        profile: CandidateProfile,
        requirements: JobRequirements,
        match_result: RequirementMatchResult,
        tone: EmailTone,
    ) -> EmailDraft:
        subject = f"Application for {request.role} – {profile.name}"
        greeting = f"Dear {request.company_name} Hiring Team,"
        introduction = (
            f"I am writing to apply for the {request.role} position at "
            f"{request.company_name}."
        )
        if match_result.matched_skills:
            skills = ", ".join(match_result.matched_skills)
            qualification = (
                f"My background includes {skills}, which are relevant to this role."
            )
        else:
            qualification = (
                "I am interested in the opportunity and in contributing while "
                "continuing to develop professionally."
            )

        project_text = ""
        if match_result.relevant_projects:
            names = ", ".join(project.name for project in match_result.relevant_projects)
            project_text = f" I have applied related skills in {names}."

        education_text = ""
        if profile.education:
            education = profile.education[0]
            education_text = (
                f" I am pursuing or have completed {education.degree} at "
                f"{education.institution}."
            )

        closing = (
            "Thank you for considering my application. My CV is attached for "
            "your review, and I would welcome the opportunity to discuss my fit."
        )
        signoff = "Sincerely" if tone is EmailTone.FORMAL else "Best regards"
        body = (
            f"{greeting}\n\n{introduction}\n\n{qualification}{project_text}"
            f"{education_text}\n\n{closing}\n\n{signoff},\n{profile.name}"
        )
        return EmailDraft(
            recipient=request.company_email,
            subject=subject,
            body=body,
        )


class AIJobApplicationGenerator:
    """Generate validated grounded output with deterministic resilience."""

    def __init__(
        self,
        provider: LLMProvider,
        fallback: JobApplicationEmailGenerator,
    ) -> None:
        self._provider = provider
        self._fallback = fallback

    async def generate(
        self,
        *,
        request: JobApplicationRequest,
        profile: CandidateProfile,
        requirements: JobRequirements,
        match_result: RequirementMatchResult,
        tone: EmailTone,
    ) -> EmailDraft:
        system_prompt, user_prompt = build_job_application_prompts(
            request=request,
            profile=profile,
            requirements=requirements,
            match_result=match_result,
            tone=tone,
        )
        try:
            raw_response = await self._provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=AIEmailOutput,
            )
            output = self._validate_response(raw_response, match_result)
        except (AIProviderError, AIResponseValidationError):
            LOGGER.warning("AI job application generation failed, fallback used")
            return await self._fallback.generate(
                request=request,
                profile=profile,
                requirements=requirements,
                match_result=match_result,
                tone=tone,
            )

        LOGGER.info("AI job application draft generated")
        return EmailDraft(
            recipient=request.company_email,
            subject=output.subject,
            body=output.body,
        )

    @staticmethod
    def _validate_response(
        raw_response: str,
        match_result: RequirementMatchResult,
    ) -> AIEmailOutput:
        try:
            output = AIEmailOutput.model_validate_json(raw_response)
        except (ValidationError, ValueError, TypeError) as error:
            raise AIResponseValidationError(
                "The AI response did not match the email schema."
            ) from error

        generated_text = f" {output.subject} {output.body} ".casefold()
        for unmatched_skill in match_result.unmatched_skills:
            pattern = rf"(?<!\w){re.escape(unmatched_skill.casefold())}(?!\w)"
            if re.search(pattern, generated_text):
                raise AIResponseValidationError(
                    "The AI response mentioned an unsupported job requirement."
                )
        return output


class UserJobApplicationGeneratorResolver(Protocol):
    """Resolve specialized job generators for one application user."""

    async def is_available(self, user_id: int) -> bool:
        ...

    async def resolve(
        self,
        user_id: int,
    ) -> JobApplicationEmailGenerator | None:
        ...


class ConfiguredUserJobApplicationGeneratorResolver:
    """Adapt the shared per-user provider resolver to job generation."""

    def __init__(
        self,
        *,
        provider_resolver: UserAIProviderResolver,
        fallback: JobApplicationEmailGenerator | None = None,
    ) -> None:
        self._provider_resolver = provider_resolver
        self._fallback = fallback or DeterministicJobApplicationGenerator()

    async def is_available(self, user_id: int) -> bool:
        return await self._provider_resolver.is_available(user_id)

    async def resolve(
        self,
        user_id: int,
    ) -> JobApplicationEmailGenerator | None:
        provider = await self._provider_resolver.resolve(user_id)
        if provider is None:
            return None
        return AIJobApplicationGenerator(provider=provider, fallback=self._fallback)
