from fastapi import FastAPI, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import Annotated, List, Optional
from datetime import timedelta

from database import SessionLocal, create_user, get_user_by_username, create_tenant, get_tenant_by_name, get_tenant_by_id, get_all_progress_items
from database import get_llm_config_for_tenant, create_or_update_llm_config, TenantLLMConfig # Import TenantLLMConfig for response model
from database import get_all_sources, add_new_source, update_source, delete_source # Import source management functions
from database import get_followed_terms, add_followed_term, delete_followed_term # Import followed term functions
from auth_utils import create_access_token, create_refresh_token, verify_token, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS
from pydantic import BaseModel

# --- Pydantic Models ---
class UserCreate(BaseModel):
    email: str
    password: str
    tenant_name: str
    # Removed is_admin: bool = False

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    # refresh_token: Optional[str] = None # Refresh token will be in HttpOnly cookie

class UserInDB(BaseModel):
    id: str
    username: str
    tenant_id: str
    is_admin: bool

class CurrentUser(BaseModel):
    id: str
    username: str
    tenant_id: str
    is_admin: bool

class ProgressItemResponse(BaseModel):
    id: int
    url: str
    source: str
    published_date: str # Or datetime.date if you prefer
    analysis_data: dict
    title: str
    keywords: List[str]
    overall_importance_score: float

    class Config:
        from_attributes = True

class LLMConfigBase(BaseModel):
    llm_provider: str
    llm_model_name: str
    api_key: str
    base_url: Optional[str] = None
    custom_settings: Optional[dict] = None

class LLMConfigCreate(LLMConfigBase):
    pass # Inherits all fields from LLMConfigBase

class LLMConfigResponse(BaseModel):
    llm_provider: str
    llm_model_name: str
    base_url: Optional[str] = None
    custom_settings: Optional[dict] = None
    # api_key is not returned for security reasons

class SourceBase(BaseModel):
    name: str
    url: str
    source_type: str
    is_active: bool = True

class SourceCreate(SourceBase):
    is_shared: bool = False # Only system admin can set this

class SourceUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    source_type: Optional[str] = None
    is_active: Optional[bool] = None

class SourceResponse(SourceBase):
    id: int
    tenant_id: str
    is_shared: bool
    class Config:
        from_attributes = True # Enable ORM mode

class FollowedTermBase(BaseModel):
    term: str

class FollowedTermCreate(FollowedTermBase):
    pass

class FollowedTermResponse(FollowedTermBase):
    id: int
    tenant_id: str
    class Config:
        from_attributes = True # Enable ORM mode


# --- FastAPI App Initialization ---
app = FastAPI()

# --- Healthcheck endpoint ---
@app.get("/")
async def root():
    return {"message": "FastAPI is running"}

# --- OAuth2PasswordBearer for token handling ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- Dependency to get DB session ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Dependency to get current user ---
async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: Annotated[Session, Depends(get_db)]):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = verify_token(token)
    if payload is None:
        raise credentials_exception
    
    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception
    
    user = get_user_by_username(username) # Use the utility function
    if user is None:
        raise credentials_exception
    
    return CurrentUser(id=user.id, username=user.username, tenant_id=user.tenant_id, is_admin=user.is_admin)

# --- Routes ---

