# StudyBot UK — GCSE Revision App

A local AI-powered revision tool for GCSE students (CCEA syllabus).  
Supports **Chemistry**, **Physics**, **Maths M4** and **Maths M8**.

Built with FastAPI · ChromaDB · DuckDB · PyMuPDF · Anthropic Claude API

---

## Features

| Feature | Description |
|---|---|
| 📚 **Document Indexing** | Upload GCSE PDFs (text, numbers, images, maths symbols). Indexed into ChromaDB for semantic search |
| 🧪 **Quiz Generator** | Generate 10 / 15 / 20 / 30 / 50 questions on any topic, sourced from your documents |
| ✅ **Answer Checking** | Each answer is marked by Claude with explanation + memory tip if wrong |
| 🃏 **Flashcards** | Auto-generated flip cards grounded in your uploaded documents |
| 📝 **Revision Notes** | CCEA unit-by-unit notes — click a unit or drill into a specific topic |
| 🔍 **Subject Filter** | One global subject selector (Chemistry / Physics / Maths M4 / Maths M8) shared across all tabs |

---

## Prerequisites

- Python 3.9 or higher
- An [Anthropic API key](https://console.anthropic.com/)
- Git

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/rameshgummada/studybot_uk.git
cd studybot_uk
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> First run downloads the ChromaDB embedding model (~90 MB). Requires internet access.

### 4. Set your Anthropic API key

```bash
# macOS / Linux
export ANTHROPIC_API_KEY=sk-ant-api03-your-key-here

# Windows (Command Prompt)
set ANTHROPIC_API_KEY=sk-ant-api03-your-key-here

# Windows (PowerShell)
$env:ANTHROPIC_API_KEY="sk-ant-api03-your-key-here"
```

Or create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```

### 5. (Optional) Configure your PDF folders

Edit the `SUBJECT_FOLDERS` dictionary in `indexer.py` to point to your local GCSE PDF folders:

```python
SUBJECT_FOLDERS = {
    "chemistry": "/path/to/your/Chemistry",
    "physics":   "/path/to/your/Physics",
    "maths_m4":  "/path/to/your/Maths",
    "maths_m8":  "/path/to/your/Maths",
}
```

### 6. Index your documents

```bash
python indexer.py
```

This scans the configured folders, extracts text from each PDF and stores chunks in ChromaDB.  
You can skip this step and upload PDFs manually via the web UI instead.

### 7. Start the server

```bash
python -m uvicorn app:app --reload --port 8000
```

### 8. Open the app

Navigate to [http://localhost:8000](http://localhost:8000)

---

## Usage

### Subject Selection
Select your subject (**Chemistry / Physics / Maths M4 / Maths M8**) from the dark bar at the top. This applies to all tabs.

### Quiz Tab
1. Choose number of questions: **10 / 15 / 20 / 30 / 50**
2. Optionally enter a topic (e.g. *Rates of Reaction*, *Quadratic Equations*)
3. Click **Generate Quiz**
4. Answer all questions then click **Submit All & Check**
5. Each wrong answer shows the correct answer, a full explanation and a memory tip

### Flashcards Tab
1. Optionally enter a topic
2. Click **Load Flashcards**
3. Click any card to flip it

### Notes Tab
1. Units for the selected subject load automatically (CCEA syllabus)
2. Click any **Unit** → full revision notes appear instantly
3. Click any **topic pill** at the top of the notes for focused notes on that specific topic
4. Use the **Print** button to print or save as PDF

### Upload Tab
Upload your own GCSE PDFs to index them for quiz and flashcard generation.  
The selected subject from the top bar is used automatically.

---

## Project Structure

```
studybot_uk/
├── app.py              # FastAPI app — all routes and web UI
├── indexer.py          # PDF ingestion → ChromaDB + DuckDB
├── upload_document.py  # Standalone script to bulk-upload PDFs
├── requirements.txt    # Python dependencies
├── .env.example        # Template for environment variables
├── chroma_db/          # ChromaDB vector store (auto-created, gitignored)
└── studybot.duckdb     # DuckDB metadata database (auto-created, gitignored)
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web UI |
| `POST` | `/upload` | Upload and index a PDF |
| `POST` | `/ingest/all` | Re-index all PDFs from configured folders |
| `GET` | `/curriculum/{subject}` | CCEA unit and topic structure |
| `POST` | `/quiz/generate` | Generate quiz questions |
| `POST` | `/quiz/answer` | Check a student answer |
| `GET` | `/flashcards/{subject}` | Generate flashcards |
| `GET` | `/notes/{subject}` | Generate revision notes |
| `GET` | `/stats` | Index statistics |

---

## Troubleshooting

**`RuntimeError: Set ANTHROPIC_API_KEY environment variable`**  
→ Export your API key as shown in Step 4.

**`Address already in use` on port 8000**  
```bash
kill $(lsof -ti :8000)
python -m uvicorn app:app --reload --port 8000
```

**ChromaDB embedding model not downloading**  
→ Ensure you have internet access on first run. The model (~90 MB) is cached locally after that.

**PDF shows no chunks after indexing**  
→ The PDF may be image-only (scanned). PyMuPDF can only extract selectable text. Try a text-based PDF.

---

## Requirements

```
fastapi
uvicorn
anthropic
chromadb
duckdb
pymupdf
python-multipart
```
