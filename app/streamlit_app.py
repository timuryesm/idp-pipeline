"""Streamlit ingestion UI — Step 1 of the IDP pipeline.

Run with:  streamlit run app/streamlit_app.py
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Make the project root importable when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion.ingestor import Ingestor  # noqa: E402
from config.settings import settings  # noqa: E402

st.set_page_config(page_title="IDP — Ingestion Layer", page_icon="📁", layout="wide")


@st.cache_resource
def get_ingestor() -> Ingestor:
    return Ingestor()


ingestor = get_ingestor()

st.title("📁 Invoice Ingestion Layer")
st.caption(
    f"Allowed: {', '.join(sorted(settings.ALLOWED_EXTENSIONS))}  ·  "
    f"Max size: {settings.MAX_FILE_SIZE_MB} MB per file"
)

uploaded = st.file_uploader(
    "Drop invoices here",
    type=["pdf", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
)

if st.button("Ingest documents", type="primary", disabled=not uploaded):
    records = [ingestor.ingest(f.name, f.getvalue()) for f in uploaded]

    accepted = sum(r.ok for r in records)
    rejected = len(records) - accepted

    c1, c2, c3 = st.columns(3)
    c1.metric("Total", len(records))
    c2.metric("Ingested", accepted)
    c3.metric("Rejected", rejected)

    table = pd.DataFrame(
        [
            {
                "Tracking ID": r.doc_id,
                "File": r.original_filename,
                "Status": r.status.value,
                "Type": r.content_type or "—",
                "Size (KB)": round(r.file_size_bytes / 1024, 1),
                "Detail": r.detail or "",
            }
            for r in records
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)
else:
    st.info("Upload one or more files, then click **Ingest documents**.")