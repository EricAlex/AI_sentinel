# ingest.py

import arxiv
from database import SessionLocal, Source
# Import our new parsers map and the dedicated arXiv function
from parsers import PARSER_MAP

def fetch_from_arxiv(max_results=50):
    """
    Fetches papers from arXiv using its dedicated Python library.
    This is kept separate from web scrapers as it uses a formal API.
    """
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
                "entry_id": result.entry_id,
                "title": result.title,
                "abstract": result.summary.replace('\n', ' '),
                "authors": [author.name for author in result.authors],
                "published_date": result.published,
                "url": result.pdf_url,
                "source": "arXiv"
            })
        print(f"INGEST: Found {len(papers)} new papers from arXiv.")
        return papers
    except Exception as e:
        print(f"INGEST: ERROR fetching from arXiv: {e}")
        return []

def fetch_from_web_sources():
    """
    Fetches from all active web sources defined in the database
    by dynamically calling the correct parser for each source type.
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
        
    all_items = []
    print(f"INGEST: Found {len(sources_to_scrape)} active web sources to scrape.")
    for source in sources_to_scrape:
        print(f"--- Scraping source: {source.name} ---")
        parser_func = PARSER_MAP.get(source.source_type)
        if parser_func:
            try:
                # Call the correct parser for this source, passing its URL and name
                new_items = parser_func(source.url, source.name)
                print(f"-> Found {len(new_items)} items from {source.name}")
                all_items.extend(new_items)
            except Exception as e:
                # This is crucial for resilience. If one source fails, we log it and continue.
                print(f"INGEST: FATAL ERROR parsing source '{source.name}': {e}. Skipping to next source.")
                continue
    return all_items