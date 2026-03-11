from fastapi import APIRouter, UploadFile, File

router = APIRouter()

@router.get("/")
def health():
    return {"status": "ok"}

@router.post("/pixelize")
async def pixelize(file: UploadFile = File(...)):
    return {
        "filename": file.filename
    }