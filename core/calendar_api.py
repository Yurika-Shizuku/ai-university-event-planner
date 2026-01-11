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
        self.static_cal_id = self._get_or_create_calendar(STATIC_CALENDAR_NAME)
        self.temp_cal_id = self._get_or_create_calendar(TEMP_CALENDAR_NAME)
    @staticmethod
    def _authenticate():
        """Handles OAuth2 flow and token management."""
        creds = None
        # Ensure your file is named credentials.json (plural) in your root folder
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return creds

    def _get_or_create_calendar(self, calendar_name):
        """Checks if a specific calendar exists, otherwise creates it with local timezone."""
        try:
            calendar_list = self.service.calendarList().list().execute()
            for entry in calendar_list.get('items', []):
                if entry['summary'] == calendar_name:
                    return entry['id']

            # Create new calendar with Asia/Kolkata timezone
            new_calendar = {
                'summary': calendar_name,
                'timeZone': self.timezone
            }
            created_calendar = self.service.calendars().insert(body=new_calendar).execute()
            return created_calendar['id']
        except HttpError as e:
            print(f"Error managing calendar '{calendar_name}': {e}")
            return 'primary'

    def check_conflicts(self, start_time, end_time):
        """
        Checks for busy slots in ALL calendars using freebusy query.
        Includes required timeZone to prevent 400 Bad Request errors.
        """
        # Ensure only valid, non-empty IDs are sent to the API
        valid_items = []
        for cid in [self.static_cal_id, self.temp_cal_id, "primary"]:
            if cid:
                valid_items.append({"id": cid})

        body = {
            "timeMin": start_time,
            "timeMax": end_time,
            "timeZone": self.timezone,  # Critical field for 2026 project stability
            "items": valid_items
        }

        try:
            result = self.service.freebusy().query(body=body).execute()
            conflicts = []

            # Aggregate busy slots from all queried calendars
            for cal_id, data in result.get("calendars", {}).items():
                busy_slots = data.get("busy", [])
                if busy_slots:
                    conflicts.extend(busy_slots)

            return conflicts

        except HttpError as e:
            # Enhanced error reporting for debugging
            print(f"❌ Conflict check failed: {e}")
            return []
    def create_event(
            self,
            calendar_type,
            summary,
            start_time,
            end_time,
            description=""
    ):
        """
        Creates an event in the target calendar.
        Metadata (Semester/Branch) should be pre-included in the description
        by the caller to ensure consistent formatting.
        """
        cal_id = self.static_cal_id if calendar_type == "static" else self.temp_cal_id

        event = {
            "summary": summary,
            "description": description.strip(),
            "start": {"dateTime": start_time, "timeZone": self.timezone},
            "end": {"dateTime": end_time, "timeZone": self.timezone},
        }

        try:
            return self.service.events().insert(
                calendarId=cal_id,
                body=event
            ).execute()

        except HttpError as e:
            print(f"❌ Event creation failed [{e.status_code}]: {e}")
            return None

    def delete_past_temp_events(self):
        """Cleanup rule: Removes events in the temporary calendar that have passed."""
        # Get current time in Asia/Kolkata
        tz = pytz.timezone(self.timezone)
        now = datetime.datetime.now(tz).isoformat()

        try:
            events_result = self.service.events().list(
                calendarId=self.temp_cal_id, timeMax=now, singleEvents=True
            ).execute()

            events = events_result.get('items', [])
            for event in events:
                self.service.events().delete(calendarId=self.temp_cal_id, eventId=event['id']).execute()
            return len(events)
        except HttpError as e:
            print(f"Cleanup error: {e}")
            return 0