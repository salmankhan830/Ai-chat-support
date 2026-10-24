from google import genai
from decouple import config

Client = genai.Client(api_key=config("GEMINI_API_KEY"))

response= Client.models.generate_content(
    model=config("GEMINI_MODEL"),
    contents="give me 5 names of animals",
)

print(response.text)