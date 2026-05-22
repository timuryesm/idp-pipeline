# 🧾 Intelligent Invoice & Document Processing Pipeline (IDP)

A production-grade pipeline that ingests invoices (PDF/image), extracts structured
data with AI, validates it against strict business rules, and surfaces analytics —
with a human-in-the-loop review queue for anything that fails validation.

## Architecture

```
[ Ingestion ] 📁  →  [ AI Extraction ] 🧠  →  [ Validation (Pydantic) ] ✅
                                                       │
                                  success ─────────────┼───────────── mismatch
                                       ▼                                 ▼
                              [ Analytics DB ] 📊              [ Human Review ] ⚠️
```

## Tech stack

| Layer        | Choice                                            |
|--------------|---------------------------------------------------|
| Logic        | Python                                            |
| UI / Dashboard | Streamlit                                       |
| Extraction   | `pdfplumber` / multimodal LLM (`gpt-4o-mini`, `gemini-1.5-flash`) |
| Validation   | Pydantic v2                                        |
| Storage      | SQLite → PostgreSQL                                |

## Build roadmap

- [x] **Step 1 — Secure ingestion layer** ← *you are here*
- [ ] Step 2 — AI extraction layer (structured JSON output)
- [ ] Step 3 — Pydantic business-logic validator (math + date cross-checks)
- [ ] Step 4 — Analytics dashboard + review queue

---

## Step 1 — Secure Ingestion Layer ✅

Accepts one or many files and, for each, runs five validation gates before
assigning a UUID tracking ID and storing the file safely.

**Validation gates** (`src/ingestion/validator.py`)
1. Size floor — rejects empty/corrupt files.
2. Size ceiling — rejects oversized uploads (default 10 MB, configurable).
3. Extension allow-list — only `.pdf`, `.png`, `.jpg`, `.jpeg`.
4. Magic-byte sniffing — reads the real content type from the file header.
5. Spoof check — the real bytes must match the declared extension
   (a PNG renamed `invoice.pdf` is rejected).

**Other enterprise touches**
- UUIDv4 tracking ID per document; stored as `{uuid}__{sanitized_name}` so two
  files named `invoice.pdf` never collide.
- Filename sanitization strips path components (`../../etc/passwd` → `passwd`).
- Every stage logged to console **and** a rotating file (`logs/idp.log`).
- Zero hardcoded config — everything via env vars / `.env`.
- `ingest()` never throws on bad input; invalid files return a `REJECTED`
  `DocumentRecord` for the caller to handle.

### Project layout
```
idp-pipeline/
├── app/streamlit_app.py        # upload UI
├── config/settings.py          # env-driven config
├── src/
│   ├── ingestion/
│   │   ├── models.py           # DocumentRecord + enums
│   │   ├── validator.py        # the 5 gates
│   │   └── ingestor.py         # orchestration + storage
│   └── utils/logger.py         # console + rotating file logging
├── tests/test_ingestion.py     # 11 unit tests
├── storage/{uploads,quarantine}/
├── requirements.txt
├── .env.example
└── .gitignore
```

### Run it
```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# Launch the upload UI
streamlit run app/streamlit_app.py

# Run the tests
pytest -q
```

### Configuration (`.env`)
| Variable                 | Default | Purpose                       |
|--------------------------|---------|-------------------------------|
| `IDP_MAX_FILE_SIZE_MB`   | `10`    | Per-file size ceiling         |
| `IDP_MIN_FILE_SIZE_BYTES`| `100`   | Empty/corrupt floor           |
| `IDP_LOG_LEVEL`          | `INFO`  | Logging verbosity             |
| `IDP_UPLOAD_DIR`         | `storage/uploads` | Where valid files land |
