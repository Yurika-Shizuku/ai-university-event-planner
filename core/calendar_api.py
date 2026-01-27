import os
import datetime
import pytz
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar']

DEFAULT_TIMEZONE = "Asia/Kolkata"

STATIC_CALENDAR_NAME = "Semester Static Calendar"
TEMP_CALENDAR_NAME = "Club Temporary Events"


class CalendarAPI:
    def __init__(self):
        """Initializes the Calendar API with 'Asia/Kolkata' defaults."""
        self.creds = self._authenticate()
        self.service = build("calendar", "v3", credentials=self.creds)
        self.timezone = DEFAULT_TIMEZONE
        self.local_tz = pytz.timezone(self.timezone)

        # FIX: calendar IDs must NEVER silently fall back to primary
        self.static_cal_id = self._get_or_create_calendar(STATIC_CALENDAR_NAME)
        self.temp_cal_id = self._get_or_create_calendar(TEMP_CALENDAR_NAME)

    @staticmethod
    def _authenticate():
        """Handles OAuth2 flow and token management."""
        creds = None

        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        return creds

    def _get_or_create_calendar(self, calendar_name):
        """
        Checks if a specific calendar exists (with pagination),
        otherwise creates it with local timezone.
        """
        try:
            page_token = None

            # FIX: handle pagination properly
            while True:
                calendar_list = self.service.calendarList().list(
                    pageToken=page_token
                ).execute()

                for entry in calendar_list.get('items', []):
                    if entry.get('summary') == calendar_name:
                        return entry['id']

                page_token = calendar_list.get('nextPageToken')
                if not page_token:
                    break

            # Not found → create
            new_calendar = {
                'summary': calendar_name,
                'timeZone': self.timezone
            }

            created_calendar = self.service.calendars().insert(
                body=new_calendar
            ).execute()

            return created_calendar['id']

        except HttpError as e:
            # FIX: never silently fall back to primary
            raise RuntimeError(
                f"❌ Failed to get or create calendar '{calendar_name}': {e}"
            )

    def check_conflicts(self, start_time, end_time, target_semesters):
        """
        Semester-Aware Conflict Checking.
        Returns a list of detailed conflict strings for the UI to explain clashes.
        FIXED: Removed unreliable freebusy check. Now explicitly lists events.
        FIXED: Corrected semester parsing logic (split by '|' instead of space).
        """
        # Strictly exclude "primary" per requirements
        calendars_to_check = [self.static_cal_id, self.temp_cal_id]
        conflict_reports = []

        try:
            for cal_id in calendars_to_check:
                # Fetch actual events to extract metadata and timings for Problem 4
                # Use singleEvents=True to expand recurrence and catch specific instances
                events_result = self.service.events().list(
                    calendarId=cal_id,
                    timeMin=start_time,
                    timeMax=end_time,
                    singleEvents=True
                ).execute()

                events = events_result.get("items", [])

                for ev in events:
                    summary = ev.get("summary", "Untitled Event")
                    description = ev.get("description", "")

                    # Parse Event Times for readable explanation
                    # Helper to safely parse ISO strings
                    start_dt_str = ev['start'].get('dateTime')
                    end_dt_str = ev['end'].get('dateTime')

                    # Skip all-day events if they don't have dateTime
                    if not start_dt_str or not end_dt_str:
                        continue

                    ev_start = datetime.datetime.fromisoformat(
                        start_dt_str.replace('Z', '+00:00')
                    ).astimezone(self.local_tz)

                    ev_end = datetime.datetime.fromisoformat(
                        end_dt_str.replace('Z', '+00:00')
                    ).astimezone(self.local_tz)

                    time_range = f"{ev_start.strftime('%I:%M %p')} - {ev_end.strftime('%I:%M %p')}"

                    if cal_id == self.temp_cal_id:
                        # Temp events (Club events) clash with everyone
                        conflict_reports.append(f"Clash with Event: {summary} ({time_range})")

                    elif cal_id == self.static_cal_id:
                        # Extract Semester: "Semester: Sem 3 | Branch: CSE"
                        event_sem = "All"
                        if "Semester:" in description:
                            try:
                                # FIXED: Split by '|' to capture full tag like "Sem 1"
                                part_after_sem = description.split("Semester:")[1]
                                if "|" in part_after_sem:
                                    event_sem = part_after_sem.split("|")[0].strip()
                                else:
                                    event_sem = part_after_sem.strip()
                            except IndexError:
                                event_sem = "All"

                        # Logic: Problem 3 - Only block if semester matches or target is "All"
                        is_clash = False
                        if target_semesters == "All" or "All" in target_semesters:
                            is_clash = True
                        else:
                            if isinstance(target_semesters, str):
                                if target_semesters == event_sem:
                                    is_clash = True
                            elif event_sem in target_semesters:
                                is_clash = True

                        if is_clash:
                            conflict_reports.append(f"Clash with Class: {summary} [{event_sem}] ({time_range})")

            return conflict_reports

        except HttpError as e:
            print(f"❌ Conflict check failed: {e}")
            return [f"Error checking conflicts: {e}"]

    def get_suggestions(self, start_iso, duration_minutes, target_semesters, valid_weekdays):
        """
        Suggests exactly 2 alternative slots based on working hours:
        - 09:00 - 15:00 (Preferred)
        - 15:00 - 16:00 (Extended buffer)
        - Checks next 7 days.
        """
        suggestions = []
        base_dt = datetime.datetime.fromisoformat(start_iso.replace('Z', '+00:00')).astimezone(self.local_tz)

        # Search over 8 days (Today + 7)
        for day_offset in range(8):
            current_day = base_dt + datetime.timedelta(days=day_offset)
            # --- [CHANGE START] Filter by specific weekdays if provided ---
            if valid_weekdays is not None:
                # If the current day (0=Mon, 6=Sun) is NOT in the allowed list, skip it.
                if current_day.weekday() not in valid_weekdays:
                    continue
            # --- [CHANGE END] ---------------------------------------------
            search_windows = [
                (9, 15),  # Preferred
                (15, 16)  # Buffer
            ]

            for start_hour, end_hour in search_windows:
                start_search = current_day.replace(hour=start_hour, minute=0, second=0, microsecond=0)

                # If searching on 'today', don't suggest past times
                if day_offset == 0 and base_dt > start_search:
                    start_search = base_dt

                end_search_limit = current_day.replace(hour=end_hour, minute=0, second=0, microsecond=0)

                # Step through time in 30-minute intervals
                temp_start = start_search
                while temp_start + datetime.timedelta(minutes=duration_minutes) <= end_search_limit:
                    slot_start = temp_start.isoformat()
                    slot_end = (temp_start + datetime.timedelta(minutes=duration_minutes)).isoformat()

                    conflicts = self.check_conflicts(slot_start, slot_end, target_semesters)

                    if not conflicts:
                        suggestions.append({
                            "start": slot_start,
                            "end": slot_end,
                            "display": temp_start.strftime("%A, %d %b | %I:%M %p")
                        })

                    if len(suggestions) >= 2:  # STRICT REQUIREMENT: 2 suggestions
                        return suggestions

                    temp_start += datetime.timedelta(minutes=30)

        return suggestions

    def create_event(
            self,
            calendar_type,
            summary,
            start_time,
            end_time,
            description="",
            recurrence_until=None,
            creator_email=None  # NEW: For Feature 4 (Ownership)
    ):
        """
        Creates an event in the target calendar.
        Supports Problem 1: Timetable Sync with RRULE.
        Supports Feature 4: Stores creator email for cancellation rights.
        """
        cal_id = (
            self.static_cal_id
            if calendar_type == "static"
            else self.temp_cal_id
        )

        if cal_id == "primary" or not cal_id:
            raise RuntimeError("❌ Refusing to create events in PRIMARY calendar.")

        event = {
            "summary": summary,
            "description": description.strip(),
            "start": {
                "dateTime": start_time,
                "timeZone": self.timezone
            },
            "end": {
                "dateTime": end_time,
                "timeZone": self.timezone
            },
            # Feature 4: Store creator email in metadata
            "extendedProperties": {
                "shared": {
                    "creator_email": creator_email if creator_email else "system"
                }
            }
        }

        # Problem 1: Add RRULE for static timetable classes
        if recurrence_until and calendar_type == "static":
            # Format: UNTIL=YYYYMMDDTHHMMSSZ
            # Recurrence expects a list of strings
            until_date = recurrence_until.strftime("%Y%m%dT235959Z")
            event["recurrence"] = [f"RRULE:FREQ=WEEKLY;UNTIL={until_date}"]

        try:
            return self.service.events().insert(
                calendarId=cal_id,
                body=event
            ).execute()

        except HttpError as e:
            print(f"❌ Event creation failed: {e}")
            return None

    def get_event(self, calendar_type, event_id):
        """
        Retrieves a single event. Used for checking cancellation rights .
        """
        cal_id = self.static_cal_id if calendar_type == "static" else self.temp_cal_id
        try:
            return self.service.events().get(
                calendarId=cal_id,
                eventId=event_id
            ).execute()
        except HttpError:
            return None

    def delete_event(self, calendar_type, event_id):
        """
        Deletes a single event. Used for Student Cancellation.
        """
        cal_id = self.static_cal_id if calendar_type == "static" else self.temp_cal_id
        try:
            self.service.events().delete(
                calendarId=cal_id,
                eventId=event_id
            ).execute()
            return True
        except HttpError as e:
            print(f"❌ Delete failed: {e}")
            return False

    def delete_events_by_semester(self, semester_tag):
        """
        Feature 2: Admin Undo.
        Atomically deletes all events in Static Calendar matching a specific semester tag.
        Uses 'q' parameter for server-side filtering (safer & faster).
        """
        try:
            # Query for events containing the semester tag in text (summary or description)
            # Example q="Semester: Sem 3"
            query = f"Semester: {semester_tag}"

            page_token = None
            deleted_count = 0

            while True:
                events_result = self.service.events().list(
                    calendarId=self.static_cal_id,
                    q=query,
                    # singleEvents=True,  # Expand recurring instances to delete them individually?
                    # Actually for Undo, better to delete the master recurrence.
                    # So singleEvents=False.
                    singleEvents=False,
                    pageToken=page_token
                ).execute()

                items = events_result.get('items', [])

                for item in items:
                    # Double check description to be safe
                    desc = item.get('description', '')
                    if query in desc:
                        self.service.events().delete(
                            calendarId=self.static_cal_id,
                            eventId=item['id']
                        ).execute()
                        deleted_count += 1

                page_token = events_result.get('nextPageToken')
                if not page_token:
                    break

            return deleted_count

        except HttpError as e:
            print(f"❌ Batch delete failed: {e}")
            return 0

    def delete_past_temp_events(self):
        """Cleanup rule: Removes events in the temporary calendar that have passed."""
        tz = pytz.timezone(self.timezone)
        now = datetime.datetime.now(tz).isoformat()

        try:
            events_result = self.service.events().list(
                calendarId=self.temp_cal_id,
                timeMax=now,
                singleEvents=True
            ).execute()

            events = events_result.get('items', [])

            for event in events:
                self.service.events().delete(
                    calendarId=self.temp_cal_id,
                    eventId=event['id']
                ).execute()

            return len(events)

        except HttpError as e:
            print(f"Cleanup error: {e}")
            return 0