# database.py

import os
import json
import datetime
import uuid
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
from passlib.hash import bcrypt
from cryptography.fernet import Fernet

SHARED_TENANT_ID = "a0a0a0a0-a0a0-4a0a-a0a0-a0a0a0a0a0a0" # A special UUID for the shared tenant

# Load environment variables from .env file
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found. Please set it in your .env file.")

if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY not found. Please set it in your .env file.")

fernet = Fernet(ENCRYPTION_KEY.encode())

# Create the SQLAlchemy engine and session factory
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# --- ORM Models: Defining the Database Schema ---

class Tenant(Base):
    """Stores information about each customer/tenant."""
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())) # UUID for tenant ID
    name = Column(String, unique=True, index=True, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    users = relationship("User", back_populates="tenant")
    progress_items = relationship("ProgressItem", back_populates="tenant")
    sources = relationship("Source", back_populates="tenant")
    followed_terms = relationship("FollowedTerm", back_populates="tenant")
    correction_flags = relationship("CorrectionFlag", back_populates="tenant")
    parser_proposals = relationship("ParserProposal", back_populates="tenant")
    llm_config = relationship("TenantLLMConfig", back_populates="tenant", uselist=False) # One-to-one relationship
    custom_parsers = relationship("TenantSourceParser", back_populates="tenant")


class User(Base):
    """Stores user information, linked to a tenant."""
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4())) # UUID for user ID
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    username = Column(String, unique=True, index=True, nullable=False) # e.g., email address
    password_hash = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False) # Tenant-level admin
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    tenant = relationship("Tenant", back_populates="users")

    def verify_password(self, password: str) -> bool:
        return bcrypt.verify(password, self.password_hash)

    def set_password(self, password: str):
        self.password_hash = bcrypt.hash(password)


class TenantLLMConfig(Base):
    """Stores LLM configuration for each tenant, with encrypted API keys."""
    __tablename__ = "tenant_llm_configs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), unique=True, nullable=False)
    llm_provider = Column(String, nullable=False) # e.g., "openai", "google", "huggingface"
    llm_model_name = Column(String, nullable=False) # e.g., "gpt-4o", "gemini-2.5-flash"
    api_key_encrypted = Column(Text, nullable=False) # Encrypted API key
    base_url = Column(String, nullable=True) # For custom API endpoints
    custom_settings = Column(JSON, nullable=True) # For provider-specific settings
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    tenant = relationship("Tenant", back_populates="llm_config")

    def get_api_key(self) -> str:
        return fernet.decrypt(self.api_key_encrypted.encode()).decode()

    def set_api_key(self, api_key: str):
        self.api_key_encrypted = fernet.encrypt(api_key.encode()).decode()


class TenantSourceParser(Base):
    """Stores custom parser code for a specific source and tenant."""
    __tablename__ = "tenant_source_parsers"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    parser_code = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    tenant = relationship("Tenant", back_populates="custom_parsers")
    source = relationship("Source") # Relationship to Source model

    __table_args__ = (UniqueConstraint('tenant_id', 'source_id', name='_tenant_source_uc'),)


class ProgressItem(Base):
    """Stores the main AI progress items after analysis."""
    __tablename__ = "progress_items"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False) # Link to tenant
    entry_id = Column(String, unique=True, index=True) # Unique ID from the source (e.g., arXiv ID or URL)
    title = Column(String, index=True)
    url = Column(String)
    source = Column(String, index=True)
    published_date = Column(DateTime)
    # The full AI analysis result from Gemini (summary, scores, justifications, etc.)
    analysis_data = Column(JSON) # JSONB in PostgreSQL for efficient querying
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    tenant = relationship("Tenant", back_populates="progress_items")


class Source(Base):
    """Stores the list of sources for the scraper to read from."""
    __tablename__ = 'sources'
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False) # Link to tenant
    name = Column(String, unique=True) # e.g., 'arXiv', 'Google AI Blog'
    url = Column(String, unique=True, index=True) # Homepage/feed URL
    source_type = Column(String) # 'arxiv', 'blog', etc.
    is_active = Column(Boolean, default=True) # Toggle sources on/off without deleting
    is_shared = Column(Boolean, default=False) # True if source is available to all tenants

    tenant = relationship("Tenant", back_populates="sources")


