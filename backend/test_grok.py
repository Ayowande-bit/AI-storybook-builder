
# Import the libraries we need.
import os
from dotenv import load_dotenv
from groq import Groq

# Load the API key from backend/.env.
load_dotenv()

# Read the Groq API key.
api_key = os.getenv("GROQ_API_KEY")

# Stop if the API key is missing.
if not api_key:
    raise ValueError("GROQ_API_KEY was not found.")

# Connect to Groq using its official SDK.
client = Groq(api_key=api_key)

# Ask the model to generate a short children's story.
response = client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[
        {
            "role": "system",
            "content": (
                "You create gentle, age-appropriate children's "
                "stories that teach positive values."
            ),
        },
        {
            "role": "user",
            "content": (
                "Write a short story about a little rabbit "
                "who learns to share. Include a title and lesson."
            ),
        },
    ],
)

# Print the generated story.
print(response.choices[0].message.content)
