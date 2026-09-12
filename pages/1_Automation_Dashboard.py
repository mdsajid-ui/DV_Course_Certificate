"""
Automation Dashboard
=====================
Read-only view over cert_store.db so you can see, at a glance, whether the
auto_processor.py background job is keeping up: how many certificates were
sent, how many failed (and why), and which sheet rows couldn't even be
attempted (missing email, duplicate certificate number, etc).

This is a separate Streamlit page (Streamlit's standard `pages/` convention)
so it shows up as its own entry in the sidebar next to the existing tabs in
app.py — nothing in app.py needed to change.

Run alongside the rest of the app:
    streamlit run app.py
then open "Automation Dashboard" in the left sidebar.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import cert_store

st.set_page_config(page_title="Automation Dashboard", page_icon="\U0001F4CA", layout="wide")
st.title("\U0001F4CA Certificate Automation Dashboard")
st.caption("Live view of cert_store.db — refresh after auto_processor.py runs a poll.")

if st.button("\U0001F504 Refresh"):
    st.rerun()

records = cert_store.list_all_certificates()
skipped = cert_store.list_skipped_rows()

total = len(records)
sent = sum(1 for r in records if r.email_status == "SENT")
failed = sum(1 for r in records if r.email_status == "FAILED")
pending = sum(1 for r in records if r.email_status == "PENDING")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total certificates issued", total)
col2.metric("\u2705 Sent", sent)
col3.metric("\u274C Failed", failed)
col4.metric("\u23F3 Pending", pending)
col5.metric("\u26A0\uFE0F Skipped rows", len(skipped))

st.divider()

if failed:
    st.subheader("\u274C Failed sends — will auto-retry next poll")
    failed_rows = [
        {
            "Name": r.name,
            "Email": r.email,
            "Certificate No": r.cert_number,
            "Last attempt": r.last_attempt_at,
            "Error": r.last_error,
        }
        for r in records
        if r.email_status == "FAILED"
    ]
    st.dataframe(pd.DataFrame(failed_rows), use_container_width=True, hide_index=True)
else:
    st.success("No failed sends right now.")

if skipped:
    st.subheader("\u26A0\uFE0F Sheet rows the automation couldn't attempt — needs a manual fix")
    st.dataframe(pd.DataFrame(skipped), use_container_width=True, hide_index=True)

st.subheader("All certificates")
all_rows = [
    {
        "Name": r.name,
        "Email": r.email,
        "Certificate No": r.cert_number,
        "Status": r.email_status,
        "Sent count": r.send_count,
        "Last sent": r.last_sent_at,
        "Issued": r.created_at,
    }
    for r in records
]
st.dataframe(pd.DataFrame(all_rows), use_container_width=True, hide_index=True)
