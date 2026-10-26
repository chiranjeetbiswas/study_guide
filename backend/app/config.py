import os

from dotenv import load_dotenv

# Reads backend/.env and puts its values into environment variables
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Model for the fact-checking reviewer (verify.py). Unset: the same model that writes the answers. A different model is a
# more independent second opinion, and Groq counts the rate limit per model, so the load is split between the two.
REVIEW_MODEL = os.getenv("REVIEW_MODEL") or None

# e.g. mongodb://localhost:27017 or mongodb+srv://user:password@cluster.mongodb.net
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
MONGODB_DB = os.getenv("MONGODB_DB", "study_guide")

# Websites allowed to call this API (browser CORS check). Comma-separated, no trailing slash, e.g.
# https://my-frontend.onrender.com. The local dev frontend is always allowed.
FRONTEND_ORIGINS = ["http://localhost:3001"] + [
    o.strip().rstrip("/") for o in os.getenv("FRONTEND_ORIGIN", "").split(",") if o.strip()
]

# Signs login tokens. Anyone who knows it can forge a login, so it must be long, random and secret.
JWT_SECRET = os.getenv("JWT_SECRET", "")
if len(JWT_SECRET) < 32:
    raise RuntimeError(
        "JWT_SECRET is missing or too short (need 32+ characters). Generate one with:\n"
        '  python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
        "and add it to backend/.env as JWT_SECRET=..."
    )
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # default: 24 hours
