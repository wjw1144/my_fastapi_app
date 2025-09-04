# app/schemas/update_file.py
from pydantic import BaseModel
from typing import List

class FileContentItem(BaseModel):
    path: str
    content: str

class UpdateFileFullRequest(BaseModel):
    files: List[FileContentItem]

class UpdateFileRequest(BaseModel):
    mcc: str
    mnc: str
    file_paths: List[str]
