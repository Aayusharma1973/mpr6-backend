from pydantic import BaseModel, Field
from typing import List, Optional, Any
from datetime import datetime
import uuid

class AIMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str # AI generated text (Markdown supported)
    sender: str = "assistant"
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class AIResponse(BaseModel):
    """Unified response for all 3 AI routes"""
    bot_message: AIMessage

class InteractionAlertRequest(BaseModel):
    new_medicine: dict
    user_profile: dict  # allergies, blood group
    current_medications: List[dict]

class AISuggestionsRequest(BaseModel):
    user_profile: dict
    full_medication_list: List[dict]

class AIInsightsRequest(BaseModel):
    weekly_tracking_history: List[dict]
    medication_list: List[dict]

class SideEffectsRequest(BaseModel):
    medicine: dict  # name, dosage, instructions
