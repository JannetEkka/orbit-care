"""Request bodies. Every field is bounded, so no unchecked text reaches storage."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .summary import NOTE_TAGS

Role = Literal["family", "caretaker", "doctor", "elder"]
Colour = Literal["white", "yellow", "pink", "blue", "green", "orange"]
NoteTag = Literal[NOTE_TAGS]  # type: ignore[valid-type]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Clock = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^(\+?[0-9][0-9 ()-]{2,19})?$")]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, max_length=254, pattern=r"^([^@\s<>,;]{1,64}@[^@\s<>,;]+\.[^@\s<>,;]{2,})?$"
    ),
]
Passcode = Annotated[str, StringConstraints(pattern=r"^\d{6,12}$")]
DocId = Annotated[str, StringConstraints(pattern=r"^[a-z]{1,4}_[0-9a-f]{12}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(Strict):
    orbit_code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9]{8}$")]
    passcode: Passcode


class CreateOrbitIn(Strict):
    elder_name: Name
    your_name: Name
    your_email: Email = ""
    passcode: Passcode


class SlotIn(Strict):
    time: Clock
    giver_id: DocId | None = None


class MedicineIn(Strict):
    name: Name
    dose: Short = ""
    instructions: Short = ""
    slots: list[SlotIn] = Field(min_length=1, max_length=8)
    stock: int | None = Field(default=None, ge=0, le=10000)
    per_dose: int = Field(default=1, ge=1, le=20)
    colour: Colour = "white"
    active: bool = True


class AppointmentIn(Strict):
    doctor: Name
    purpose: Short = ""
    when: datetime
    clinic_phone: Phone = ""
    accompany_id: DocId | None = None
    repeat_days: int | None = Field(default=None, ge=1, le=730)


class MemberIn(Strict):
    name: Name
    role: Role
    email: Email = ""
    phone: Phone = ""
    passcode: Passcode | None = None
    digest: bool = True


class MarkIn(Strict):
    status: Literal["given", "skipped"]
    reason: Short = ""


class NoteIn(Strict):
    text: Text = ""
    tags: list[NoteTag] = Field(default_factory=list, max_length=8)


class FeelingIn(Strict):
    value: Literal["good", "not_good"]


class AboutIn(Strict):
    address_as: Short = ""
    likes: Text = ""
    calms: Text = ""
    notes: Text = ""


class ContactsIn(Strict):
    chemist_name: Short = ""
    chemist_phone: Phone = ""
    hospital_name: Short = ""
    hospital_phone: Phone = ""
    doctor_name: Short = ""
    doctor_phone: Phone = ""
    doctor_email: Email = ""
    ambulance_phone: Phone = "108"


class RulesIn(Strict):
    upcoming_lead_min: int = Field(default=15, ge=5, le=120)
    missed_after_min: int = Field(default=30, ge=5, le=240)
    escalate_after_min: int = Field(default=60, ge=10, le=480)
    refill_warn_days: int = Field(default=5, ge=1, le=30)


class ProfileIn(Strict):
    elder_name: Name
    about: AboutIn = Field(default_factory=AboutIn)
    contacts: ContactsIn = Field(default_factory=ContactsIn)
    settings: RulesIn = Field(default_factory=RulesIn)


class DoctorRequestIn(Strict):
    kind: Literal["call", "visit"]
    message: Short = ""
