# ingest.py

import arxiv
from database import SessionLocal, Source
# Import our new parsers map and the healer task
from parsers import PARSER_MAP
from redis import Redis
import os

from sourcerer import attempt_heal_parser

redis_client = Redis.from_url(os.getenv('CELERY_BROKER_URL'), decode_responses=True)

def fetch_from_arxiv(max_results=100):
    """Fetches papers from arXiv using its dedicated Python library."""
    print("INGEST: Fetching from arXiv source...")
    query = "cat:cs.LG OR cat:cs.AI OR cat:cs.CL OR cat:cs.CV OR cat:cs.RO"
    try:
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )
        papers = []
        for result in search.results():
            papers.append({
                "entry_id": result.entry_id, "title": result.title, "abstract": result.summary.replace('\n', ' '),
                "authors": [author.name for author in result.authors], "published_date": result.published,
                "url": result.pdf_url, "source": "arXiv"
            })
        print(f"INGEST: Found {len(papers)} new papers from arXiv.")
        return papers
    except Exception as e:
        print(f"INGEST: ERROR fetching from arXiv: {e}")
        return []

def fetch_from_web_sources():
    """
    Fetches from all active web sources and triggers the AI healer
    for sources that fail.
    """
    db = SessionLocal()
    try:
        # Get all sources that are active and have a parser defined in our map
        sources_to_scrape = db.query(Source).filter(
            Source.is_active == True,
            Source.source_type.in_(PARSER_MAP.keys())
        ).all()
    finally:
        db.close()
    # --------------------------------------------------
        
    all_items = []
    print(f"INGEST: Found {len(sources_to_scrape)} active web sources to scrape.")
    for source in sources_to_scrape:
        print(f"--- Scraping source: {source.name} ---")
        parser_func = PARSER_MAP.get(source.source_type)
        if parser_func:
            # --- REDIS FAILURE TRACKING LOGIC ---
            failure_key = f"parser_failure:{source.id}"
            
            try:
                new_items = parser_func(source.url, source.name, 10)
                if not new_items:
                    raise ValueError("Parser returned an empty list.")
                
                print(f"-> Found {len(new_items)} items from {source.name}")
                all_items.extend(new_items)
                
                # On success, delete the failure key from Redis
                redis_client.delete(failure_key)

            except Exception as e:
                print(f"INGEST: PARSE FAILED for source '{source.name}': {e}.")
                
                # On failure, increment the failure count in Redis
                # INCR is atomic, so it's safe for multiple workers
                failure_count = redis_client.incr(failure_key)
                # Set an expiration so old failures don't count forever (e.g., 6 hours)
                redis_client.expire(failure_key, 6 * 3600)
                
                # Trigger heal after 2 consecutive failures
                if failure_count >= 2:
                    print(f"INGEST: Source '{source.name}' has failed {failure_count} times. Triggering AI Healer.")
                    attempt_heal_parser.delay(source.id)
                    # After triggering, delete the key to reset the process and prevent spam
                    redis_client.delete(failure_key)
                continue
    return all_items