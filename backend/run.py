"""`python run.py` — binds to localhost by default (see PROXY_HOST)."""
import uvicorn

from app.config import get_settings

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run("app.main:app", host=s.host, port=s.port, proxy_headers=True)
