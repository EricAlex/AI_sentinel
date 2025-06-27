# app.py

# --- ChromaDB System Hack ---
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
# --- End of Hack ---

import os
import math
import re
import streamlit as st
import pandas as pd
import chromadb
from sentence_transformers import SentenceTransformer

# Import all necessary functions from our other modules
from database import (
    SessionLocal,
    get_all_progress_items,
    FollowedTerm,
    CorrectionFlag,
    delete_followed_term  # Import the new delete function
)
from ui_components import render_progress_card

# --- 1. Page Configuration ---
st.set_page_config(
    page_title="The AI Progress Sentinel",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- 2. Caching and Resource Loading ---
LOCAL_MODEL_PATH = '/app/models/all-MiniLM-L6-v2'

@st.cache_resource
def get_embedding_model():
    print("Loading embedding model from local path...")
    return SentenceTransformer(LOCAL_MODEL_PATH)

@st.cache_resource
def get_chroma_client():
    print("Connecting to ChromaDB...")
    CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
    CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

@st.cache_data(ttl=60)
def load_data():
    print("Loading data from PostgreSQL...")
    return get_all_progress_items()

# --- 3. Initialization ---
model = get_embedding_model()
client = get_chroma_client()
progress_collection = client.get_or_create_collection(name="ai_progress")
all_data = load_data()

# Initialize session state for BOTH tabs' pagination independently
if "all_progress_page" not in st.session_state:
    st.session_state.all_progress_page = 1
if "my_feed_page" not in st.session_state:
    st.session_state.my_feed_page = 1
if "page_size" not in st.session_state:
    st.session_state.page_size = 10

# Persistent Language State Logic
LANGUAGES = {'English': 'en', '中文 (Chinese)': 'zh'}
query_params = st.query_params.to_dict()
initial_lang_code = query_params.get("lang", "en")
if initial_lang_code not in LANGUAGES.values():
    initial_lang_code = 'en'
st.session_state.display_language = initial_lang_code

# --- 4. Sidebar ---
with st.sidebar:
    st.header("Display Options")
    
    def language_changed():
        selected_name = st.session_state.language_selector_key
        new_lang_code = LANGUAGES[selected_name]
        st.session_state.display_language = new_lang_code
        st.query_params.lang = new_lang_code

    current_lang_name = next((name for name, code in LANGUAGES.items() if code == st.session_state.display_language), 'English')
    lang_names = list(LANGUAGES.keys())
    current_index = lang_names.index(current_lang_name)

    st.selectbox("Display Language:", options=lang_names, index=current_index, key="language_selector_key", on_change=language_changed)

    st.divider()
    st.header("Filters & Controls")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.session_state.all_progress_page = 1
        st.session_state.my_feed_page = 1
        st.rerun()

    st.subheader("Search")
    semantic_query = st.text_input("Search for concepts...", placeholder="e.g., efficient transformers")
    search_term = st.text_input("Filter results by keyword...", placeholder="e.g., mamba")
    
    sort_options = ["Importance Score", "Date"]
    if semantic_query:
        sort_options.insert(0, "Relevance")
    sort_key = st.selectbox("Sort by", options=sort_options, index=0)
    
    all_sources = sorted(list(set(item['source'] for item in all_data))) if all_data else []
    selected_sources = st.multiselect("Filter by Source", options=all_sources, default=all_sources)

    st.divider()
    st.header("Paging")
    st.number_input("Items per page:", min_value=5, max_value=50, step=5, key="page_size")

    # --- Term Management UI ---
    st.divider()
    st.header("Manage My Feed")
    db = SessionLocal()
    try:
        followed_terms = [row.term for row in db.query(FollowedTerm.term).all()]
        if not followed_terms:
            st.caption("Not following any terms yet.")
        else:
            for term in followed_terms:
                term_col, button_col = st.columns([4, 1])
                term_col.write(f"• `{term}`")
                if button_col.button("❌", key=f"delete_term_{term}", help=f"Stop following '{term}'"):
                    delete_followed_term(term)
                    st.rerun()
        
        with st.form("follow_form", clear_on_submit=True):
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


# --- 5. Main App ---
st.title("🧠 The AI Progress Sentinel")
st.caption("AI-Powered Summaries & Rankings of AI Progress. Continuously Updated.")

if not all_data:
    st.warning("The database is currently empty. Please wait for the scraper to populate it.")
    st.stop()

df = pd.DataFrame(all_data)
df['id'] = df['id'].astype(str)
df['published_date'] = pd.to_datetime(df['published_date'], errors='coerce')


# --- Reusable Display Function ---
def process_and_display_feed(input_df: pd.DataFrame, tab_key_prefix: str):
    page_number_key = f"{tab_key_prefix}_page"
    
    # Filtering Logic
    results_df = input_df
    if semantic_query:
        with st.spinner("Performing semantic search..."):
            query_embedding = model.encode(semantic_query).tolist()
            results = progress_collection.query(query_embeddings=[query_embedding], n_results=50)
            relevant_ids = results['ids'][0]
            if not relevant_ids:
                results_df = pd.DataFrame(columns=df.columns)
            else:
                results_df = df[df['id'].isin(relevant_ids)].copy()
                relevance_scores = {id_str: dist for id_str, dist in zip(results['ids'][0], results['distances'][0])}
                results_df['relevance'] = results_df['id'].map(relevance_scores)
    
    if selected_sources:
        results_df = results_df[results_df['source'].isin(selected_sources)]
    if search_term:
        term_lower = search_term.lower()
        results_df = results_df[results_df.apply(
            lambda row: term_lower in str(row['title']).lower() or term_lower in str(row['keywords']).lower(),
            axis=1
        )]
    
    # Sorting Logic
    if sort_key == "Relevance" and 'relevance' in results_df.columns:
        sorted_df = results_df.sort_values('relevance', ascending=True)
    elif sort_key == "Importance Score":
        sorted_df = results_df.sort_values('overall_importance_score', ascending=False)
    else:
        sorted_df = results_df.sort_values('published_date', ascending=False, na_position='last')

    # Pagination Logic
    total_items = len(sorted_df)
    page_size = st.session_state.page_size
    total_pages = math.ceil(total_items / page_size) if page_size > 0 else 1
    if st.session_state.get(page_number_key, 1) > total_pages:
        st.session_state[page_number_key] = 1
    
    start_index = (st.session_state[page_number_key] - 1) * page_size
    end_index = start_index + page_size
    paginated_df = sorted_df.iloc[start_index:end_index]

    # Pagination UI
    st.subheader(f"Showing {len(paginated_df)} of {total_items} breakthroughs")
    p_col1, p_col2, p_col3, p_col4 = st.columns([2, 2, 1, 5])
    if p_col1.button("⬅️ Previous", use_container_width=True, disabled=(st.session_state[page_number_key] <= 1), key=f"prev_{tab_key_prefix}"):
        st.session_state[page_number_key] -= 1
        st.rerun()
    if p_col2.button("Next ➡️", use_container_width=True, disabled=(st.session_state[page_number_key] >= total_pages), key=f"next_{tab_key_prefix}"):
        st.session_state[page_number_key] += 1
        st.rerun()
    p_col3.number_input("Page", min_value=1, max_value=total_pages or 1, key=page_number_key, label_visibility="collapsed")
    p_col4.markdown(f"<div style='text-align: right; padding-top: 10px;'>Page {st.session_state[page_number_key]} of {total_pages}</div>", unsafe_allow_html=True)
    st.divider()

    # Display Results
    if paginated_df.empty:
        st.info("No results match your criteria.")
    else:
        for _, item in paginated_df.iterrows():
            card_container = st.container(border=True)
            render_progress_card(item.to_dict(), card_container, lang_code=st.session_state.display_language, key_prefix=f"{tab_key_prefix}_{item['id']}")
            
            # Flagging logic
            if st.session_state.get(f"flagging_item_id_{tab_key_prefix}_{item['id']}") == item['id']:
                with st.form(key=f"form_flag_{tab_key_prefix}_{item['id']}", clear_on_submit=True):
                    st.warning(f"Flagging: {item['title']}")
                    reason = st.selectbox("Reason:", ["Inaccurate Summary", "Incorrect Score", "Other"], key=f"reason_{tab_key_prefix}_{item['id']}")
                    comment = st.text_area("Optional Comment:", key=f"comment_{tab_key_prefix}_{item['id']}")
                    submitted = st.form_submit_button("Submit Flag")
                    if submitted:
                        db = SessionLocal()
                        try:
                            new_flag = CorrectionFlag(item_id=int(item['id']), reason=reason, user_comment=comment)
                            db.add(new_flag)
                            db.commit()
                            st.success("Flag submitted!")
                        finally:
                            db.close()
                        del st.session_state[f"flagging_item_id_{tab_key_prefix}_{item['id']}"]
                        st.rerun()

# --- Tab Definitions ---
tab_all, tab_feed = st.tabs(["🔥 All Progress", "👤 My Feed"])

with tab_all:
    process_and_display_feed(df, tab_key_prefix="all_progress")

with tab_feed:
    db = SessionLocal()
    followed_terms = [row.term for row in db.query(FollowedTerm.term).all()]
    db.close()

    if not followed_terms:
        st.info("You are not following any terms. Add some in the sidebar to create your personalized feed.")
    else:
        try:
            pattern = '|'.join(map(re.escape, followed_terms))
            my_feed_df = df[df.apply(
                lambda row: bool(
                    re.search(pattern, str(row['title']).lower()) or
                    re.search(pattern, str(row['keywords']).lower())
                ), 
                axis=1
            )]
            process_and_display_feed(my_feed_df, tab_key_prefix="my_feed")
        except re.error as e:
            st.error(f"Could not process followed terms due to a regular expression error: {e}")