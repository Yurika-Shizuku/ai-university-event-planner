import os
import time
import json
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

    def extract_timetable_data(self, pdf_bytes):
        """
        Extracts timetable data directly from memory bytes.
        Includes Size Checks and Retry Logic.
        """
        # 1. Size Limit Check (Save Quota)
        if len(pdf_bytes) > 5 * 1024 * 1024:  # 5MB Limit
            raise ValueError("PDF is too large (>5MB). Please compress it.")

        prompt =  """
    Extract the weekly timetable and header metadata.
    Return JSON in this format ONLY:

    {
      "metadata": {
        "semester": "e.g., 4th Semester",
        "branch": "e.g., Information Technology"
      },
      "events": [
        {
          "summary": "...",
          "day": "Monday",
          "start_time": "HH:MM",
          "end_time": "HH:MM",
          "type": "static"
        }
      ]
    }
    """

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1
        )

        # 2. Retry Loop with Exponential Backoff
        max_retries = 1
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

                # Normalize and return
                data = _safe_json_parse(response.text)


                # 1. Ensure root is a dictionary
                if not isinstance(data, dict):
                    raise ValueError("AI response is not a JSON object")

                # 2. Fix Metadata Nesting: Ensure metadata exists and has defaults
                metadata = data.setdefault("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = data["metadata"] = {}

                data.setdefault("metadata", {})
                data["metadata"].setdefault("semester", "Unknown Semester")
                data["metadata"].setdefault("branch", "Unknown Branch")
                data.setdefault("events", [])

                # 3. Ensure events is a valid list
                data.setdefault("events", [])
                if not isinstance(data["events"], list):
                    raise ValueError("Events must be a list")

                return data


            except Exception as e:
                # Check for 429 / Resource Exhausted
                error_str = str(e).lower()
                if "429" in error_str or "resource_exhausted" in error_str:
                    wait_time = 2 ** attempt  # 2s, 4s, 8s
                    print(f"⚠️ Quota hit. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                # If it's another error, raise it immediately
                raise RuntimeError(f"Gemini Error: {e}")

        # If all retries fail
        raise RuntimeError("Failed after 3 retries due to API Quota.")