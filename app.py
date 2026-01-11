import streamlit as st
from pathlib import Path
from datetime import datetime, date, timedelta
from core.gemini_client import GeminiClient
from core.agent import SchedulingAgent
import json
from datetime import datetime, date, timedelta, time

# --- 1. Session State Persistence ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "upload_history" not in st.session_state:
    st.session_state.upload_history = []
if "preview_data" not in st.session_state:
    st.session_state.preview_data = None
if "curr_file" not in st.session_state:
    st.session_state.curr_file = ""
if "generated" not in st.session_state:
    st.session_state.generated = False
st.set_page_config(page_title="AI Event Planner Pro", page_icon="📅", layout="wide")
# --- Organiser State ---
if "org_date" not in st.session_state:
    st.session_state.org_date = date.today()
if "org_time" not in st.session_state:
    st.session_state.org_time = datetime.now().time().replace(second=0, microsecond=0)
if "org_title" not in st.session_state:
    st.session_state.org_title = ""
if "org_target" not in st.session_state:
    st.session_state.org_target = ["All"]
if "org_ai_used" not in st.session_state:
    st.session_state.org_ai_used = False

# --- 2. Caching Wrapper (The "Silver Bullet" Fix) ---
# We cache based on file_bytes so renaming a file doesn't trick the cache
@st.cache_data(show_spinner=False)
def cached_extraction(file_bytes):
    """
    Caches the API result based on file CONTENT.
    1. Prevents 429 errors on reruns.
    2. Avoids disk I/O for the AI step.
    """
    client = GeminiClient()
    return client.extract_timetable_data(file_bytes)


# --- 3. Logic Utilities ---
def get_first_occurrence(start_date, day_name):
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    try:
        target_day = days.index(day_name.capitalize())
        current_day = start_date.weekday()
        days_ahead = target_day - current_day
        if days_ahead < 0: days_ahead += 7
        return start_date + timedelta(days_ahead)
    except:
        return start_date


def sync_recurring_timetable(events, semester_start, semester_end):
    # Rename to avoid shadowing global imports
    sync_agent = SchedulingAgent()
    master_ids = []
    until_str = semester_end.strftime("%Y%m%dT235959Z")
    day_map = {"Monday": "MO", "Tuesday": "TU", "Wednesday": "WE",
               "Thursday": "TH", "Friday": "FR", "Saturday": "SA", "Sunday": "SU"}

    for ev in events:
        day_str = ev.get('day', 'Monday').capitalize()
        rrule_day = day_map.get(day_str, "MO")
        actual_start_date = get_first_occurrence(semester_start, day_str)

        # We manually combine Date + Time here, so "HH:MM" schema is perfectly fine
        event_body = {
            'summary': f"[Sync] {ev['summary']}",
            'start': {'dateTime': f"{actual_start_date.isoformat()}T{ev['start_time']}:00", 'timeZone': 'Asia/Kolkata'},
            'end': {'dateTime': f"{actual_start_date.isoformat()}T{ev['end_time']}:00", 'timeZone': 'Asia/Kolkata'},
            'recurrence': [f'RRULE:FREQ=WEEKLY;BYDAY={rrule_day};UNTIL={until_str}'],
        }
        try:
            res = sync_agent.cal.service.events().insert(calendarId='primary', body=event_body).execute()
            master_ids.append(res['id'])
        except Exception as e:
            st.error(f"Sync error: {e}")
    return master_ids


def undo_sync(event_ids):
    undo_agent = SchedulingAgent()
    for eid in event_ids:
        try:
            undo_agent.cal.service.events().delete(calendarId='primary', eventId=eid).execute()
        except:
            pass


# --- 4. UI Implementation ---
with st.sidebar:
    st.title("⚙️ Control Panel")
    mode = st.radio("Select Mode", ["Student Chat", "Admin Upload"])

    if mode == "Admin Upload":
        st.header("Sync Settings")
        start_dt = st.date_input("Semester Start", date.today())
        end_dt = st.date_input("Semester End", date.today() + timedelta(weeks=12))
        uploaded_file = st.file_uploader("Upload PDF Timetable", type="pdf")

        if st.button("Generate Preview"):
            if uploaded_file:
                # Read bytes ONCE for both Cache and Processing
                file_bytes = uploaded_file.getvalue()

                with st.spinner("AI is analyzing (Cached)..."):
                    try:
                        # Pass bytes directly to cache -> client
                        raw_data = cached_extraction(file_bytes)

                        events = raw_data if isinstance(raw_data, list) else raw_data.get("events", [])
                        if events:
                            st.session_state.preview_data = events
                            st.session_state.generated = True  # 🔒 LOCK API
                            st.sidebar.success("Preview Loaded!")
                        else:
                            st.error("AI returned no events.")
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.error("Upload a file first.")

