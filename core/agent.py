import os
import datetime
import json
import pytz
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

        # FIX 1: Load Admin Emails for Privileged Access
        # Supports JSON list ["a@b.com", "c@d.com"] or comma-separated string
        admin_env = os.getenv("ADMIN_EMAILS", "")
        self.admins = []
        if admin_env:
            try:
                if "[" in admin_env:
                    self.admins = json.loads(admin_env)
                else:
                    self.admins = [e.strip() for e in admin_env.split(",") if e.strip()]
            except Exception:
                self.admins = []

        # Tools list: registered functions that Gemini can call
        self.tools = [
            self.check_availability,
            self.book_temporary_event,
            self.cancel_event,
            self.get_alternative_slots
        ]

    def check_availability(self, start_iso: str, end_iso: str, target_semesters: str | list = "All",valid_weekdays: list = None) -> str:
        """
        Checks if a time slot is free across static + temp calendars based on semester.
        Provides detailed clash info for Problem 4.
        """
        conflicts = self.cal.check_conflicts(start_iso, end_iso, target_semesters)

        if not conflicts:
            return "SUCCESS: The slot is available for the specified semester(s)."

        # FIX 2: Ensure conflict details are returned clearly to the LLM
        conflict_list = "\n- ".join(conflicts)
        # --- ADDED BLOCK START: Calculate duration and fetch suggestions immediately ---
        try:
            s_dt = datetime.datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
            e_dt = datetime.datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
            duration = int((e_dt - s_dt).total_seconds() / 60)
        except:
            duration = 60  # Default fallback

        # Call get_alternative_slots internally, passing the weekday constraints
        suggestions_text = self.get_alternative_slots(start_iso, duration, target_semesters, valid_weekdays)
        # --- ADDED BLOCK END ---------------------------------------------------------
        return (
            f"❌ CONFLICT DETECTED. You cannot book this slot.\n"
            f"Clashing Details:\n- {conflict_list}\n\n"
            #f"{suggestions_text}"
        )

    def get_alternative_slots(self, start_iso: str, duration_minutes: int, target_semesters: str | list = "All",valid_weekdays: list = None) -> str:
        """
        Suggests exactly 2 alternative slots within college hours (09:00-16:00).
        Supports Problem 2 requirement for structured suggestions.
        """
        # Ensure duration is an integer for the API
        duration = int(duration_minutes)
        suggestions = self.cal.get_suggestions(start_iso, duration, target_semesters,valid_weekdays)

        if not suggestions:
            return "No available slots found within the next 7 days during college hours (09:00-16:00)."

        resp = "SUGGESTED SLOTS (Select one):\n"
        for i, s in enumerate(suggestions[:2], 1):  # Strictly enforce top 2 suggestions
            resp += f"\nOption {i}: {s['display']}\n   - Start: {s['start']}\n   - End: {s['end']}\n"

        return resp

    def book_temporary_event(
            self,
            summary: str,
            start_iso: str,
            end_iso: str,
            target_semesters: str | list = "All",
            creator_email: str = None  # NEW: Feature 4 (Ownership)
    ) -> str:
        """
        Creates a TEMPORARY event after validating against STATIC timetable for specific semesters.
        Injects Semester metadata and Creator Identity.
        """
        # 🔒 Final safety check (Semester-aware)
        # FIX 2: Critical Check - Blocks booking if ANY conflict exists
        conflicts = self.cal.check_conflicts(start_iso, end_iso, target_semesters)
        if conflicts:
            return f"❌ BOOKING REJECTED: Slot is no longer available due to: {', '.join(conflicts)}"

        # Prepare description with semester info for future conflict checks (Problem 3)
        if isinstance(target_semesters, list):
            sem_meta = ", ".join(target_semesters)
        else:
            sem_meta = target_semesters

        description = f"Semester: {sem_meta}"

        try:
            event = self.cal.create_event(
                calendar_type="temp",
                summary=f"[Temp] {summary}",
                start_time=start_iso,
                end_time=end_iso,
                description=description,
                creator_email=creator_email  # Pass email to API
            )

            if not event:
                return "❌ Error: Google Calendar failed to create the event."

            return f"✅ SUCCESS: '{summary}' scheduled for {sem_meta}."

        except Exception as e:
            return f"❌ Error: {e}"

    def cancel_event(self, event_id: str, requester_email: str = None) -> str:
        """
        Cancels an event if:
        1. It is within the 48-hour booking window.
        2. The requester matches the creator (Feature 4) OR IS AN ADMIN.
        """
        try:
            # Fetch event details using the helper added to CalendarAPI
            event = self.cal.get_event("temp", event_id)
            if not event:
                return "❌ Error: Event not found."

            # 1. Check 48-Hour Rule
            created_str = event.get("created")
            # Parse creation time (handled as UTC by Google)
            created_dt = datetime.datetime.fromisoformat(
                created_str.replace("Z", "+00:00")
            )
            now = datetime.datetime.now(datetime.timezone.utc)

            hours_diff = (now - created_dt).total_seconds() / 3600

            if hours_diff > 48:
                return f"❌ Cancellation denied. The 48-hour window has passed (Event created {int(hours_diff)} hours ago)."

            # 2. Check Ownership Rule (Feature 4)
            # FIX 1: Admin Override Logic
            # Admins can cancel ANY event. Users can only cancel THEIR OWN events.
            is_admin = requester_email in self.admins

            if requester_email and not is_admin:
                extended_props = event.get("extendedProperties", {}).get("shared", {})
                creator = extended_props.get("creator_email", "system")

                if requester_email != creator and creator != "system":
                    return f"❌ Permission Denied. This event was created by {creator}."

            # Proceed to delete
            success = self.cal.delete_event("temp", event_id)
            if success:
                return "✅ Event successfully cancelled."
            else:
                return "❌ Error: Failed to delete event."

        except Exception as e:
            return f"❌ Error during cancellation: {str(e)}"

    def get_chat_session(self):
        """
        Initializes the Gemini chat session with structured instructions for Problem 2 & 4.
        """
        instruction = (
            "SYSTEM ROLE: University Scheduling Assistant (Asia/Kolkata +05:30).\n\n"
            "OPERATING GUIDELINES:\n"
            "1. NO SMALL TALK. Do not say 'Hello' or 'I can help with that'. Go straight to information.\n"
            "2. CHECK BEFORE SUGGESTING: If a user asks for a time, call 'check_availability' immediately.\n"
            "3. HANDLING CLASHES (Problem 4): If a conflict is returned, explain it clearly (Class name, Semester, Time) "
            "and immediately call 'get_alternative_slots' to find 2 options.\n"
            "4. SUGGESTIONS (Problem 2): Provide exactly 2 suggestions if the original request fails. "
            "Present them as options for the user to choose. Do not auto-fill their dashboard.\n"
            "5. SEMESTER AWARENESS (Problem 3): Only block bookings if the conflict is for the user's TARGET semester. "
            "If they target 'Sem 3', ignore 'Sem 5' classes. If they target 'All', any class is a clash.\n"
            "6. WORKING HOURS: Never suggest or book outside 09:00 AM - 04:00 PM.\n"
            "7. TIMEZONE: Always assume Asia/Kolkata (+05:30)."
        )

        return self.client.chats.create(
            model="models/gemini-flash-latest",
            config=types.GenerateContentConfig(
                tools=self.tools,
                system_instruction=instruction,
                temperature=0.1
            )
        )