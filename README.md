# AI-university-event-planner
An intelligent dual-calendar system that uses **Gemini 2.0** to synchronizes university timetables and club events using Gemini 2.0 to eliminate scheduling conflicts.

---

## The Why?
University life is a balancing act between academics and extracurriculars. Existing tools often dump everything into one calendar, leading to cluttered views and scheduling overlaps.
- Students and club organizers must manually track classes and events
- Overlapping academic and club events  
- Double bookings during class hours

This project solves the problem by **automatically extracting timetables using AI** and **enforcing conflict-aware scheduling** across multiple Google Calendars.

Static Semester Calendar: Reserved exclusively for university-mandated timetables and lectures.

Club Temporary Events: A dedicated space for organizer-led events.

---

## Technical Architecture

### 1 Intelligence Layer — *Gemini 2.0*

- **Multimodal PDF Extraction**  
  Parses complex timetable PDFs to identify weekly recurring class patterns.

- **Contextual Metadata Detection**  
  Automatically detects **Branch (IT, CS, etc.)** and **Semester** from document headers.

- **Robust JSON Parsing**  
  Custom sanitization removes AI narration and markdown fences to ensure clean, structured JSON output.

---

### 2 Orchestration Layer — *Google Calendar API*

- **Dual-Calendar Logic**
  -  **Static Semester Calendar** → Academic classes  
  -  **Club Temporary Calendar** → Events & extracurriculars  

- **Conflict-First Booking**  
  Uses Google Calendar **FreeBusy API** to block event creation if a class already exists.

- **Timezone Enforcement**  
  All events are strictly handled in **Asia/Kolkata** timezone.

---

### 3 Presentation Layer — *Streamlit*

- **4-Box Input System**  
  Clean and reactive UI allowing organizers to:
  - Manually enter event details  
  - Or auto-fill using natural language with AI  

- **Quota-Safe Caching**  
  Uses `@st.cache_data` to reduce API calls and prevent **429 rate-limit errors** during demos or judging.

---

## 4 Tech Stack

- **AI / LLM**: Gemini 2.0  
- **Backend**: Python 3.11
- **Frontend**: Streamlit  
- **APIs**: Google Calendar API 
- **Authentication**: OAuth 2.0 
- **Timezone Handling**: pytz (Asia/Kolkata)

---

## Setup & Installation

### 1 Clone Repository & Install Dependencies

```bash
git clone https://github.com/Yurika-Shizuku/ai-university-event-planner.git
cd ai-university-event-planner
pip install -r requirements.txt
```
## 2. Environment setup

Create a .env file in the root directory:
```
GOOGLE_API_KEY=your_google_api_key_here
```
## 3. Google API Credentials
1. Enable the Google Calendar API in your Google Cloud Console.
2. Configure the OAuth Consent Screen and add your email to the Test Users list.
3. Download your `credentials.json` and place it in the root folder.

Note: On first run, a browser window will open for authentication, creating `token.json` locally..

---

## Future Scope & Scaling
*Smart Conflict Resolution & Recommendation*

**Intelligent Rescheduling**: If a conflict is detected, the AI will proactively suggest the three best alternative slots based on the target group's collective free time across all calendars.

**Urgency Scoring**: Implement a priority system where "University Exams" (Static) take absolute precedence, but "Major Club Events" can temporarily suggest a shift in minor "Study Group" sessions.

**Bulk Branch Management**: Allow a single Admin to upload a ZIP file containing timetables for all branches (CS, IT, ECE) and have the AI distribute them to branch-specific public calendars automatically.