class FollowedTerm(Base):
    """Stores personalized terms that users want to follow, now linked to a tenant."""
    __tablename__ = 'followed_terms'
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False) # Link to tenant
    term = Column(String, unique=True, index=True) # Term is unique per tenant
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    tenant = relationship("Tenant", back_populates="followed_terms")


class CorrectionFlag(Base):
    """Stores user-submitted flags for content review, linked to a tenant."""
    __tablename__ = 'correction_flags'
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False) # Link to tenant
    item_id = Column(Integer, ForeignKey('progress_items.id'), index=True) # Link to the progress item
    reason = Column(String)
    user_comment = Column(Text, nullable=True)
    status = Column(String, default='pending', index=True) # pending, resolved
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    tenant = relationship("Tenant", back_populates="correction_flags")


class ParserProposal(Base):
    """Stores AI-generated proposals for broken parsers, linked to a tenant."""
    __tablename__ = 'parser_proposals'

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False) # Link to tenant
    source_id = Column(Integer, ForeignKey('sources.id'), index=True)
    proposed_code = Column(Text, nullable=False)
    validation_output_sample = Column(JSON) # Store a sample of what the new parser found
    status = Column(String, default='pending_review', index=True) # pending_review, approved, rejected
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    tenant = relationship("Tenant", back_populates="parser_proposals")


# --- Database Utility Functions ---

def create_all_tables():
    """A utility function to create all defined tables in the database."""
    print("DATABASE: Creating all tables...")
    Base.metadata.create_all(bind=engine)
    print("DATABASE: Tables created successfully (if they didn't exist).")

