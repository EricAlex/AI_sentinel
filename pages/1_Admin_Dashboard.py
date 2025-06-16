# pages/1_Admin_Dashboard.py

import os
import streamlit as st
import pandas as pd
from health import get_celery_stats, get_db_status, get_redis_status, get_system_usage
from database import SessionLocal, CorrectionFlag, ProgressItem
from dotenv import load_dotenv

load_dotenv()

# --- Page Configuration and Authentication ---
st.set_page_config(page_title="System Dashboard", layout="wide", page_icon="⚙️")
st.title("⚙️ System Health & Governance")

# Simple password protection for the admin page
password = st.text_input("Enter Admin Password", type="password")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

if password != ADMIN_PASSWORD:
    st.error("Incorrect password. Access denied.")
    st.stop()

st.success("Access Granted. Welcome, Admin.")

# --- Tabbed Interface for Organization ---
tab1, tab2 = st.tabs(["📊 Health Dashboard", "🚩 Flag Review"])

# --- Health Dashboard Tab ---
with tab1:
    st.header("Live System Status")
    
    # Add a refresh button to get the latest stats
    if st.button("Refresh Stats"):
        st.rerun()

    # Display Service Status
    st.subheader("Core Infrastructure")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("PostgreSQL DB", get_db_status())
    with col2:
        st.metric("Redis Broker", get_redis_status())
    with col3:
        celery_stats = get_celery_stats()
        st.metric("Celery Service", celery_stats.get('status', 'Error'))

    # Display Celery Worker Stats
    if celery_stats.get('status') == 'Online':
        st.subheader("Background Processing")
        c1, c2, c3 = st.columns(3)
        c1.metric("Active Workers", celery_stats.get('active_workers', 0))
        c2.metric("Tasks in Progress", celery_stats.get('tasks_in_progress', 0))
        c3.metric("Total Tasks Processed", celery_stats.get('total_tasks_processed', 0))

    # Display Host System Usage
    st.subheader("Host System Usage")
    usage = get_system_usage()
    s1, s2 = st.columns(2)
    s1.metric("CPU Usage", f"{usage['cpu_percent']}%")
    s2.metric("Memory Usage", f"{usage['memory_percent']}%")


# --- Flag Review Tab ---
with tab2:
    st.header("Content Governance: Pending Flags")
    db = SessionLocal()
    try:
        # Query for pending flags and join with the related progress item to get its title
        pending_flags = db.query(CorrectionFlag, ProgressItem).join(
            ProgressItem, CorrectionFlag.item_id == ProgressItem.id
        ).filter(CorrectionFlag.status == 'pending').order_by(CorrectionFlag.created_at.desc()).all()

        if not pending_flags:
            st.success("No pending flags to review. All content is clear!")
        else:
            st.info(f"You have {len(pending_flags)} items to review.")
            for flag, item in pending_flags:
                with st.container(border=True):
                    st.subheader(f"Flag for: *{item.title}*")
                    st.write(f"**Reason:** {flag.reason}")
                    if flag.user_comment:
                        st.write(f"**User Comment:** {flag.user_comment}")
                    st.caption(f"Flagged on: {flag.created_at.strftime('%Y-%m-%d %H:%M')} UTC")

                    b_col1, b_col2 = st.columns(2)
                    with b_col1:
                        if st.button("Mark as Resolved", key=f"resolve_{flag.id}", use_container_width=True):
                            flag_to_update = db.query(CorrectionFlag).get(flag.id)
                            flag_to_update.status = 'resolved'
                            db.commit()
                            st.rerun()
                    with b_col2:
                        if st.button("Delete Flag", key=f"delete_{flag.id}", type="primary", use_container_width=True):
                            flag_to_delete = db.query(CorrectionFlag).get(flag.id)
                            db.delete(flag_to_delete)
                            db.commit()
                            st.rerun()
    finally:
        db.close()