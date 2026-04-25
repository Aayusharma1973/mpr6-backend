from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.ai_schemas import (
    AIResponse,
    AIMessage,
    InteractionAlertRequest,
    AISuggestionsRequest,
    AIInsightsRequest,
    SideEffectsRequest
)
from app.ai.agent_service import (
    generate_interaction_alert,
    generate_ai_suggestions,
    generate_ai_insights,
    generate_side_effects
)
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/ai", tags=["AI Insights"])

@router.post("/interaction-alert", response_model=AIResponse, summary="Check for medicine interactions")
async def interaction_alert(
    body: InteractionAlertRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Check if the new_medicine is safe. If not, suggest a generic alternative.
    """
    context = body.model_dump()
    message_text = await generate_interaction_alert(context)
    
    return AIResponse(
        bot_message=AIMessage(message=message_text)
    )

@router.post("/suggestions", response_model=AIResponse, summary="Get AI suggestions for medication")
async def ai_suggestions(
    body: AISuggestionsRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Provide 3 tips for better results (bioavailability and timing).
    """
    context = body.model_dump()
    message_text = await generate_ai_suggestions(context)
    
    return AIResponse(
        bot_message=AIMessage(message=message_text)
    )

@router.post("/insights", response_model=AIResponse, summary="Get AI insights based on tracking history")
async def ai_insights(
    body: AIInsightsRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Predict the next missed dose based on tracking history.
    """
    context = body.model_dump()
    message_text = await generate_ai_insights(context)
    
    return AIResponse(
        bot_message=AIMessage(message=message_text)
    )

@router.post("/side-effects", response_model=AIResponse, summary="Get common side effects for a medicine")
async def get_side_effects(
    body: SideEffectsRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Provide common side effects for the given medicine.
    Input Context: name, dosage, instructions.
    """
    context = body.model_dump()
    message_text = await generate_side_effects(context)
    
    return AIResponse(
        bot_message=AIMessage(message=message_text)
    )
