"""IDP Pipeline dashboard.

Run with:  streamlit run app/streamlit_app.py
"""
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

# Make the project root importable when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pymupdf
import streamlit as st

from config.settings import settings
from src.persistence.repository import InvoiceRepository
from src.pipeline import process_document
from src.validation.validator import validate

st.set_page_config(page_title="IDP Pipeline", page_icon="🧾", layout="wide")


@st.cache_resource
def get_repo() -> InvoiceRepository:
    return InvoiceRepository()


repo = get_repo()


def _parse_date(text: str):
    text = text.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _original_preview(doc_id: str):
    """Return image bytes/path for the stored original, or None."""
    stored = next(settings.UPLOAD_DIR.glob(f"{doc_id}__*"), None)
    if stored is None:
        return None
    if stored.suffix.lower() == ".pdf":
        with pymupdf.open(stored) as d:
            return d[0].get_pixmap(dpi=120).tobytes("png")
    return str(stored)


st.title("🧾 Invoice Processing Pipeline")
queue_tab, insights_tab = st.tabs(["📥 Pipeline Queue", "📊 Financial Insights"])

with queue_tab:
    # ---- Upload & process --------------------------------------------------
    st.subheader("Upload invoices")
    uploaded = st.file_uploader(
        "Drop PDFs or images", type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )
    if st.button("Process", type="primary", disabled=not uploaded):
        results = [process_document(f.name, f.getvalue(), repo=repo) for f in uploaded]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Processed", len(results))
        c2.metric("Approved", sum(r.status == "APPROVED" for r in results))
        c3.metric("Needs review", sum(r.status == "NEEDS_REVIEW" for r in results))
        c4.metric("Rejected", sum(r.status == "REJECTED" for r in results))
        for r in results:
            if r.status == "REJECTED":
                st.error(f"**{r.original_filename}** — rejected: {r.detail}")
            elif r.status == "NEEDS_REVIEW":
                st.warning(f"**{r.original_filename}** — needs review: {r.detail}")
            else:
                st.success(f"**{r.original_filename}** — approved")

    # ---- Processed-invoices table -----------------------------------------
    st.divider()
    st.subheader("Processed invoices")
    summaries = repo.list_summaries()
    if not summaries:
        st.info("No invoices processed yet. Upload some above to get started.")
    else:
        df = pd.DataFrame([{
            "Status": s.status.value,
            "File": s.original_filename,
            "Vendor": s.vendor_name or "—",
            "Total": (f"{s.currency or ''} {s.grand_total}".strip()
                      if s.grand_total is not None else "—"),
            "Invoice date": s.invoice_date.isoformat() if s.invoice_date else "—",
            "Errors": s.error_count,
            "Processed": s.processed_at.strftime("%Y-%m-%d %H:%M"),
            "Doc ID": s.doc_id,
        } for s in summaries])
        st.dataframe(df, width="stretch", hide_index=True)

        # ---- Review & correct ---------------------------------------------
        st.divider()
        st.subheader("Review & correct")
        options = {f"{s.original_filename} — {s.status.value}": s.doc_id for s in summaries}
        label = st.selectbox("Select an invoice to review", list(options.keys()))
        record = repo.get(options[label])
        if record:
            ext, val = record.extracted, record.validation
            col_doc, col_form = st.columns([1, 1])

            with col_doc:
                st.markdown("**Original document**")
                preview = _original_preview(record.doc_id)
                if preview is None:
                    st.caption("Original file not found on disk.")
                else:
                    st.image(preview)

            with col_form:
                st.markdown(f"**Current status:** {val.status.value}")
                for i in val.issues:
                    (st.error if i.severity.value == "ERROR" else st.warning)(
                        f"`{i.code}` — {i.message}")

                with st.form(f"review_{record.doc_id}"):
                    vendor = st.text_input("Vendor", ext.vendor_name or "")
                    inv_no = st.text_input("Invoice number", ext.invoice_number or "")
                    d1, d2 = st.columns(2)
                    inv_date = d1.text_input("Invoice date (YYYY-MM-DD)",
                                             ext.invoice_date.isoformat() if ext.invoice_date else "")
                    due_date = d2.text_input("Due date (YYYY-MM-DD)",
                                             ext.due_date.isoformat() if ext.due_date else "")
                    currency = st.text_input("Currency", ext.currency or "")
                    m1, m2 = st.columns(2)
                    subtotal = m1.number_input("Subtotal", value=float(ext.subtotal or 0), step=0.01, format="%.2f")
                    shipping = m2.number_input("Shipping", value=float(ext.shipping or 0), step=0.01, format="%.2f")
                    discount = m1.number_input("Discount", value=float(ext.discount or 0), step=0.01, format="%.2f")
                    adjustments = m2.number_input("Adjustments", value=float(ext.adjustments or 0), step=0.01, format="%.2f")
                    tax = m1.number_input("Tax", value=float(ext.tax_amount or 0), step=0.01, format="%.2f")
                    grand_total = m2.number_input("Grand total", value=float(ext.grand_total or 0), step=0.01, format="%.2f")
                    submitted = st.form_submit_button("Re-validate & save", type="primary")

                if ext.line_items:
                    st.caption("Line items (read-only)")
                    st.dataframe(pd.DataFrame([li.model_dump() for li in ext.line_items]),
                                 width="stretch", hide_index=True)

                if submitted:
                    corrected = ext.model_copy(update={
                        "vendor_name": vendor or None,
                        "invoice_number": inv_no or None,
                        "invoice_date": _parse_date(inv_date),
                        "due_date": _parse_date(due_date),
                        "currency": currency or None,
                        "subtotal": Decimal(str(subtotal)),
                        "shipping": Decimal(str(shipping)),
                        "discount": Decimal(str(discount)),
                        "adjustments": Decimal(str(adjustments)),
                        "tax_amount": Decimal(str(tax)),
                        "grand_total": Decimal(str(grand_total)),
                        "notes": ext.notes + ["Manually reviewed and corrected."],
                    })
                    new_val = validate(corrected)
                    repo.save(corrected, new_val, record.original_filename)
                    if new_val.status.value == "APPROVED":
                        st.success("Saved — now **APPROVED** ✅  (reselect or re-run to refresh the table)")
                    else:
                        remaining = "; ".join(i.message for i in new_val.errors)
                        st.warning(f"Saved — still **NEEDS_REVIEW**. Remaining: {remaining}")

