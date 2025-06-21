# tasks.py

# --- ChromaDB System Hack ---
# This block must be at the very top of the file
# to ensure the correct sqlite3 version is loaded
# before chromadb is imported.
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
# --- End of Hack ---

import os
import time
from celery_app import celery
# --- Update the import ---
from ingest import fetch_from_arxiv, fetch_from_web_sources
from services import analyze_rank_and_translate
from database import SessionLocal, add_progress_item, ProgressItem
from sentence_transformers import SentenceTransformer
import chromadb

# --- Initialize models and clients (no changes here) ---
LOCAL_MODEL_PATH = '/app/models/all-MiniLM-L6-v2'

print("TASKS: Loading Sentence Transformer model from local path...")
try:
    embedding_model = SentenceTransformer(LOCAL_MODEL_PATH, device='cpu')
    print("TASKS: Sentence Transformer model loaded successfully.")
except Exception as e:
    print(f"TASKS: FATAL ERROR loading Sentence Transformer model: {e}")
    embedding_model = None

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
progress_collection = chroma_client.get_or_create_collection(name="ai_progress", metadata={"hnsw:space": "cosine"})
print("TASKS: Connected to ChromaDB successfully.")

# --- Celery Tasks ---

@celery.task(name="tasks.run_scraper_cycle")
def run_scraper_cycle():
    """A single task that orchestrates fetching from all active sources."""
    print("TASK: Starting full scraper cycle.")
    all_new_items = []
    
    # Fetch from arXiv using its dedicated function
    all_new_items.extend(fetch_from_arxiv())
    
    # Fetch from all other web sources using the new dispatcher
    all_new_items.extend(fetch_from_web_sources())
    
    if not all_new_items:
        print("TASK: No new items found in this cycle.")
        return "Scraper cycle complete. No new items found from any source."
    
    # Remove duplicates based on URL before dispatching
    unique_items = {item['url']: item for item in all_new_items}.values()
    
    print(f"TASK: Found a total of {len(unique_items)} unique items. Dispatching analysis tasks...")
    for item in unique_items:
        # Dispatch a separate task for each item for parallel processing
        process_item.delay(item)
        
    return f"Scraper cycle complete. Dispatched {len(unique_items)} tasks."


@celery.task(name="tasks.process_item", bind=True, max_retries=3, default_retry_delay=60)
def process_item(self, item_data: dict):
    """
    The main worker task: takes raw item data, analyzes it, creates embeddings, and stores everything.
    This task is resilient to missing keys from the AI and API failures.
    """
    entry_id = item_data['entry_id']
    title = item_data['title']
    print(f"TASK: Worker processing item: {title}")

    # 1. Check if item already exists in PostgreSQL
    db = SessionLocal()
    try:
        exists = db.query(ProgressItem).filter(ProgressItem.entry_id == entry_id).first()
        if exists:
            print(f"TASK: Skipping '{title}' as it already exists in DB.")
            return f"Skipped (already exists): {entry_id}"
    finally:
        db.close()

    # 2. Perform AI analysis (now using the more robust service layer)
    try:
        # Call the new, all-in-one function
        analysis_data = analyze_rank_and_translate(title, item_data['abstract'])
        if not analysis_data:
            raise ValueError("Unified analysis from Gemini returned None or was invalid.")
    except Exception as e:
        print(f"TASK: ERROR during Gemini analysis for '{title}': {e}. Retrying...")
        raise self.retry(exc=e)

    # 3. Create semantic embedding (using .get() for resilience)
    text_to_embed = (
        f"Title: {analysis_data.get('en', {}).get('title', 'No Title Provided')}\n"
        f"Innovation: {analysis_data.get('en', {}).get('what_is_new', 'No summary available.')}\n"
        f"Impact: {analysis_data.get('en', {}).get('why_it_matters', 'No impact statement available.')}"
    )
    embedding = embedding_model.encode(text_to_embed).tolist()

    # 4. Store results in PostgreSQL
    db_item_data = {**item_data, "analysis_data": analysis_data}
    db_item = add_progress_item(db_item_data)
    if not db_item:
        print(f"TASK: ERROR failed to save '{title}' to PostgreSQL.")
        return f"Failed (Postgres save error): {entry_id}"

    # 5. Store embedding in ChromaDB
    try:
        progress_collection.add(
            embeddings=[embedding],
            documents=[text_to_embed],
            metadatas=[{"source": item_data['source'], "title": title}],
            ids=[str(db_item.id)]
        )
    except Exception as e:
        print(f"TASK: ERROR failed to save embedding for '{title}' to ChromaDB: {e}")

    print(f"TASK: Successfully processed and stored '{title}'.")
    return f"Success: {entry_id}"

# Note: The send_weekly_digest task is omitted here for clarity but would
# be part of this file in the full application.