import httpx
import re

OLLAMA_URL = "http://ollama:11434"

async def get_pull_progress():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            tags = await client.get(f"{OLLAMA_URL}/api/tags")
            if tags.status_code == 200:
                data = tags.json()
                if data.get("models"):
                    return {"progress": 100}

            logs = await client.get(f"{OLLAMA_URL}/api/ps")
            text = logs.text

            match = re.search(r'(\d+)%', text)
            if match:
                return {"progress": int(match.group(1))}

    except Exception:
        pass

    return {"progress": 0}