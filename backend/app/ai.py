import json

from fastapi import HTTPException
from groq import Groq

from app.config import GROQ_API_KEY
from app.flashcards import MODEL
from app.trace import traced_create


def chat_json(system: str, user: str, *, max_tokens: int = 8000, label: str = "chat") -> dict:
    """One Groq call that must answer with a JSON object. Raises HTTP 502 if the call or the JSON fails."""
    if not GROQ_API_KEY or GROQ_API_KEY.startswith(("paste-", "your-")):
        raise HTTPException(status_code=500, detail="GROQ_API_KEY is not set in backend/.env")
    try:
        client = Groq(api_key=GROQ_API_KEY, max_retries=6)
        completion = traced_create(
            client,
            label,
            model=MODEL,
            temperature=0.2,
            max_completion_tokens=max_tokens,
            reasoning_effort="low",
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        data = json.loads(completion.choices[0].message.content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI request failed: {type(e).__name__}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="AI returned an unexpected answer. Please try again.")
    return data
