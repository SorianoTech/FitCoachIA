from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProfileUser(ProfileModel):
    name_or_username: str = Field(min_length=1)
    registration_date: datetime


class Biometrics(ProfileModel):
    age: int = Field(ge=14, le=100)
    weight_kg: float = Field(ge=30, le=300)
    height_cm: int = Field(ge=130, le=230)
    bmi: float = Field(gt=0)
    perceived_composition: str = Field(min_length=1)
    estimated_composition: str = Field(min_length=1)


class Goal(ProfileModel):
    primary: Literal["lose_fat", "gain_muscle", "performance"]
    secondary: str | None = None
    timeframe_weeks: int = Field(ge=1)
    realistic_expectation: bool


class Activity(ProfileModel):
    occupation: str = Field(min_length=1)
    neat_level: Literal["sedentary", "active", "very_physical"]
    description: str = Field(min_length=1)


class CriticalFood(ProfileModel):
    name: str = Field(min_length=1)
    frequency: str = Field(min_length=1)
    context: str = Field(min_length=1)


class Nutrition(ProfileModel):
    meals_per_day: int = Field(ge=1)
    critical_foods: list[CriticalFood]
    general_pattern: str = Field(min_length=1)


class DigestiveEnergy(ProfileModel):
    bloating_frequency: Literal["never", "sometimes", "always"]
    energy_crash: bool
    triggers: list[str]


class Injury(ProfileModel):
    location: str = Field(min_length=1)
    type: str = Field(min_length=1)
    age: str = Field(min_length=1)
    restriction: str = Field(min_length=1)
    diagnosis: str | None = None


class Training(ProfileModel):
    consistent_years: float = Field(ge=0)
    environment: Literal["gym", "home", "outdoors", "mixed"]
    equipment: list[str]


class Sleep(ProfileModel):
    average_hours: float = Field(ge=4, le=12)
    quality: Literal["poor", "fair", "good", "excellent"]
    problems: list[str]


class Supplement(ProfileModel):
    name: str = Field(min_length=1)
    dose: str = Field(min_length=1)
    frequency: str = Field(min_length=1)


class Supplementation(ProfileModel):
    current: list[Supplement]
    monthly_budget_usd: float | None = Field(default=None, ge=0)
    restrictions: list[str]


class Commitment(ProfileModel):
    days_per_week: int = Field(ge=1, le=7)
    minutes_per_session: int = Field(ge=15, le=180)
    flexibility: Literal["fixed", "flexible"]
    dropout_history: str | None = None


class Flags(ProfileModel):
    red: list[str]
    yellow: list[str]


class InitialCalculations(ProfileModel):
    bmr: float = Field(gt=0)
    estimated_tdee: float = Field(gt=0)
    tolerable_volume_sets: int = Field(ge=0)


class InterviewerProfile(ProfileModel):
    user: ProfileUser
    biometrics: Biometrics
    goal: Goal
    activity: Activity
    nutrition: Nutrition
    digestive_energy: DigestiveEnergy
    injuries: list[Injury]
    training: Training
    sleep: Sleep
    supplementation: Supplementation
    commitment: Commitment
    flags: Flags
    initial_calculations: InitialCalculations


class InterviewerTurn(ProfileModel):
    status: Literal["in_progress", "completed"]
    reply: str = Field(min_length=1)
    report: str | None = None
    profile: InterviewerProfile | None = None

    @model_validator(mode="after")
    def validate_completion(self) -> "InterviewerTurn":
        if self.status == "completed" and (self.report is None or self.profile is None):
            raise ValueError("A completed interview requires both report and profile")
        if self.status == "in_progress" and (self.report is not None or self.profile is not None):
            raise ValueError("An in-progress interview cannot include report or profile")
        return self