with insights_tab:
    insights = repo.list_summaries()
    if not insights:
        st.info("No data yet. Process some invoices in the Pipeline Queue tab first.")
    else:
        df = pd.DataFrame([{
            "vendor": s.vendor_name or "Unknown",
            "total": float(s.grand_total) if s.grand_total is not None else None,
            "status": s.status.value,
            "invoice_date": s.invoice_date,
        } for s in insights])

        total_n = len(df)
        approved_n = int((df["status"] == "APPROVED").sum())
        approval_rate = approved_n / total_n * 100 if total_n else 0
        spend = df["total"].dropna()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Invoices", total_n)
        c2.metric("Approval rate", f"{approval_rate:.0f}%")
        c3.metric("Total spend", f"{spend.sum():,.2f}")
        c4.metric("Avg invoice", f"{spend.mean():,.2f}" if not spend.empty else "—")

        st.divider()
        left, right = st.columns(2)
        with left:
            st.markdown("**Status breakdown**")
            st.bar_chart(df["status"].value_counts())
        with right:
            st.markdown("**Spend by vendor**")
            by_vendor = (df.dropna(subset=["total"])
                           .groupby("vendor")["total"].sum().sort_values(ascending=False))
            st.bar_chart(by_vendor)

        dated = df.dropna(subset=["total", "invoice_date"]).copy()
        if not dated.empty:
            st.markdown("**Spend over time (by invoice month)**")
            dated["month"] = pd.to_datetime(dated["invoice_date"]).dt.to_period("M").astype(str)
            st.line_chart(dated.groupby("month")["total"].sum())