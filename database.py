# database.py

import os
import json
import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON, Boolean, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found. Please set it in your .env file.")

# Create the SQLAlchemy engine and session factory
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# --- ORM Models: Defining the Database Schema ---

class ProgressItem(Base):
    """Stores the main AI progress items after analysis."""
    __tablename__ = "progress_items"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(String, unique=True, index=True) # Unique ID from the source (e.g., arXiv ID or URL)
    title = Column(String, index=True)
    url = Column(String)
    source = Column(String, index=True)
    published_date = Column(DateTime)
    # The full AI analysis result from Gemini (summary, scores, justifications, etc.)
    analysis_data = Column(JSON) # JSONB in PostgreSQL for efficient querying
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Source(Base):
    """Stores the list of sources for the scraper to read from."""
    __tablename__ = 'sources'
    
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True) # e.g., 'arXiv', 'Google AI Blog'
    url = Column(String, unique=True, index=True) # Homepage/feed URL
    source_type = Column(String) # 'arxiv', 'blog', etc.
    is_active = Column(Boolean, default=True) # Toggle sources on/off without deleting

class FollowedTerm(Base):
    """Stores personalized terms that users want to follow."""
    __tablename__ = 'followed_terms'
    
    id = Column(Integer, primary_key=True)
    term = Column(String, unique=True, index=True)
    user_id = Column(String, default="default_user", index=True) # For future multi-user support

class CorrectionFlag(Base):
    """Stores user-submitted flags for content review."""
    __tablename__ = 'correction_flags'
    
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey('progress_items.id'), index=True) # Link to the progress item
    reason = Column(String)
    user_comment = Column(Text, nullable=True)
    status = Column(String, default='pending', index=True) # pending, resolved
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# --- Database Utility Functions ---

def create_all_tables():
    """A utility function to create all defined tables in the database."""
    print("DATABASE: Creating all tables...")
    Base.metadata.create_all(bind=engine)
    print("DATABASE: Tables created successfully (if they didn't exist).")

def add_progress_item(item_data: dict):
    """
    Adds a newly fetched and analyzed item to the database.
    Handles data extraction from the combined dictionary.
    
    Returns: The newly created ProgressItem object or None.
    """
    db = SessionLocal()
    try:
        new_item = ProgressItem(
            entry_id=item_data['entry_id'],
            title=item_data.get('title', 'Untitled'),
            url=item_data['url'],
            source=item_data['source'],
            published_date=item_data['published_date'],
            analysis_data=item_data['analysis_data']
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        print(f"DATABASE: Successfully added '{new_item.title}' to the database.")
        return new_item
    except IntegrityError:
        db.rollback()
        print(f"DATABASE: Item with entry_id '{item_data['entry_id']}' already exists. Skipping.")
        return None
    except Exception as e:
        db.rollback()
        print(f"DATABASE: An unexpected error occurred while adding an item: {e}")
        return None
    finally:
        db.close()

def get_all_progress_items():
    """
    Fetches all processed items from the database and formats them for the Streamlit UI.
    This flattens the nested JSON data for easier use in Pandas.
    
    Returns: A list of flattened dictionaries.
    """
    db = SessionLocal()
    try:
        items = db.query(ProgressItem).order_by(ProgressItem.published_date.desc()).all()
        results = []
        for item in items:
            # Flatten the nested analysis_data for easier display and filtering
            analysis = item.analysis_data or {}
            scores = analysis.get('scores', {})
            
            flat_item = {
                "id": item.id,
                "url": item.url,
                "source": item.source,
                "published_date": item.published_date.date(),
                "title": analysis.get('title', item.title),
                "summary_what_is_new": analysis.get('summary_what_is_new', ''),
                "summary_how_it_works": analysis.get('summary_how_it_works', ''),
                "summary_why_it_matters": analysis.get('summary_why_it_matters', ''),
                "keywords": analysis.get('keywords', []),
                "overall_importance_score": float(analysis.get('overall_importance_score', 0.0)),
                "overall_importance_justification": analysis.get('overall_importance_justification', ''),
                "novelty_score": scores.get('breakthrough_novelty', {}).get('score', 0),
                "human_impact_score": scores.get('human_impact', {}).get('score', 0),
                "field_influence_score": scores.get('field_influence', {}).get('score', 0),
                "technical_maturity_score": scores.get('technical_maturity', {}).get('score', 0),
            }
            results.append(flat_item)
        return results
    finally:
        db.close()