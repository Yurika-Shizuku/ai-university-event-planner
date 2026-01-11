from pydantic import BaseModel
from typing import List, Optional

class Event(BaseModel):
    summary: str
    day: str
    # Changed from datetime to str to accept "HH:MM" format directly
    start_time: str
    end_time: str
    description: Optional[str] = ""

class TimetableResponse(BaseModel):
    events: List[Event]