st.title("📅 AI University Event Planner")

if mode == "Admin Upload":
    if st.session_state.preview_data:
        st.subheader(f"👀 Preview: {st.session_state.curr_file}")
        st.table(st.session_state.preview_data)

        if st.button("🚀 Confirm & Sync All", type="primary"):
            with st.spinner("Syncing to Google Calendar..."):
                m_ids = sync_recurring_timetable(st.session_state.preview_data, start_dt, end_dt)
                if m_ids:
                    st.session_state.upload_history.append({
                        "file": st.session_state.curr_file, "ids": m_ids,
                        "status": "Active", "timestamp": datetime.now().strftime("%H:%M:%S")
                    })
                    st.session_state.preview_data = None
                    st.success("Synced Successfully!")
                    st.rerun()

    st.divider()
    st.subheader("📜 History")
    for i, entry in enumerate(st.session_state.upload_history):
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.write(f"📁 {entry['file']} ({entry['timestamp']})")
        c2.write(f"Status: {entry['status']}")
        if entry['status'] == "Active" and c3.button("Undo", key=f"undo_{i}"):
            undo_sync(entry['ids'])
            entry['status'] = "Deleted"
            st.rerun()

elif mode == "Student Chat":  # rename label later if you want
    st.header("🏗️ Event Organiser")

    # --- 1. 4-Box Input System ---
    col1, col2 = st.columns(2)

    with col1:
        st.session_state.org_date = st.date_input(
            "📅 Event Date",
            st.session_state.org_date
        )
        st.session_state.org_title = st.text_input(
            "📝 Event Title",
            value=st.session_state.org_title,
            placeholder="e.g. Guest Lecture on AI"
        )

    with col2:
        st.session_state.org_time = st.time_input(
            "⏰ Event Time",
            value=st.session_state.org_time
        )
        st.session_state.org_target = st.multiselect(
            "🎯 Target Semester",
            ["Sem 1", "Sem 2", "Sem 3", "Sem 4", "Sem 5", "Sem 6", "All"],
            default=st.session_state.org_target
        )

    st.divider()

    # --- 2. AI-Assisted Scheduling (OPTIONAL) ---
    st.subheader("🤖 AI-Assisted Scheduling (Optional)")

    ai_prompt = st.text_area(
        "Describe the event in natural language",
        placeholder="Schedule a coding workshop next Friday at 2pm"
    )

    if st.button("✨ Use AI to Fill Details"):
        if not ai_prompt.strip():
            st.warning("Please write something for the AI to understand.")
        else:
            with st.spinner("Understanding your request..."):
                try:
                    agent = SchedulingAgent()

                    system_prompt = f"""
                    Convert the user request into STRICT JSON.
                    Today is {date.today()}.

                    Return ONLY JSON in this format:
                    {{
                      "date": "YYYY-MM-DD",
                      "time": "HH:MM",
                      "title": "Event title"
                    }}
                    """

                    resp = agent.get_chat_session().send_message(
                        system_prompt + "\nUser request: " + ai_prompt
                    )

                    parsed = json.loads(resp.text)

                    # ✅ Auto-fill safely
                    st.session_state.org_date = date.fromisoformat(parsed["date"])
                    h, m = map(int, parsed["time"].split(":"))
                    st.session_state.org_time = time(h, m)
                    st.session_state.org_title = parsed["title"]
                    st.session_state.org_ai_used = True

                    st.success("Details filled! Review and confirm below 👇")

                except Exception as e:
                    st.error(f"AI could not understand the request: {e}")
    st.divider()
    st.subheader("📅 Finalize Event")

    if st.button("🚀 Check & Book Event", type="primary"):
        agent = SchedulingAgent()

        # Use strftime to ensure seconds (:00) and the +05:30 offset are included
        start_iso = f"{st.session_state.org_date.isoformat()}T{st.session_state.org_time.strftime('%H:%M:%S')}+05:30"

        # Safely calculate a 1-hour end time
        end_time_obj = (datetime.combine(date.min, st.session_state.org_time) + timedelta(hours=1)).time()
        end_iso = f"{st.session_state.org_date.isoformat()}T{end_time_obj.strftime('%H:%M:%S')}+05:30"
        conflicts = agent.cal.check_conflicts(start_iso, end_iso)

        if conflicts:
            st.error("❌ This time clashes with existing timetable events.")
            st.json(conflicts)
        else:
            desc = f"Target: {', '.join(st.session_state.org_target)}"
            res = agent.cal.create_event(
                calendar_type="temp",
                summary=st.session_state.org_title,
                start_time=start_iso,
                end_time=end_iso,
                description=desc
            )

            if res:
                st.success("✅ Event booked successfully!")
                st.session_state.org_ai_used = False
