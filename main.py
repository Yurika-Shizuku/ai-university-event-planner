import sys
import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from core.gemini_client import GeminiClient
from core.agent import SchedulingAgent

# Load API keys from .env file
load_dotenv()

def admin_setup(pdf_filename):
    """
    Headless CLI workflow for Admins to upload timetables.
    Useful for batch processing files without the Web UI.
    """
    print(f"\n--- 🛠️ CLI Admin Mode: Processing {pdf_filename} ---")

    pdf_path = Path("data/uploads") / pdf_filename
    if not pdf_path.exists():
        print(f"❌ Error: File not found at {pdf_path}")
        return

    gemini = GeminiClient()
    agent = SchedulingAgent()

    # Extract data using the 2026 Unified SDK
    extracted_data = gemini.extract_timetable_data(pdf_path)

    # Normalize response to prevent 'list' object attribute errors
    events = extracted_data.get("events", []) if isinstance(extracted_data, dict) else extracted_data

    if events and isinstance(events, list):
        print(f"✅ Found {len(events)} events. Syncing to Static Calendar...")
        for event in events:
            # Pushes to 'static' calendar with Asia/Kolkata timezone
            agent.cal.create_event(
                calendar_type="static",
                summary=event["summary"],
                start_time=f"2026-01-12T{event['start_time']}:00", # Defaulting to semester start week
                end_time=f"2026-01-12T{event['end_time']}:00",
                description=event.get("description", "Imported via CLI Admin")
            )
        print("🚀 Static Calendar updated successfully!")
    else:
        print("❌ Extraction failed. AI returned unexpected format or no events.")

def launch_web_app():
    """Launches the Streamlit Web Interface."""
    print("🌐 Launching AI Event Planner Web Interface...")
    try:
        # Executes 'streamlit run app.py' as a subprocess
        subprocess.run(["streamlit", "run", "app.py"])
    except FileNotFoundError:
        print("❌ Error: Streamlit is not installed. Run 'pip install streamlit'.")

if __name__ == "__main__":
    # Ensure local storage exists
    Path("data/uploads").mkdir(parents=True, exist_ok=True)

    # Check for CLI admin flag: python main.py --admin timetable.pdf
    if "--admin" in sys.argv:
        try:
            filename = sys.argv[sys.argv.index("--admin") + 1]
            admin_setup(filename)
        except (IndexError, ValueError):
            print("❌ Usage: python main.py --admin <file.pdf>")
    else:
        # Default behavior: Launch the modern 2026 Web UI
        launch_web_app()