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

class ParserProposal(Base):
    """Stores AI-generated proposals for broken parsers."""
    __tablename__ = 'parser_proposals'

    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey('sources.id'), index=True)
    proposed_code = Column(Text, nullable=False)
    validation_output_sample = Column(JSON) # Store a sample of what the new parser found
    status = Column(String, default='pending_review', index=True) # pending_review, approved, rejected
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
    Fetches all items and flattens the NEW multi-lingual structure for the UI.
    """
    db = SessionLocal()
    try:
        items = db.query(ProgressItem).order_by(ProgressItem.published_date.desc()).all()
        results = []
        for item in items:
            analysis = item.analysis_data or {}
            ranking = analysis.get('ranking', {})
            
            flat_item = {
                "id": item.id,
                "url": item.url,
                "source": item.source,
                "published_date": item.published_date.date() if item.published_date else 'N/A',
                "analysis_data": analysis, # Pass the full rich object to the UI
                
                # Flattened fields for searching/sorting, always from English
                "title": analysis.get('en', {}).get('title', 'Untitled'),
                "keywords": analysis.get('keywords', []),
                "overall_importance_score": float(ranking.get('overall_importance_score', 0.0)),
            }
            results.append(flat_item)
        return results
    finally:
        db.close()

def get_all_sources():
    """Fetches all sources from the database."""
    db = SessionLocal()
    try:
        return db.query(Source).all()
    finally:
        db.close()

def add_new_source(name: str, url: str, source_type: str):
    """Adds a new source to the database."""
    db = SessionLocal()
    try:
        # Check if source already exists to prevent duplicates
        exists = db.query(Source).filter((Source.name == name) | (Source.url == url)).first()
        if exists:
            print(f"DATABASE: Source '{name}' or URL '{url}' already exists.")
            return None
        
        new_source = Source(name=name, url=url, source_type=source_type, is_active=True)
        db.add(new_source)
        db.commit()
        db.refresh(new_source)
        print(f"DATABASE: Successfully added new source '{name}'.")
        return new_source
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error adding new source: {e}")
        return None
    finally:
        db.close()

def update_source(source_id: int, new_data: dict):
    """Updates an existing source's data."""
    db = SessionLocal()
    try:
        source = db.query(Source).get(source_id)
        if not source:
            return False
        
        for key, value in new_data.items():
            setattr(source, key, value)
        
        db.commit()
        print(f"DATABASE: Successfully updated source ID {source_id}.")
        return True
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error updating source: {e}")
        return False
    finally:
        db.close()

def delete_source(source_id: int):
    """Deletes a source from the database."""
    db = SessionLocal()
    try:
        source = db.query(Source).get(source_id)
        if not source:
            return False
        
        db.delete(source)
        db.commit()
        print(f"DATABASE: Successfully deleted source ID {source_id}.")
        return True
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error deleting source: {e}")
        return False
    finally:
        db.close()

def delete_followed_term(term_to_delete: str):
    """Deletes a followed term from the database."""
    db = SessionLocal()
    try:
        term_object = db.query(FollowedTerm).filter(FollowedTerm.term == term_to_delete).first()
        if term_object:
            db.delete(term_object)
            db.commit()
            print(f"DATABASE: Successfully deleted followed term '{term_to_delete}'.")
            return True
        return False
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error deleting followed term: {e}")
        return False
    finally:
        db.close()

