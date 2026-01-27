from pydantic import BaseModel
from typing import List, Optional

class Metadata(BaseModel):
    semester: str
    branch: str

class Event(BaseModel):
    summary: str
    day: str
    # Changed from datetime to str to accept "HH:MM" format directly
    start_time: str
    end_time: str
    type: Optional[str] = "static"
    description: Optional[str] = ""

class TimetableResponse(BaseModel):
    metadata: Metadata
    events: List[Event]