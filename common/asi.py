import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

asi_client = OpenAI(
    base_url="https://api.asi1.ai/v1",
    api_key=os.getenv("ASI_ONE_API_KEY"),
)


def asi_chat(system: str, user: str, max_tokens: int = 1024) -> str:
    """Single-call helper hitting ASI:One. Used by every swarm-* agent."""
    r = asi_client.chat.completions.create(
        model="asi1-extended",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    return r.choices[0].message.content
