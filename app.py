import streamlit as st
import pandas as pd
import json
import os
from pathlib import Path
from datetime import datetime, date, timedelta, time
import pytz

from time import sleep

from core.gemini_client import GeminiClient
from core.agent import SchedulingAgent

@st.cache_resource
def get_cached_agent():
    """
    Initializes the SchedulingAgent ONLY ONCE.
    This prevents re-logging into Google on every button click.
    """
    from core.agent import SchedulingAgent
    return SchedulingAgent()
# --- Page Config ---
st.set_page_config(page_title="AI Event Planner Pro", page_icon="📅", layout="wide")

# --- Constants & Config ---
# FIX: Ensure environment variable usage for Admins if available, else default
ADMIN_EMAILS = json.loads(os.getenv("ADMIN_EMAILS", '["admin@university.edu"]'))
COLLEGE_DOMAIN = "@college.edu"
HISTORY_FILE = Path("data/history.json")
Path("data").mkdir(exist_ok=True)

# --- Session State Initialization ---
if "user" not in st.session_state:
    st.session_state.user = None  # {email, role}
if "preview_data" not in st.session_state:
    st.session_state.preview_data = None
if "ai_response" not in st.session_state:
    st.session_state.ai_response = None
# Organiser Form State
if "org_date" not in st.session_state:
    st.session_state.org_date = date.today()
if "org_start_time" not in st.session_state:
    st.session_state.org_start_time = time(9, 0)
if "org_end_time" not in st.session_state:
    st.session_state.org_end_time = time(10, 0)
if "org_title" not in st.session_state:
    st.session_state.org_title = ""
if "org_target" not in st.session_state:
    st.session_state.org_target = ["All"]


# --- Authentication Logic ---
def login(email):
    email = email.strip().lower()
    role = None

    if email in ADMIN_EMAILS:
        role = "Admin"
    elif email.endswith(COLLEGE_DOMAIN) or "@" in email:  # Allow teachers/students
        role = "Student"
    else:
        st.error("❌ Invalid Email format.")
        return

    st.session_state.user = {"email": email, "role": role}
    st.rerun()


def logout():
    st.session_state.user = None
    st.rerun()


# --- Admin History Management ---
def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


def save_history(record):
    history = load_history()
    history.append(record)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def delete_semester_history(sem_tag):
    """Removes a semester from history and deletes events from Calendar."""
    agent = SchedulingAgent()
    count = agent.cal.delete_events_by_semester(sem_tag)

    # Update local history file
    history = load_history()
    new_history = [h for h in history if h['semester'] != sem_tag]
    with open(HISTORY_FILE, "w") as f:
        json.dump(new_history, f, indent=2)

    return count


# --- Helper Functions ---
@st.cache_data(show_spinner=False)
def cached_extraction(file_bytes):
    client = GeminiClient()
    return client.extract_timetable_data(file_bytes)


def get_first_occurrence(start_date, day_name):
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    try:
        target_day = days.index(day_name.capitalize())
    except ValueError:
        target_day = 0
    current_day = start_date.weekday()
    delta = target_day - current_day
    if delta < 0:
        delta += 7
    return start_date + timedelta(days=delta)


def sync_recurring_timetable(events, metadata, semester_start, semester_end):
    """
    Syncs the timetable with weekly recurrence until semester_end.
    """
    agent = SchedulingAgent()
    sem_name = metadata.get("semester", "All")
    ids = []

    for ev in events:
        start_date = get_first_occurrence(semester_start, ev["day"])
        start_iso = f"{start_date.isoformat()}T{ev['start_time']}:00+05:30"
        end_iso = f"{start_date.isoformat()}T{ev['end_time']}:00+05:30"

        # Mandatory metadata for Problem 3
        desc = f"Semester: {sem_name} | Branch: {metadata.get('branch', 'N/A')}"

        res = agent.cal.create_event(
            calendar_type="static",
            summary=f"[Class] {ev['summary']}",
            start_time=start_iso,
            end_time=end_iso,
            description=desc,
            recurrence_until=semester_end
        )

        if res:
            ids.append(res["id"])

    # Save to History
    save_history({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "semester": sem_name,
        "branch": metadata.get("branch", "N/A"),
        "event_count": len(ids)
    })

    return ids


