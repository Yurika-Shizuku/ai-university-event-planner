import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

print("API KEY:", os.getenv("GOOGLE_API_KEY"))

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

for model in client.models.list():
    print(model.name)