def add_progress_item(item_data: dict, tenant_id: str):
    """
    Adds a newly fetched and analyzed item to the database, linked to a tenant.
    Handles data extraction from the combined dictionary.
    
    Returns: The newly created ProgressItem object or None.
    """
    db = SessionLocal()
    try:
        new_item = ProgressItem(
            tenant_id=tenant_id,
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
        print(f"DATABASE: Successfully added '{new_item.title}' for tenant {tenant_id} to the database.")
        return new_item
    except IntegrityError:
        db.rollback()
        print(f"DATABASE: Item with entry_id '{item_data['entry_id']}' already exists for tenant {tenant_id}. Skipping.")
        return None
    except Exception as e:
        db.rollback()
        print(f"DATABASE: An unexpected error occurred while adding an item for tenant {tenant_id}: {e}")
        return None
    finally:
        db.close()

def get_all_progress_items(tenant_id: str):
    """
    Fetches all items for a specific tenant and flattens the NEW multi-lingual structure for the UI.
    This version includes robust parsing for potentially malformed AI-generated data.
    """
    db = SessionLocal()
    try:
        items = db.query(ProgressItem).filter(ProgressItem.tenant_id == tenant_id).order_by(ProgressItem.published_date.desc()).all()
        results = []
        for item in items:
            analysis = item.analysis_data or {}
            ranking = analysis.get('ranking', {})

            # Robustly parse the importance score
            score_value = ranking.get('overall_importance_score', 0.0)
            try:
                overall_importance_score = float(score_value)
            except (ValueError, TypeError):
                overall_importance_score = 0.0

            flat_item = {
                "id": item.id,
                "url": item.url,
                "source": item.source,
                "published_date": item.published_date.isoformat() if item.published_date else 'N/A',
                "analysis_data": analysis,

                # Flattened fields for searching/sorting, always from English
                "title": analysis.get('en', {}).get('title', item.title or 'Untitled'), # Fallback to original title
                "keywords": analysis.get('keywords', []),
                "overall_importance_score": overall_importance_score,
            }
            results.append(flat_item)
        return results
    finally:
        db.close()

def get_all_sources(tenant_id: str):
    """
    Fetches all sources for a specific tenant (including shared ones).
    """
    db = SessionLocal()
    try:
        # Fetch tenant-specific sources and shared sources
        sources = db.query(Source).filter(
            (Source.tenant_id == tenant_id) | (Source.is_shared == True)
        ).all()
        return sources
    finally:
        db.close()

def add_new_source(name: str, url: str, source_type: str, tenant_id: str, is_shared: bool = False):
    """
    Adds a new source to the database, linked to a tenant.
    """
    db = SessionLocal()
    try:
        # Check if source already exists for this tenant or as a shared source
        exists = db.query(Source).filter(
            ((Source.tenant_id == tenant_id) | (Source.is_shared == True)) & 
            ((Source.name == name) | (Source.url == url))
        ).first()
        if exists:
            print(f"DATABASE: Source '{name}' or URL '{url}' already exists for tenant {tenant_id} or as shared.")
            return None
        
        new_source = Source(
            tenant_id=tenant_id,
            name=name, 
            url=url, 
            source_type=source_type, 
            is_active=True,
            is_shared=is_shared
        )
        db.add(new_source)
        db.commit()
        db.refresh(new_source)
        print(f"DATABASE: Successfully added new source '{name}' for tenant {tenant_id}.")
        return new_source
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error adding new source for tenant {tenant_id}: {e}")
        return None
    finally:
        db.close()

def update_source(source_id: int, new_data: dict, tenant_id: str):
    """
    Updates an existing source's data, ensuring it belongs to the tenant or is shared.
    """
    db = SessionLocal()
    try:
        source = db.query(Source).filter(
            (Source.id == source_id) & ((Source.tenant_id == tenant_id) | (Source.is_shared == True))
        ).first()
        if not source:
            print(f"DATABASE: Source ID {source_id} not found or not accessible by tenant {tenant_id}.")
            return False
        
        for key, value in new_data.items():
            setattr(source, key, value)
        
        db.commit()
        print(f"DATABASE: Successfully updated source ID {source_id} for tenant {tenant_id}.")
        return True
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error updating source for tenant {tenant_id}: {e}")
        return False
    finally:
        db.close()

def delete_source(source_id: int, tenant_id: str):
    """
    Deletes a source from the database, ensuring it belongs to the tenant and is not shared.
    """
    db = SessionLocal()
    try:
        source = db.query(Source).filter(
            (Source.id == source_id) & (Source.tenant_id == tenant_id) & (Source.is_shared == False)
        ).first()
        if not source:
            print(f"DATABASE: Source ID {source_id} not found, not owned by tenant {tenant_id}, or is a shared source and cannot be deleted.")
            return False
        
        db.delete(source)
        db.commit()
        print(f"DATABASE: Successfully deleted source ID {source_id} for tenant {tenant_id}.")
        return True
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error deleting source for tenant {tenant_id}: {e}")
        return False
    finally:
        db.close()

def delete_followed_term(term_to_delete: str, tenant_id: str):
    """
    Deletes a followed term for a specific tenant from the database.
    """
    db = SessionLocal()
    try:
        term_object = db.query(FollowedTerm).filter(
            (FollowedTerm.term == term_to_delete) & (FollowedTerm.tenant_id == tenant_id)
        ).first()
        if term_object:
            db.delete(term_object)
            db.commit()
            print(f"DATABASE: Successfully deleted followed term '{term_to_delete}' for tenant {tenant_id}.")
            return True
        print(f"DATABASE: Followed term '{term_to_delete}' not found for tenant {tenant_id}.")
        return False
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error deleting followed term for tenant {tenant_id}: {e}")
        return False
    finally:
        db.close()

def add_followed_term(term: str, tenant_id: str):
    """
    Adds a new followed term for a specific tenant.
    """
    db = SessionLocal()
    try:
        exists = db.query(FollowedTerm).filter(
            (FollowedTerm.term == term) & (FollowedTerm.tenant_id == tenant_id)
        ).first()
        if exists:
            print(f"DATABASE: Followed term '{term}' already exists for tenant {tenant_id}.")
            return None
        
        new_term = FollowedTerm(tenant_id=tenant_id, term=term)
        db.add(new_term)
        db.commit()
        db.refresh(new_term)
        print(f"DATABASE: Successfully added followed term '{term}' for tenant {tenant_id}.")
        return new_term
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error adding followed term for tenant {tenant_id}: {e}")
        return None
    finally:
        db.close()

def get_followed_terms(tenant_id: str):
    """
    Fetches all followed terms for a specific tenant.
    """
    db = SessionLocal()
    try:
        return db.query(FollowedTerm).filter(FollowedTerm.tenant_id == tenant_id).all()
    finally:
        db.close()

def get_progress_item_by_id(item_id: int, tenant_id: str):
    """
    Fetches a single progress item by ID for a specific tenant.
    """
    db = SessionLocal()
    try:
        return db.query(ProgressItem).filter(
            (ProgressItem.id == item_id) & (ProgressItem.tenant_id == tenant_id)
        ).first()
    finally:
        db.close()

def add_correction_flag(item_id: int, reason: str, user_comment: str, tenant_id: str):
    """
    Adds a correction flag for a specific item and tenant.
    """
    db = SessionLocal()
    try:
        # Ensure the item exists and belongs to the tenant
        item = db.query(ProgressItem).filter(
            (ProgressItem.id == item_id) & (ProgressItem.tenant_id == tenant_id)
        ).first()
        if not item:
            print(f"DATABASE: Progress item ID {item_id} not found or not accessible by tenant {tenant_id}.")
            return None

        new_flag = CorrectionFlag(
            tenant_id=tenant_id,
            item_id=item_id,
            reason=reason,
            user_comment=user_comment
        )
        db.add(new_flag)
        db.commit()
        db.refresh(new_flag)
        print(f"DATABASE: Successfully added correction flag for item {item_id} by tenant {tenant_id}.")
        return new_flag
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error adding correction flag for tenant {tenant_id}: {e}")
        return None
    finally:
        db.close()

def add_parser_proposal(source_id: int, proposed_code: str, validation_output_sample: dict, tenant_id: str):
    """
    Adds a parser proposal for a specific source and tenant.
    """
    db = SessionLocal()
    try:
        # Ensure the source exists and belongs to the tenant or is shared
        source = db.query(Source).filter(
            (Source.id == source_id) & ((Source.tenant_id == tenant_id) | (Source.is_shared == True))
        ).first()
        if not source:
            print(f"DATABASE: Source ID {source_id} not found or not accessible by tenant {tenant_id}.")
            return None

        new_proposal = ParserProposal(
            tenant_id=tenant_id,
            source_id=source_id,
            proposed_code=proposed_code,
            validation_output_sample=validation_output_sample
        )
        db.add(new_proposal)
        db.commit()
        db.refresh(new_proposal)
        print(f"DATABASE: Successfully added parser proposal for source {source_id} by tenant {tenant_id}.")
        return new_proposal
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error adding parser proposal for tenant {tenant_id}: {e}")
        return None
    finally:
        db.close()

def get_user_by_username(username: str):
    """
    Fetches a user by username.
    """
    db = SessionLocal()
    try:
        return db.query(User).filter(User.username == username).first()
    finally:
        db.close()

def create_user(tenant_id: str, username: str, password: str, is_admin: bool = False):
    """
    Creates a new user for a given tenant.
    """
    db = SessionLocal()
    try:
        # Check if username already exists globally (usernames are unique across all tenants)
        existing_user = db.query(User).filter(User.username == username).first()
        if existing_user:
            print(f"DATABASE: Username '{username}' already exists.")
            return None

        new_user = User(tenant_id=tenant_id, username=username, is_admin=is_admin)
        new_user.set_password(password)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        print(f"DATABASE: Successfully created user '{username}' for tenant {tenant_id}.")
        return new_user
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error creating user '{username}': {e}")
        return None
    finally:
        db.close()

def create_tenant(name: str, description: str = None, id: str = None):
    """
    Creates a new tenant.
    """
    db = SessionLocal()
    try:
        existing_tenant = db.query(Tenant).filter(Tenant.name == name).first()
        if existing_tenant:
            print(f"DATABASE: Tenant with name '{name}' already exists.")
            return None
        
        if id:
            new_tenant = Tenant(id=id, name=name, description=description)
        else:
            new_tenant = Tenant(name=name, description=description)
        db.add(new_tenant)
        db.commit()
        db.refresh(new_tenant)
        print(f"DATABASE: Successfully created tenant '{name}' with ID {new_tenant.id}.")
        return new_tenant
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error creating tenant '{name}': {e}")
        return None
    finally:
        db.close()

def get_tenant_by_id(tenant_id: str):
    """
    Fetches a tenant by ID.
    """
    db = SessionLocal()
    try:
        return db.query(Tenant).filter(Tenant.id == tenant_id).first()
    finally:
        db.close()

def get_tenant_by_name(tenant_name: str):
    """
    Fetches a tenant by name.
    """
    db = SessionLocal()
    try:
        return db.query(Tenant).filter(Tenant.name == tenant_name).first()
    finally:
        db.close()

def get_llm_config_for_tenant(tenant_id: str):
    """
    Fetches LLM configuration for a specific tenant.
    """
    db = SessionLocal()
    try:
        return db.query(TenantLLMConfig).filter(TenantLLMConfig.tenant_id == tenant_id).first()
    finally:
        db.close()

def create_or_update_llm_config(tenant_id: str, llm_provider: str, llm_model_name: str, api_key: str, base_url: str = None, custom_settings: dict = None):
    """
    Creates or updates LLM configuration for a tenant.
    """
    db = SessionLocal()
    try:
        llm_config = db.query(TenantLLMConfig).filter(TenantLLMConfig.tenant_id == tenant_id).first()
        if llm_config:
            llm_config.llm_provider = llm_provider
            llm_config.llm_model_name = llm_model_name
            llm_config.set_api_key(api_key)
            llm_config.base_url = base_url
            llm_config.custom_settings = custom_settings
        else:
            llm_config = TenantLLMConfig(
                tenant_id=tenant_id,
                llm_provider=llm_provider,
                llm_model_name=llm_model_name,
                base_url=base_url,
                custom_settings=custom_settings
            )
            llm_config.set_api_key(api_key)
            db.add(llm_config)
        db.commit()
        db.refresh(llm_config)
        print(f"DATABASE: Successfully created/updated LLM config for tenant {tenant_id}.")
        return llm_config
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error creating/updating LLM config for tenant {tenant_id}: {e}")
        return None
    finally:
        db.close()

def get_custom_parser(tenant_id: str, source_id: int):
    """
    Fetches a custom parser for a specific tenant and source.
    """
    db = SessionLocal()
    try:
        return db.query(TenantSourceParser).filter(
            (TenantSourceParser.tenant_id == tenant_id) & (TenantSourceParser.source_id == source_id)
        ).first()
    finally:
        db.close()

def create_or_update_custom_parser(tenant_id: str, source_id: int, parser_code: str):
    """
    Creates or updates a custom parser for a specific tenant and source.
    """
    db = SessionLocal()
    try:
        custom_parser = db.query(TenantSourceParser).filter(
            (TenantSourceParser.tenant_id == tenant_id) & (TenantSourceParser.source_id == source_id)
        ).first()
        if custom_parser:
            custom_parser.parser_code = parser_code
        else:
            custom_parser = TenantSourceParser(
                tenant_id=tenant_id,
                source_id=source_id,
                parser_code=parser_code
            )
            db.add(custom_parser)
        db.commit()
        db.refresh(custom_parser)
        print(f"DATABASE: Successfully created/updated custom parser for tenant {tenant_id}, source {source_id}.")
        return custom_parser
    except Exception as e:
        db.rollback()
        print(f"DATABASE: Error creating/updating custom parser for tenant {tenant_id}, source {source_id}: {e}")
        return None
    finally:
        db.close()