# ==========================================
#              MAIN APP UI
# ==========================================

if not st.session_state.user:
    # --- Login Screen ---
    st.markdown(
        "<h1 style='text-align: center;'> Event Planner Login</h1>",
        unsafe_allow_html=True
    )

    c1, c2, c3 = st.columns([1, 2, 1])

    with c2:
        with st.form("login_form"):
            email_input = st.text_input("Enter Institutional Email")
            submit = st.form_submit_button("Login")

        if submit and email_input:
            login(email_input)

        st.info(
            f"**Admin Access:** {', '.join(ADMIN_EMAILS)}\n\n"
            f"**Student Access:** Any valid email."
        )

else:
    # --- Authenticated App ---
    user_email = st.session_state.user["email"]
    user_role = st.session_state.user["role"]

    # Header
    col_l, col_r = st.columns([8, 2])

    col_l.title(" AI Uni Event Planner")
    col_r.write(f" **{user_role}**: {user_email}")

    if col_r.button("Logout"):
        logout()

    st.divider()


    # ==========================================
    #              ADMIN DASHBOARD
    # ==========================================
    if user_role == "Admin":
        st.subheader(" Admin Dashboard")

        tab1, tab2 = st.tabs(["📤 Upload Timetable", " Upload History"])

        with tab1:
            st.info("Set semester bounds for weekly recurrence.")
            c1, c2 = st.columns(2)
            start_dt = c1.date_input("Semester Start", date.today())
            end_dt = c2.date_input("Semester End", date.today() + timedelta(weeks=16))
            uploaded_file = st.file_uploader("Upload PDF Timetable", type="pdf")

            if uploaded_file and st.button("Analyze PDF"):
                with st.spinner("Extracting with Gemini..."):
                    try:
                        data = cached_extraction(uploaded_file.getvalue())
                        st.session_state.preview_data = data
                        st.success("Analysis Complete. Please review below.")
                    except Exception as e:
                        st.error(f"Analysis failed: {e}")

            # --- Editable Preview (Feature 3) ---
            if st.session_state.preview_data:
                st.write("###  Review & Edit Before Sync")
                st.caption("Double-click cells to edit extracted details.")

                # 1. Create DataFrame
                df = pd.DataFrame(st.session_state.preview_data["events"])

                # 2. CONVERSION FIX: Convert String "HH:MM" -> datetime.time objects for UI
                try:
                    df["start_time"] = pd.to_datetime(df["start_time"], format="%H:%M").dt.time
                    df["end_time"] = pd.to_datetime(df["end_time"], format="%H:%M").dt.time
                except Exception as e:
                    st.error(f"Error parsing time data: {e}")

                # 3. Render Data Editor
                edited_df = st.data_editor(
                    df,
                    num_rows="dynamic",
                    column_config={
                        "start_time": st.column_config.TimeColumn("Start", format="HH:mm"),
                        "end_time": st.column_config.TimeColumn("End", format="HH:mm"),
                        "day": st.column_config.SelectboxColumn(
                            "Day",
                            options=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
                                     "Sunday"]
                        )
                    },
                    use_container_width=True
                )

                meta = st.session_state.preview_data.get("metadata", {})
                st.write(f"**Target Semester:** {meta.get('semester')} | **Branch:** {meta.get('branch')}")

                if st.button(" Confirm & Sync to Calendar"):
                    # 4. REVERSION FIX: Convert datetime.time objects BACK to String "HH:MM"
                    # This ensures compatibility with sync_recurring_timetable logic
                    try:
                        # Helper to safely format time objects
                        def format_time_safe(t):
                            if isinstance(t, time):
                                return t.strftime("%H:%M")
                            return str(t)  # Fallback


                        edited_df["start_time"] = edited_df["start_time"].apply(format_time_safe)
                        edited_df["end_time"] = edited_df["end_time"].apply(format_time_safe)

                        # Convert back to list of dicts
                        final_events = edited_df.to_dict('records')

                        with st.spinner("Syncing to Google Calendar..."):
                            ids = sync_recurring_timetable(
                                final_events,
                                meta,
                                start_dt,
                                end_dt
                            )
                            st.success(f" Successfully created {len(ids)} recurring events!")
                            st.session_state.preview_data = None  # Clear after sync

                    except Exception as e:
                        st.error(f"Sync failed: {e}")

        with tab2:
            st.write("###  Managed Semesters")
            history = load_history()

            if not history:
                st.write("No uploads found.")
            else:
                for h in history:
                    c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
                    c1.write(f"**{h['semester']}**")
                    c2.write(f"{h['branch']}")
                    c3.write(h['timestamp'])

                    # Undo Feature (Feature 2)
                    if c4.button(f" Undo {h['semester']}", key=h['timestamp']):
                        with st.spinner("Rolling back calendar..."):
                            count = delete_semester_history(h['semester'])
                            st.success(f"Deleted {count} events for {h['semester']}.")
                            st.rerun()

    # ==========================================
    #             STUDENT DASHBOARD
    # ==========================================

    else:
        st.header(" Student Event Manager")

        tab_book, tab_my_events = st.tabs([" Book Event", " My Bookings"])

        with tab_book:
            # Manual Form
            col1, col2 = st.columns(2)
            with col1:
                st.session_state.org_date = st.date_input(" Event Date", st.session_state.org_date)
                st.session_state.org_title = st.text_input(" Event Title", st.session_state.org_title)

            with col2:
                st.session_state.org_start_time = st.time_input(" Start Time", st.session_state.org_start_time)
                st.session_state.org_end_time = st.time_input(" End Time", st.session_state.org_end_time)
                st.session_state.org_target = st.multiselect(
                    "Target Semester",
                    ["Sem 1", "Sem 2", "Sem 3", "Sem 4", "Sem 5", "Sem 6", "Sem 7", "Sem 8", "All"],
                    default=st.session_state.org_target
                )

            # --- AI Interaction ---
            st.subheader(" AI Assistant")
            ai_prompt = st.text_area("Ask AI (e.g., 'Find a slot for Coding Club next Tuesday')",
                                     placeholder="E.g., Coding club meeting next Tuesday afternoon for 90 mins")

            if st.button(" Ask AI"):
                with st.spinner("AI is thinking..."):
                    agent = get_cached_agent()
                    client = GeminiClient()

                    # 1. Parse intent - Use AI to figure out WHAT they want
                    try:
                        # We pass a simple initial prompt to get the intent JSON
                        intent_data = client.parse_event_request(ai_prompt)
                        intent_info = intent_data.get("intent", {})

                        target_sem = intent_info.get("target_semesters", "All")
                        duration = intent_info.get("duration_minutes", 60)

                        # Use today/now as defaults if not extracted
                        now = datetime.now()
                        start_iso = f"{now.strftime('%Y-%m-%d')}T09:00:00+05:30"
                        end_iso = f"{now.strftime('%Y-%m-%d')}T10:00:00+05:30"  # Placeholder

                        # --- [ADDED] PARSE WEEKDAY CONSTRAINTS ---
                        # Extract specific days (e.g. "Wednesday") from user text to enforce strict filtering
                        user_prompt_lower = ai_prompt.lower()
                        valid_days = []
                        day_map = {
                            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                            "friday": 4, "saturday": 5, "sunday": 6
                        }

                        for day_name, day_idx in day_map.items():
                            if day_name in user_prompt_lower:
                                valid_days.append(day_idx)

                        # If no specific days mentioned, default to None (Allow all days)
                        if not valid_days:
                            valid_days = None
                        # -----------------------------------------

                        # 2. Check Actual Availability (Using Logic, not AI hallucination)
                        # We check next 7 days if exact date not specified.

                        # --- [CHANGED] Pass 'valid_weekdays' to the agent ---
                        suggestions_str = agent.get_alternative_slots(
                            start_iso,
                            duration,
                            target_sem,
                            valid_weekdays=valid_days  # <--- NEW PARAMETER
                        )

                        # 3. Get AI Explanation with Real Data
                        # We feed the real availability data back into the AI to generate the friendly response
                        context = f"User wants: {intent_info}\nBackend Availability Data:\n{suggestions_str}"
                        st.session_state.ai_response = client.parse_event_request(ai_prompt,
                                                                                  availability_context=context)

                    except Exception as e:
                        st.error(f"AI Error: {e}")

            if st.session_state.ai_response:
                res = st.session_state.ai_response
                st.info(f"**AI:** {res.get('explanation')}")

                if res.get("suggestions"):
                    st.write("###  Recommended Slots")
                    for sug in res["suggestions"]:
                        if st.button(f"Book {sug['display']}", key=sug['start_iso']):
                            #agent = get_cached_agent()
                            booking_res = agent.book_temporary_event(
                                summary=res['intent'].get('event_name', "New Event"),
                                start_iso=sug['start_iso'],
                                end_iso=sug['end_iso'],
                                target_semesters=res['intent'].get('target_semesters', "All"),
                                creator_email=user_email  # Feature 4
                            )
                            if "✅" in booking_res:
                                st.success(booking_res)
                                st.session_state.ai_response = None
                            else:
                                st.error(booking_res)

            st.divider()

            # --- Manual Finalize ---
            if st.button(" Finalize Manual Entry"):
                agent = get_cached_agent()
                start_iso = f"{st.session_state.org_date.isoformat()}T{st.session_state.org_start_time.strftime('%H:%M:%S')}+05:30"
                end_iso = f"{st.session_state.org_date.isoformat()}T{st.session_state.org_end_time.strftime('%H:%M:%S')}+05:30"

                with st.spinner("Checking Availability..."):
                    # 1. Check for Conflicts
                    status = agent.check_availability(start_iso, end_iso, st.session_state.org_target)

                    if "❌" in status:
                        # Case A: Conflict Detected
                        st.error(status)  # Red Box for Conflict

                        # 2. Automatically get suggestions separate from the error
                        try:
                            s_dt = datetime.combine(st.session_state.org_date, st.session_state.org_start_time)
                            e_dt = datetime.combine(st.session_state.org_date, st.session_state.org_end_time)
                            duration_mins = int((e_dt - s_dt).total_seconds() / 60)

                            suggestions_text = agent.get_alternative_slots(start_iso, duration_mins,
                                                                           st.session_state.org_target)

                            st.info(suggestions_text)  # Blue/Info Box for Solutions
                        except Exception as e:
                            st.warning("Could not calculate alternative slots.")

                    else:
                        # Case B: No Conflict -> Book Immediately
                        res = agent.book_temporary_event(
                            summary=st.session_state.org_title,
                            start_iso=start_iso,
                            end_iso=end_iso,
                            target_semesters=st.session_state.org_target,
                            creator_email=user_email
                        )

                        if "✅" in res:
                            st.success(res)
                        else:
                            st.error(res)

        # --- My Events (Feature 4 & 5) ---
        with tab_my_events:
            st.subheader(" Your Scheduled Events")
            agent = SchedulingAgent()

            if st.button("Refresh My Events"):
                st.rerun()

            try:
                now_str = datetime.now(pytz.utc).isoformat()
                events_result = agent.cal.service.events().list(
                    calendarId=agent.cal.temp_cal_id,
                    timeMin=now_str,  # Only future events
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()

                my_events = []
                for ev in events_result.get('items', []):
                    # Check ownership via Extended Properties
                    props = ev.get("extendedProperties", {}).get("shared", {})
                    creator = props.get("creator_email")

                    # Admins see everything, Users see only theirs
                    if user_role == "Admin" or creator == user_email:
                        my_events.append(ev)

                if not my_events:
                    st.info("No upcoming events found.")
                else:
                    for ev in my_events:
                        props = ev.get("extendedProperties", {}).get("shared", {})
                        creator = props.get("creator_email", "Unknown")

                        with st.expander(f"{ev['summary']} | {ev['start'].get('dateTime')[11:16]} | By: {creator}"):
                            st.write(
                                f"**Time:** {ev['start'].get('dateTime')[11:16]} - {ev['end'].get('dateTime')[11:16]}")
                            st.write(f"**Details:** {ev.get('description', '')}")

                            # Cancel Button logic
                            if st.button(" Cancel Event", key=ev['id']):
                                res = agent.cancel_event(ev['id'], requester_email=user_email)
                                if "✅" in res:
                                    st.success(res)
                                    sleep(1)
                                    st.rerun()
                                else:
                                    st.error(res)
            except Exception as e:
                st.error(f"Error fetching events: {e}")