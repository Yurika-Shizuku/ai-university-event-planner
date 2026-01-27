import sys
import os
import subprocess
import datetime
import json
from pathlib import Path
from dotenv import load_dotenv

# Ensure 'core' modules can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.gemini_client import GeminiClient
from core.agent import SchedulingAgent

# Load API keys from .env file
load_dotenv()

# Constants for History Persistence
HISTORY_FILE = Path("data/history.json")
Path("data").mkdir(exist_ok=True)
Path("data/uploads").mkdir(parents=True, exist_ok=True)


def save_history(record):
    """Saves upload event to history file for Admin Dashboard visibility."""
    history = []
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except json.JSONDecodeError:
            history = []

    history.append(record)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def admin_setup(pdf_filename):
    """
    Headless CLI workflow for Admins to upload timetables.
    FIXED: Now supports Problem 1 (Weekly RRULE) by requesting start/end dates.
    UPDATED: Saves to history for Feature 2 (Admin Undo/History).
    """
    print(f"\n--- 🛠️ CLI Admin Mode: Processing {pdf_filename} ---")

    pdf_path = Path("data/uploads") / pdf_filename
    if not pdf_path.exists():
        # Try looking in root if not in uploads
        pdf_path = Path(pdf_filename)
        if not pdf_path.exists():
            print(f"❌ Error: File not found at {pdf_path}")
            return

    # Request dates for Problem 1
    print("\n📅 Timetable Duration Required:")
    start_input = input("Enter Semester Start Date (YYYY-MM-DD): ").strip()
    end_input = input("Enter Semester End Date (YYYY-MM-DD): ").strip()

    try:
        sem_start = datetime.datetime.strptime(start_input, "%Y-%m-%d").date()
        sem_end = datetime.datetime.strptime(end_input, "%Y-%m-%d").date()
    except ValueError:
        print("❌ Invalid date format. Please use YYYY-MM-DD.")
        return

    gemini = GeminiClient()
    agent = SchedulingAgent()

    try:
        print(f"📄 Reading {pdf_path.name}...")
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        # Extract data
        print("🤖 Analyzing PDF with Gemini 2.0 Flash...")
        extracted_data = gemini.extract_timetable_data(pdf_bytes)

        events = extracted_data.get("events", [])
        metadata = extracted_data.get("metadata", {})
        semester_tag = metadata.get("semester", "All")
        branch_tag = metadata.get("branch", "N/A")

        if events and isinstance(events, list):
            print(f"✅ Found {len(events)} events for {semester_tag} ({branch_tag}).")
            print("🔄 Syncing with Weekly Recurrence...")

            days_map = {
                "Monday": 0, "Tuesday": 1, "Wednesday": 2,
                "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6
            }

            success_count = 0

            for event in events:
                day_name = event.get("day", "Monday").capitalize()
                target_weekday = days_map.get(day_name, 0)

                # Calculate first occurrence on or after sem_start
                days_ahead = target_weekday - sem_start.weekday()
                if days_ahead < 0:
                    days_ahead += 7
                first_date = sem_start + datetime.timedelta(days=days_ahead)

                # Format ISO 8601 with Asia/Kolkata timezone
                # Expecting HH:MM string from Gemini
                start_iso = f"{first_date.isoformat()}T{event['start_time']}:00+05:30"
                end_iso = f"{first_date.isoformat()}T{event['end_time']}:00+05:30"

                # Standardize description for Problem 3 (Conflict Detection Compatibility)
                # MUST match the format used in gemini_client.py and app.py
                description = f"Semester: {semester_tag} | Branch: {branch_tag}"

                # Create event with recurrence_until for Problem 1
                result = agent.cal.create_event(
                    calendar_type="static",
                    summary=f"[Class] {event['summary']}",
                    start_time=start_iso,
                    end_time=end_iso,
                    description=description,
                    recurrence_until=sem_end
                )

                if result:
                    success_count += 1
                    print(f"  + Created: {event['summary']} ({day_name})")

            # --- FEATURE 2: PERSIST HISTORY ---
            # Save the upload record so it appears in the Web Admin Dashboard
            if success_count > 0:
                save_history({
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "semester": semester_tag,
                    "branch": branch_tag,
                    "event_count": success_count
                })

            print(f"\n🚀 Static Calendar updated successfully! {success_count} classes synced until {sem_end}.")
            print("📝 Upload logged to Admin History.")

        else:
            print("❌ Extraction failed. AI returned no events.")

    except Exception as e:
        print(f"❌ CLI Admin Setup failed: {e}")


def launch_web_app():
    """Launches the Streamlit Web Interface."""
    print("🌐 Launching AI Event Planner Web Interface...")
    try:
        subprocess.run(["streamlit", "run", "app.py"])
    except FileNotFoundError:
        print("❌ Error: Streamlit is not installed. Run 'pip install streamlit'.")
    except Exception as e:
        print(f"❌ Error launching app: {e}")


if __name__ == "__main__":
    if "--admin" in sys.argv:
        try:
            filename = sys.argv[sys.argv.index("--admin") + 1]
            admin_setup(filename)
        except (IndexError, ValueError):
            print("❌ Usage: python main.py --admin <file.pdf>")
    else:
        launch_web_app()