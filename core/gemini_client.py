import os
import time
import json
import datetime
import pytz
from google import genai
from google.genai import types
from dotenv import load_dotenv


def _safe_json_parse(text: str) -> dict:
    """
    Extracts the first valid JSON object from Gemini output.
    Handles markdown, explanations, and noise safely.
    """
    text = text.strip()

    # Remove markdown fences
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json", "", 1).strip()

    # Find first JSON object
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("No JSON object found in AI response")

    json_str = text[start:end + 1]
    return json.loads(json_str)


load_dotenv()


class GeminiClient:
    def __init__(self):
        """Initializes the Gemini 2.0 Client."""
        self.client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        self.model_id = "models/gemini-flash-latest"
        self.timezone = "Asia/Kolkata"

    def extract_timetable_data(self, pdf_bytes):
        """
        Extracts timetable data directly from memory bytes.
        Supports Problem 1 by providing clean metadata for RRULE generation.
        """
        # 1. Size Limit Check (Save Quota)
        if len(pdf_bytes) > 5 * 1024 * 1024:  # 5MB Limit
            raise ValueError("PDF is too large (>5MB). Please compress it.")

        prompt = """
        Extract the weekly timetable and header metadata from this PDF.
        Return JSON in this format ONLY:

        {
          "metadata": {
            "semester": "Sem 3", 
            "branch": "Information Technology"
          },
          "events": [
            {
              "summary": "Subject Name",
              "day": "Monday",
              "start_time": "HH:MM",
              "end_time": "HH:MM",
              "type": "static",
              "description": "Semester: Sem 3"
            }
          ]
        }

        CRITICAL: 
        1. Use the format "Sem X" (e.g., Sem 1, Sem 8) for the semester.
        2. You MUST include "Semester: Sem X" in the description field for EVERY event.
        3. This data will be used to create recurring weekly events.
        """

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1
        )

        # 2. Retry Loop with Exponential Backoff
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model_id,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
                    ],
                    config=config
                )

                data = _safe_json_parse(response.text)

                if not isinstance(data, dict):
                    raise ValueError("AI response is not a JSON object")

                metadata = data.setdefault("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = data["metadata"] = {}

                data["metadata"].setdefault("semester", "Unknown Semester")
                data["metadata"].setdefault("branch", "Unknown Branch")

                # Normalize semester string to "Sem X" format
                sem = data["metadata"]["semester"]
                import re
                digit = re.findall(r'\d+', sem)
                if digit:
                    sem = f"Sem {digit[0]}"
                    data["metadata"]["semester"] = sem

                # FIX 2 (Conflict Detection Data Integrity):
                # We must ensure the 'description' field matches the format expected by calendar.py.
                # If the AI hallucinates a format like "Semester: 3rd", conflict detection fails.
                # We forcefully overwrite the description using the normalized metadata.
                branch = data["metadata"]["branch"]

                data.setdefault("events", [])
                if not isinstance(data["events"], list):
                    raise ValueError("Events must be a list")

                for event in data["events"]:
                    # Enforce the format: "Semester: Sem X | Branch: Y"
                    # This ensures the Calendar Conflict Checker (which parses this string) works 100%.
                    event["description"] = f"Semester: {sem} | Branch: {branch}"

                return data

            except Exception as e:
                error_str = str(e).lower()
                if "429" in error_str or "resource_exhausted" in error_str:
                    wait_time = 2 ** (attempt + 1)
                    print(f"⚠️ Quota hit. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                raise RuntimeError(f"Gemini Error: {e}")

        raise RuntimeError(f"Failed after {max_retries} retries due to API Quota.")

    def parse_event_request(self, user_input, availability_context=None):
        """
        Problem 2 & 4: Behaves like an intelligent assistant.
        Analyzes intent, explains clashes, and picks exactly 2 suggestions.
        """
        now = datetime.datetime.now(pytz.timezone(self.timezone))
        current_time_str = now.strftime("%Y-%m-%d %H:%M:%S %Z (%A)")

        context_str = ""
        if availability_context:
            context_str = f"\nCALENDAR CONTEXT:\n{availability_context}"

        prompt = f"""
        You are a University Event Planner assistant. 
        Current Time: {current_time_str}
        {context_str}

        TASK:
        Analyze the user input. 
        1. If clashes are listed in the CALENDAR CONTEXT, explain them clearly (Which class, Semester, and Time).
        2. If available slots are listed, suggest EXACTLY 2 of them.
        3. If no context is provided, extract the intent for a calendar search.

        RULES:
        - Output ONLY a structured JSON.
        - NO small talk. NO "Here is your request".
        - For suggestions, use the 'display' and 'start_iso'/'end_iso' provided in the context.

        JSON FORMAT:
        {{
            "explanation": "Clear explanation of clashes (if any) or a brief confirmation.",
            "intent": {{
                "event_name": "string",
                "duration_minutes": integer,
                "target_semesters": ["Sem 1", etc.] or "All"
            }},
            "suggestions": [
                {{ "display": "formatted time string", "start_iso": "...", "end_iso": "..." }}
            ]
        }}

        User Input: "{user_input}"
        """

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1
        )

        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config=config
            )
            return _safe_json_parse(response.text)
        except Exception as e:
            raise RuntimeError(f"Failed to parse event request: {e}")