@app.post("/register", response_model=Token)
def register_user_api(user_data: UserCreate, response: Response, db: Annotated[Session, Depends(get_db)]):
    # Basic email validation
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", user_data.email):
        raise HTTPException(status_code=400, detail="Invalid email address format.")

    tenant = get_tenant_by_name(user_data.tenant_name)
    if not tenant:
        tenant = create_tenant(name=user_data.tenant_name)
        if not tenant:
            raise HTTPException(status_code=400, detail="Could not create tenant")

    # Always create users as non-admin through this endpoint
    user = create_user(tenant_id=tenant.id, username=user_data.email, password=user_data.password, is_admin=False)
    if not user:
        raise HTTPException(status_code=400, detail="Email already registered or could not create user")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "tenant_id": user.tenant_id, "is_admin": user.is_admin},
        expires_delta=access_token_expires
    )

    refresh_token_expires = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_token = create_refresh_token(
        data={"sub": user.username},
        expires_delta=refresh_token_expires
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="strict",
        secure=True, # Only send cookie over HTTPS
        max_age=int(refresh_token_expires.total_seconds())
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/token", response_model=Token)
def login_for_access_token(response: Response, form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: Annotated[Session, Depends(get_db)]):
    user = get_user_by_username(form_data.username)
    if not user or not user.verify_password(form_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "tenant_id": user.tenant_id, "is_admin": user.is_admin},
        expires_delta=access_token_expires
    )

    refresh_token_expires = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_token = create_refresh_token(
        data={"sub": user.username},
        expires_delta=refresh_token_expires
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="strict",
        secure=True, # Only send cookie over HTTPS
        max_age=int(refresh_token_expires.total_seconds())
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/refresh", response_model=Token)
async def refresh_token(request: Request, response: Response, db: Annotated[Session, Depends(get_db)]):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not found")

    payload = verify_token(refresh_token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token payload")

    user = get_user_by_username(username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    new_access_token = create_access_token(
        data={"sub": user.username, "tenant_id": user.tenant_id, "is_admin": user.is_admin},
        expires_delta=access_token_expires
    )

    # Optionally, rotate refresh token (issue a new one)
    new_refresh_token_expires = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    new_refresh_token = create_refresh_token(
        data={"sub": user.username},
        expires_delta=new_refresh_token_expires
    )

    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        samesite="strict",
        secure=True,
        max_age=int(new_refresh_token_expires.total_seconds())
    )
    return {"access_token": new_access_token, "token_type": "bearer"}

@app.get("/users/me/", response_model=CurrentUser)
async def read_users_me(current_user: Annotated[CurrentUser, Depends(get_current_user)]):
    return current_user

# --- Tenant-aware data endpoints ---
@app.get("/progress_items/", response_model=List[ProgressItemResponse])
async def get_progress_items_api(current_user: Annotated[CurrentUser, Depends(get_current_user)]):
    items = get_all_progress_items(current_user.tenant_id)
    return items

@app.get("/llm_config/", response_model=LLMConfigResponse)
async def get_llm_config_api(current_user: Annotated[CurrentUser, Depends(get_current_user)]):
    llm_config = get_llm_config_for_tenant(current_user.tenant_id)
    if not llm_config:
        raise HTTPException(status_code=404, detail="LLM configuration not found for this tenant.")
    return llm_config

@app.post("/llm_config/", response_model=LLMConfigResponse)
async def create_update_llm_config_api(llm_config_data: LLMConfigCreate, current_user: Annotated[CurrentUser, Depends(get_current_user)]):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only tenant administrators can configure LLM settings.")
    
    llm_config = create_or_update_llm_config(
        tenant_id=current_user.tenant_id,
        llm_provider=llm_config_data.llm_provider,
        llm_model_name=llm_config_data.llm_model_name,
        api_key=llm_config_data.api_key,
        base_url=llm_config_data.base_url,
        custom_settings=llm_config_data.custom_settings
    )
    if not llm_config:
        raise HTTPException(status_code=500, detail="Failed to save LLM configuration.")
    return llm_config

# --- Source Management Endpoints ---
@app.get("/sources/", response_model=List[SourceResponse])
async def get_sources_api(current_user: Annotated[CurrentUser, Depends(get_current_user)]):
    sources = get_all_sources(current_user.tenant_id)
    return sources

@app.post("/sources/", response_model=SourceResponse)
async def create_source_api(source_data: SourceCreate, current_user: Annotated[CurrentUser, Depends(get_current_user)]):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only tenant administrators can add sources.")
    
    # Prevent non-system admins from creating shared sources
    if source_data.is_shared and current_user.tenant_id != "system_shared_sources": # Assuming a fixed ID for system admin tenant
        raise HTTPException(status_code=403, detail="Only system administrators can create shared sources.")

    new_source = add_new_source(
        name=source_data.name,
        url=source_data.url,
        source_type=source_data.source_type,
        tenant_id=current_user.tenant_id,
        is_shared=source_data.is_shared
    )
    if not new_source:
        raise HTTPException(status_code=400, detail="Failed to add source. It might already exist or there was a database error.")
    return new_source

@app.put("/sources/{source_id}", response_model=SourceResponse)
async def update_source_api(source_id: int, source_data: SourceUpdate, current_user: Annotated[CurrentUser, Depends(get_current_user)]):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only tenant administrators can update sources.")
    
    success = update_source(source_id, source_data.model_dump(exclude_unset=True), current_user.tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Source not found or not accessible by your tenant.")
    
    # Fetch the updated source to return in the response
    updated_source = get_all_sources(current_user.tenant_id) # This returns a list, need to find the specific one
    updated_source = next((s for s in updated_source if s.id == source_id), None)
    if not updated_source:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated source.")
    return updated_source

@app.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_api(source_id: int, current_user: Annotated[CurrentUser, Depends(get_current_user)]):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only tenant administrators can delete sources.")
    
    success = delete_source(source_id, current_user.tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Source not found, not owned by your tenant, or is a shared source and cannot be deleted.")
    return

# --- Followed Terms Endpoints ---
@app.get("/followed_terms/", response_model=List[FollowedTermResponse])
async def get_followed_terms_api(current_user: Annotated[CurrentUser, Depends(get_current_user)]):
    terms = get_followed_terms(current_user.tenant_id)
    return terms

@app.post("/followed_terms/", response_model=FollowedTermResponse)
async def add_followed_term_api(term_data: FollowedTermCreate, current_user: Annotated[CurrentUser, Depends(get_current_user)]):
    new_term = add_followed_term(term_data.term.lower(), current_user.tenant_id)
    if not new_term:
        raise HTTPException(status_code=400, detail="Term already followed or could not add term.")
    return new_term

@app.delete("/followed_terms/{term_to_delete}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_followed_term_api(term_to_delete: str, current_user: Annotated[CurrentUser, Depends(get_current_user)]):
    success = delete_followed_term(term_to_delete.lower(), current_user.tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Term not found or not followed by your tenant.")
    return

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)