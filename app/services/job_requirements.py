"""Deterministic job-requirement extraction and candidate matching."""

from __future__ import annotations

import logging
import re

from app.models.job_application import (
    CandidateProfile,
    JobRequirements,
    RequirementMatchResult,
)


LOGGER = logging.getLogger(__name__)

_SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "Java": ("java",),
    "Spring Boot": ("spring boot",),
    "SQL": ("sql",),
    "REST APIs": ("rest api", "restful api"),
    "Git": ("git",),
    "React": ("react", "react.js", "reactjs"),
    "AWS": ("aws", "amazon web services"),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "PyTorch": ("pytorch",),
    "JavaScript": ("javascript",),
    "TypeScript": ("typescript",),
    "Node.js": ("node.js", "nodejs"),
}
_PREFERRED_MARKERS = ("preferred", "nice to have", "bonus", "desirable")


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class DeterministicJobRequirementExtractor:
    """Extract a small explicit skill catalogue from untrusted job text."""

    def extract(self, job_description: str) -> JobRequirements:
        segments = [
            segment.strip()
            for segment in re.split(r"[\n.!;]+", job_description)
            if segment.strip()
        ]
        required: list[str] = []
        preferred: list[str] = []
        for canonical, aliases in _SKILL_ALIASES.items():
            for segment in segments:
                normalized_segment = _normalized(segment)
                if any(
                    f" {_normalized(alias)} " in f" {normalized_segment} "
                    for alias in aliases
                ):
                    target = (
                        preferred
                        if any(marker in normalized_segment for marker in _PREFERRED_MARKERS)
                        else required
                    )
                    if canonical not in target:
                        target.append(canonical)
                    break
        LOGGER.info("Job requirements extracted")
        return JobRequirements(
            required_skills=tuple(required),
            preferred_skills=tuple(preferred),
        )


class CandidateRequirementMatcher:
    """Match only explicit profile skills and project technologies."""

    def match(
        self,
        profile: CandidateProfile,
        requirements: JobRequirements,
    ) -> RequirementMatchResult:
        profile_skills = {_normalized(skill): skill for skill in profile.skills}
        for project in profile.projects:
            profile_skills.update(
                {_normalized(skill): skill for skill in project.technologies}
            )
        for experience in profile.experience:
            profile_skills.update(
                {_normalized(skill): skill for skill in experience.skills}
            )

        all_requirements = (
            requirements.required_skills + requirements.preferred_skills
        )
        matched: list[str] = []
        unmatched: list[str] = []
        for requirement in all_requirements:
            normalized_requirement = _normalized(requirement)
            profile_value = profile_skills.get(normalized_requirement)
            if profile_value is not None:
                matched.append(profile_value)
            else:
                unmatched.append(requirement)

        matched_normalized = {_normalized(skill) for skill in matched}
        relevant_projects = tuple(
            project
            for project in profile.projects
            if matched_normalized.intersection(
                {_normalized(skill) for skill in project.technologies}
            )
        )
        LOGGER.info("Candidate requirements matched")
        return RequirementMatchResult(
            matched_skills=tuple(matched),
            unmatched_skills=tuple(unmatched),
            relevant_projects=relevant_projects,
        )
