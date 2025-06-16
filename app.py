# app.py

# --- ChromaDB System Hack ---
# This block must be at the very top of the file
# to ensure the correct sqlite3 version is loaded
# before chromadb is imported.
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
# --- End of Hack ---

import os
import streamlit as st
import pandas as pd
import chromadb
from sentence_transformers import SentenceTransformer

from database import SessionLocal, get_all_progress_items, FollowedTerm, CorrectionFlag
from ui_components import render_progress_card

# --- Page Configuration ---
st.set_page_config(
    page_title="The Synthesis Engine",
    page_icon="🧠",
    layout="wide"
)

# --- Caching and Resource Loading ---
# Cache resource-intensive objects like models and DB clients
@st.cache_resource
def get_embedding_model():
    print("Loading embedding model...")
    return SentenceTransformer('all-MiniLM-L6-v2')

@st.cache_resource
def get_chroma_client():
    print("Connecting to ChromaDB...")
    CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
    CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

# Cache data loading with a Time-To-Live (TTL) of 60 seconds
@st.cache_data(ttl=60)
def load_data():
    print("Loading data from PostgreSQL...")
    return get_all_progress_items()

# --- Initialization ---
model = get_embedding_model()
client = get_chroma_client()
progress_collection = client.get_or_create_collection(name="ai_progress")

all_data = load_data()

# --- Main App UI ---
st.title("🧠 The Synthesis Engine")
st.caption("AI-Powered Summaries & Rankings of AI Progress. Continuously Updated.")

if not all_data:
    st.warning("The database is currently empty. Please wait for the scraper and workers to populate it with data.")
    st.stop()

# Prepare DataFrame for filtering
df = pd.DataFrame(all_data)
df['id'] = df['id'].astype(str)
df['published_date'] = pd.to_datetime(df['published_date'])


# --- Sidebar for Controls & Personalization ---
with st.sidebar:
    st.header("Filters & Controls")
    if st.button("Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    # --- Search and Filter Section ---
    st.subheader("Search")
    semantic_query = st.text_input("Search for concepts (e.g., 'alternatives to transformers')")
    search_term = st.text_input("Filter results by keyword")
    
    # --- Sorting Options ---
    sort_options = ["Importance Score", "Date"]
    if semantic_query:
        sort_options.insert(0, "Relevance") # Add Relevance option only when active
    sort_key = st.selectbox("Sort by", options=sort_options, index=0)
    
    # --- Source Filtering ---
    st.subheader("Filter by Source")
    all_sources = sorted(df['source'].unique())
    selected_sources = st.multiselect("Sources", options=all_sources, default=all_sources)

    # --- Personalization Section ---
    st.divider()
    st.header("My Feed")
    db = SessionLocal()
    try:
        followed_terms = [row.term for row in db.query(FollowedTerm.term).all()]
        st.write("Following:", f"`{', '.join(followed_terms)}`" if followed_terms else "Nothing yet.")
        
        with st.form("follow_form"):
            new_term = st.text_input("Follow a new keyword/author:")
            submitted = st.form_submit_button("Follow Term")
            if submitted and new_term:
                term_exists = db.query(FollowedTerm).filter(FollowedTerm.term == new_term.lower()).first()
                if not term_exists:
                    db.add(FollowedTerm(term=new_term.lower()))
                    db.commit()
                    st.rerun()
    finally:
        db.close()


# --- Main Content Area with Tabs ---
tab_all, tab_feed = st.tabs(["🔥 All Progress", "👤 My Feed"])


# --- "All Progress" Tab Logic ---
with tab_all:
    # 1. Start with the full dataframe
    results_df = df

    # 2. Apply Semantic Search (if used)
    if semantic_query:
        with st.spinner("Searching for semantically similar items..."):
            query_embedding = model.encode(semantic_query).tolist()
            results = progress_collection.query(query_embeddings=[query_embedding], n_results=20)
            relevant_ids = results['ids'][0]
            if not relevant_ids:
                st.warning("Semantic search returned no results.")
                results_df = pd.DataFrame() # Empty dataframe
            else:
                results_df = df[df['id'].isin(relevant_ids)].copy()
                relevance_scores = {id_str: dist for id_str, dist in zip(results['ids'][0], results['distances'][0])}
                results_df['relevance'] = results_df['id'].map(relevance_scores)

    # 3. Apply Standard Filters to the (potentially semantically filtered) dataframe
    if selected_sources:
        results_df = results_df[results_df['source'].isin(selected_sources)]
    if search_term:
        term_lower = search_term.lower()
        results_df = results_df[results_df['title'].str.lower().str.contains(term_lower)]

    # 4. Apply Sorting
    if sort_key == "Relevance" and 'relevance' in results_df.columns:
        sorted_df = results_df.sort_values('relevance', ascending=True)
    elif sort_key == "Importance Score":
        sorted_df = results_df.sort_values('overall_importance_score', ascending=False)
    else: # Sort by Date
        sorted_df = results_df.sort_values('published_date', ascending=False)

    # 5. Display Results
    st.subheader(f"Showing {len(sorted_df)} breakthroughs")
    if sorted_df.empty:
        st.info("No results match your criteria.")
    else:
        for _, item in sorted_df.iterrows():
            card_container = st.container(border=True)
            render_progress_card(item.to_dict(), card_container)

            # Logic for the "Flag for Review" form
            if st.session_state.get("flagging_item_id") == item['id']:
                with st.form(key=f"form_{item['id']}"):
                    st.warning(f"Flagging: {item['title']}")
                    reason = st.selectbox("Reason:", ["Inaccurate Summary", "Incorrect Score", "Misleading Title", "Other"])
                    comment = st.text_area("Optional Comment:")
                    submitted = st.form_submit_button("Submit Flag")
                    if submitted:
                        db = SessionLocal()
                        try:
                            new_flag = CorrectionFlag(item_id=int(item['id']), reason=reason, user_comment=comment)
                            db.add(new_flag)
                            db.commit()
                            st.success("Flag submitted for review. Thank you!")
                        finally:
                            db.close()
                        del st.session_state.flagging_item_id
                        st.rerun()


# --- "My Feed" Tab Logic ---
with tab_feed:
    if not followed_terms:
        st.info("You are not following any terms. Add some in the sidebar to create your personalized feed.")
    else:
        # Filter the main dataframe for items matching any followed term
        # Using a regex pattern for efficient matching
        pattern = '|'.join(followed_terms)
        my_feed_df = df[
            df['title'].str.lower().str.contains(pattern) |
            df['keywords'].astype(str).str.lower().str.contains(pattern)
        ].sort_values('published_date', ascending=False)
        
        st.subheader(f"Found {len(my_feed_df)} items related to your interests")
        if my_feed_df.empty:
            st.write("No recent progress matches your followed terms.")
        else:
            for _, item in my_feed_df.iterrows():
                card_container = st.container(border=True)
                render_progress_card(item.to_dict(), card_container)