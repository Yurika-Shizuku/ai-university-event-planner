import os
import datetime
from google import genai
from google.genai import types
from core.calendar_api import CalendarAPI
from dotenv import load_dotenv

load_dotenv()


class SchedulingAgent:
    def __init__(self):
        # Initialize the Unified 2026 SDK Client
        self.client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        self.cal = CalendarAPI()

        # Tools list: registered functions that Gemini can call
        self.tools = [
            self.check_availability,
            self.book_temporary_event,
            self.cancel_event
        ]

    def check_availability(self, start_iso: str, end_iso: str) -> str:
        """
        Checks if a time slot is free in the primary calendar.
        Args:
            start_iso: Start time in ISO 8601 (e.g., '2026-01-10T14:00:00Z').
            end_iso: End time in ISO 8601.
        """
        conflicts = self.cal.check_conflicts(start_iso, end_iso)
        if not conflicts:
            return "The slot is available in the calendar."

        return f"Conflict detected! These slots are busy: {conflicts}. Suggest an alternative."

    def book_temporary_event(
            self,
            summary: str,
            start_iso: str,
            end_iso: str,
            semester: str | None = None,
            branch: str | None = None
    ) -> str:
        """
        Creates a TEMPORARY event after validating against STATIC timetable.
        """

        # 🔒 Final safety check
        conflicts = self.cal.check_conflicts(start_iso, end_iso)
        if conflicts:
            return "❌ Cannot book. This time clashes with an existing timetable or event."

        description_parts = []
        if semester:
            description_parts.append(f"Semester: {semester}")
        if branch:
            description_parts.append(f"Branch: {branch}")

        description = " | ".join(description_parts)

        try:
            # Ensure create_event in calendar_api supports these extra arguments
            event = self.cal.create_event(
                calendar_type="temp",
                summary=f"[Temp] {summary}",
                start_time=start_iso,
                end_time=end_iso,
                description=description

            )

            if not event:
                return "❌ Failed to create event due to calendar error."

            return f"✅ Event '{summary}' scheduled successfully."

        except Exception as e:
            return f"❌ Temporary booking failed: {e}"

    def cancel_event(self, event_id: str) -> str:
        """
        Cancels an event only if it's within the 48-hour booking window.
        Args:
            event_id: The unique ID of the Google Calendar event.
        """
        try:
            # Fetch event to check retention policy
            event = self.cal.service.events().get(
                calendarId=self.cal.temp_cal_id,
                eventId=event_id
            ).execute()

            created_str = event.get('created')
            created_dt = datetime.datetime.fromisoformat(created_str.replace('Z', '+00:00'))
            now = datetime.datetime.now(datetime.timezone.utc)

            # Enforce 48-hour cancellation rule
            if (now - created_dt).total_seconds() > 172800:
                return "Cancellation denied. The 48-hour free cancellation window has passed."

            self.cal.service.events().delete(
                calendarId=self.cal.temp_cal_id,
                eventId=event_id
            ).execute()
            return "Event successfully removed from your calendar."

        except Exception as e:
            return f"Error during cancellation: {str(e)}"

    def get_chat_session(self):
        """Initializes the Gemini 2026 chat session with tool integration."""
        instruction = (
            "You are a University Event Planner assistant.\n"
            "- ALWAYS use 'check_availability' before booking.\n"
            "- Use 'book_temporary_event' for club or extra events.\n"
            "- When booking, you can optionally include 'semester' and 'branch' if known.\n"
            "- NEVER book over 'Static' semester timetable slots.\n"
            "- All times are in 'Asia/Kolkata' timezone."
            "- If a conflict exists, suggest the nearest free slot."
        )

        # Use the 2026 Unified SDK chat initialization
        return self.client.chats.create(
            model="models/gemini-flash-latest",
            config=types.GenerateContentConfig(
                tools=self.tools,
                system_instruction=instruction
            )
        )