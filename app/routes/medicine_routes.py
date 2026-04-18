"""
Medicine CRUD routes + prescription image upload.
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from app.schemas.medicine_schemas import MedicineCreate, MedicineUpdate, MedicineOut
from app.services import medicine_service
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/medicines", tags=["Medicines"])


@router.post(
    "/manual",
    response_model=MedicineOut,
    status_code=201,
    summary="Add a medicine manually",
)
async def add_manual(
    body: MedicineCreate,
    current_user: dict = Depends(get_current_user),
):
    return await medicine_service.create_medicine(current_user["id"], body)


@router.post(
    "/from-image",
    response_model=MedicineOut,
    status_code=201,
    summary="Add a medicine by scanning a prescription image",
)
async def add_from_image(
    file: UploadFile = File(..., description="Prescription image (JPEG / PNG)"),
    current_user: dict = Depends(get_current_user),
):
    """
    Upload a prescription image.  The backend runs OCR (Tesseract) to extract
    medicine name, dosage, and frequency.  The result is saved to MongoDB and
    returned.  Fields can be corrected with PUT /medicines/{id}.
    """
    return await medicine_service.create_medicine_from_image(current_user["id"], file)


@router.get(
    "",
    response_model=list[MedicineOut],
    summary="List all medicines for the current user",
)
async def list_medicines(current_user: dict = Depends(get_current_user)):
    return await medicine_service.list_medicines(current_user["id"])


@router.get(
    "/{medicine_id}",
    response_model=MedicineOut,
    summary="Get a single medicine by ID",
)
async def get_medicine(
    medicine_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await medicine_service.get_medicine(current_user["id"], medicine_id)


@router.put(
    "/{medicine_id}",
    response_model=MedicineOut,
    summary="Update a medicine",
)
async def update_medicine(
    medicine_id: str,
    body: MedicineUpdate,
    current_user: dict = Depends(get_current_user),
):
    return await medicine_service.update_medicine(current_user["id"], medicine_id, body)


@router.delete(
    "/{medicine_id}",
    summary="Delete a medicine",
    status_code=200,
)
async def delete_medicine(
    medicine_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await medicine_service.delete_medicine(current_user["id"], medicine_id)
