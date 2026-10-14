"""Load and validate the local candidate profile source of truth."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.models.job_application import (
    CandidateProfile,
    Certification,
    Education,
    Experience,
    Project,
)
from app.services.validation import InputValidationError, validate_email, validate_text


LOGGER = logging.getLogger(__name__)
MAX_PROFILE_FILE_BYTES = 1_000_000
MAX_PROFILE_TEXT_LENGTH = 4_000


class CandidateProfileError(RuntimeError):
    """Raised when the configured candidate profile cannot be safely loaded."""


class CandidateProfileService:
    """Read a validated immutable profile from a configurable JSON file."""

    def __init__(self, profile_path: str | Path) -> None:
        self._profile_path = Path(profile_path)

    async def get_profile(self) -> CandidateProfile:
        try:
            profile = await asyncio.to_thread(self._load_sync)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            LOGGER.warning("Candidate profile unavailable")
            raise CandidateProfileError(
                "Candidate profile is missing or invalid."
            ) from error
        LOGGER.info("Candidate profile loaded")
        return profile

    def _load_sync(self) -> CandidateProfile:
        if not self._profile_path.is_file():
            raise OSError("Candidate profile file does not exist.")
        if self._profile_path.stat().st_size > MAX_PROFILE_FILE_BYTES:
            raise ValueError("Candidate profile file is too large.")
        with self._profile_path.open("r", encoding="utf-8") as profile_file:
            data = json.load(profile_file)
        if not isinstance(data, dict):
            raise TypeError("Candidate profile root must be an object.")
        return self._parse_profile(data)

    @classmethod
    def _parse_profile(cls, data: dict[str, Any]) -> CandidateProfile:
        email = cls._optional_text(data.get("email"), "Candidate email")
        if email is not None:
            email = validate_email(email)
        return CandidateProfile(
            name=cls._required_text(data.get("name"), "Candidate name"),
            email=email,
            phone=cls._optional_text(data.get("phone"), "Candidate phone"),
            location=cls._optional_text(
                data.get("location"),
                "Candidate location",
            ),
            summary=cls._optional_text(data.get("summary"), "Candidate summary"),
            education=tuple(
                cls._parse_education(item)
                for item in cls._object_list(data.get("education", []), "education")
            ),
            skills=cls._string_tuple(data.get("skills", []), "skills"),
            projects=tuple(
                cls._parse_project(item)
                for item in cls._object_list(data.get("projects", []), "projects")
            ),
            experience=tuple(
                cls._parse_experience(item)
                for item in cls._object_list(data.get("experience", []), "experience")
            ),
            certifications=tuple(
                cls._parse_certification(item)
                for item in cls._object_list(
                    data.get("certifications", []),
                    "certifications",
                )
            ),
            achievements=cls._string_tuple(
                data.get("achievements", []),
                "achievements",
            ),
        )

    @classmethod
    def _parse_education(cls, data: dict[str, Any]) -> Education:
        year = data.get("graduation_year")
        if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
            raise TypeError("graduation_year must be an integer or null.")
        return Education(
            degree=cls._required_text(data.get("degree"), "Education degree"),
            institution=cls._required_text(
                data.get("institution"),
                "Education institution",
            ),
            graduation_year=year,
        )

    @classmethod
    def _parse_project(cls, data: dict[str, Any]) -> Project:
        return Project(
            name=cls._required_text(data.get("name"), "Project name"),
            description=cls._optional_text(
                data.get("description"),
                "Project description",
            ),
            technologies=cls._string_tuple(
                data.get("technologies", []),
                "project technologies",
            ),
        )

    @classmethod
    def _parse_experience(cls, data: dict[str, Any]) -> Experience:
        return Experience(
            title=cls._required_text(data.get("title"), "Experience title"),
            organization=cls._required_text(
                data.get("organization"),
                "Experience organization",
            ),
            description=cls._optional_text(
                data.get("description"),
                "Experience description",
            ),
            skills=cls._string_tuple(
                data.get("skills", []),
                "experience skills",
            ),
        )

    @classmethod
    def _parse_certification(cls, data: dict[str, Any]) -> Certification:
        return Certification(
            name=cls._required_text(data.get("name"), "Certification name"),
            issuer=cls._optional_text(data.get("issuer"), "Certification issuer"),
        )

    @staticmethod
    def _object_list(value: Any, field_name: str) -> list[dict[str, Any]]:
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise TypeError(f"{field_name} must be an array of objects.")
        return value

    @classmethod
    def _string_tuple(cls, value: Any, field_name: str) -> tuple[str, ...]:
        if not isinstance(value, list):
            raise TypeError(f"{field_name} must be an array of strings.")
        return tuple(cls._required_text(item, field_name) for item in value)

    @staticmethod
    def _required_text(value: Any, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name} must be text.")
        try:
            return validate_text(
                value,
                field_name=field_name,
                max_length=MAX_PROFILE_TEXT_LENGTH,
            )
        except InputValidationError as error:
            raise ValueError(str(error)) from error

    @classmethod
    def _optional_text(cls, value: Any, field_name: str) -> str | None:
        if value is None:
            return None
        return cls._required_text(value, field_name)
