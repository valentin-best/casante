from datetime import date as date_type
from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    DISCHARGE_SUMMARY = "discharge_summary"
    CLINIC_LETTER = "clinic_letter"
    LAB_REPORT = "lab_report"
    PRESCRIPTION = "prescription"
    OTHER = "other"


class MedicationStatus(str, Enum):
    ACTIVE = "active"
    STOPPED = "stopped"
    CHANGED = "changed"
    UNKNOWN = "unknown"


class AllergySeverity(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"
    UNKNOWN = "unknown"


class ConditionStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class LabFlag(str, Enum):
    HIGH = "high"
    LOW = "low"
    NORMAL = "normal"


class Document(BaseModel):
    type: DocumentType = Field(..., description="Type of the document")
    provider: str | None = Field(None, description="Provider of the document")
    date: date_type | None = Field(
        None, description="Date of the document in YYYY-MM-DD format"
    )


class Medication(BaseModel):
    name: str = Field(..., description="Name of the medication")
    dose: str | None = Field(None, description="Dose of the medication")
    route: str | None = Field(None, description="Route of administration")
    frequency: str | None = Field(None, description="Frequency of administration")
    status: MedicationStatus | None = Field(
        None,
        description="Status of the medication",
    )
    start_date: date_type | None = Field(
        None, description="Start date of the medication in YYYY-MM-DD format"
    )

    stop_date: date_type | None = Field(
        None, description="Stop date of the medication in YYYY-MM-DD format"
    )
    evidence: list[str] = Field(
        ..., description="List of evidence references for the medication"
    )


class Allergy(BaseModel):
    substance: str = Field(..., description="Substance causing the allergy")
    reaction: str | None = Field(None, description="Reaction to the allergen")
    severity: AllergySeverity | None = Field(
        None,
        description="Severity of the allergic reaction",
    )
    evidence: list[str] = Field(
        ..., description="List of evidence references for the allergy"
    )


class Condition(BaseModel):
    name: str = Field(..., description="Name of the condition")
    status: ConditionStatus | None = Field(
        None,
        description="Status of the condition",
    )
    onset_date: date_type | None = Field(
        None, description="Onset date of the condition in YYYY-MM-DD format"
    )
    evidence: list[str] = Field(
        ..., description="List of evidence references for the condition"
    )


class Lab(BaseModel):
    test: str = Field(..., description="Name of the lab test")
    value: float | None = Field(None, description="Value of the lab test")
    unit: str | None = Field(None, description="Unit of the lab test value")
    reference_range: str | None = Field(
        None, description="Reference range for the lab test"
    )
    flag: LabFlag | None = Field(
        None,
        description="Flag indicating if the result is high, low, or normal",
    )
    date: date_type | None = Field(
        None, description="Date of the lab test in YYYY-MM-DD format"
    )
    evidence: list[str] = Field(
        ..., description="List of evidence references for the lab test"
    )


class Procedure(BaseModel):
    name: str = Field(..., description="Name of the procedure")
    date: date_type | None = Field(
        None, description="Date of the procedure in YYYY-MM-DD format"
    )
    evidence: list[str] = Field(
        ..., description="List of evidence references for the procedure"
    )
