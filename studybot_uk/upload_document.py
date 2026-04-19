import os
import requests

API_KEY = os.getenv("ANTHROPIC_API_KEY")
DOCS_FOLDER = "/Users/ramesh/Downloads/GCSE_SCIENCE_MATHS"  # your local path




uploaded = {}  # filename → file_id

for filename in os.listdir(DOCS_FOLDER):
    if filename.endswith((".pdf", ".docx", ".txt")):
        filepath = os.path.join(DOCS_FOLDER, filename)
        with open(filepath, "rb") as f:
            resp = requests.post(
                "https://api.anthropic.com/v1/files",
                headers={
                    "x-api-key": API_KEY,
                    "anthropic-version": "2023-06-01",
                    "anthropic-beta": "files-api-2025-04-14"
                },
                files={"file": (filename, f, "application/pdf")},
                data={"purpose": "agent"}
            )
        print(f"Response: {resp.status_code}", resp.json())  # ← debug line
        if resp.status_code == 200:
            file_id = resp.json()["id"]
            uploaded[filename] = file_id
            print(f"✅ Uploaded: {filename} → {file_id}")
        else:
            print(f"❌ Failed: {filename} — {resp.json()}")

print("\nAll file IDs:", uploaded)