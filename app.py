import os
import json
import re
import base64
import shutil
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Union
import uuid
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form, Request, status, Cookie, Response
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
import jwt
import bcrypt
from dotenv import load_dotenv

import gemini_utils

load_dotenv()

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "pocketsmart_super_secure_jwt_secret_key_2026_smartbridge")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
UPLOADS_DIR = os.path.join(STATIC_DIR, "uploads")
DATA_DIR = os.path.join(BASE_DIR, "data")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

USERS_FILE = os.path.join(DATA_DIR, "users.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

# In-memory session and token storage
active_sessions: Dict[str, Dict[str, Any]] = {}
blacklisted_tokens = set()

# Models
class RegisterUser(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None
    password: str

class UserInDB(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None
    hashed_password: str
    created_at: str

class Token(BaseModel):
    access_token: str
    token_type: str

class HomeBudgetInput(BaseModel):
    total_budget: float
    num_lights: int = 5
    num_fans: int = 4
    num_furniture: int = 2
    num_dining_tables: int = 1
    has_living_room: bool = True
    has_kitchen: bool = False
    has_bedroom: bool = False
    additional_requirements: Optional[str] = None

class PartyBudgetInput(BaseModel):
    total_budget: float
    num_guests: int = 20
    party_type: str = "Birthday"
    venue_type: str = "Home"
    needs_catering: bool = True
    needs_decoration: bool = True
    needs_entertainment: bool = True
    additional_requirements: Optional[str] = None

class JewelryBudgetInput(BaseModel):
    total_budget: float
    occasion: str = "Wedding"
    preferences: Optional[str] = None


# Persistence helper functions
def load_users() -> Dict[str, dict]:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_users(users: Dict[str, dict]):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        print(f"Error saving users: {e}")

def load_history() -> Dict[str, List[dict]]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_history_db(history: Dict[str, List[dict]]):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error saving history: {e}")

# In-memory representations backed by persistent files
users_db = load_users()
user_recommendations = load_history()

# Seed default demo user if not exists
def init_seed_users():
    if "sai" not in users_db:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw("password123".encode("utf-8"), salt).decode("utf-8")
        users_db["sai"] = {
            "username": "sai",
            "email": "sai@example.com",
            "full_name": "Sai Kumar",
            "hashed_password": hashed,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        save_users(users_db)

    # Seed sample history for demo user if empty
    if "sai" not in user_recommendations or len(user_recommendations["sai"]) == 0:
        sample_time = datetime.now(timezone.utc).strftime("%b %d, %Y, %I:%M %p")
        user_recommendations["sai"] = [
            {
                "id": str(uuid.uuid4()),
                "timestamp": sample_time,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "recommendation_type": "jewelry",
                "type": "jewelry",
                "input_summary": "Wedding • ₹25,000 • Outfit: Traditional Banarasi",
                "result_summary": "₹25,000 (Remaining: ₹800)",
                "input_data": {"total_budget": 25000, "occasion": "Wedding", "preferences": "Traditional Kundan & Gold"},
                "full_result": {
                    "total_budget": 25000,
                    "remaining_budget": 800,
                    "outfit_analysis": {"colors": "Royal Blue & Gold", "style": "Traditional Banarasi Silk", "formality": "Formal Festive"},
                    "jewelry_recommendations": [
                        {"item_type": "Choker Necklace", "description": "22k Gold plated Kundan choker with emerald bead drops", "style": "Kundan", "estimated_price": 12000, "shopping_links": {"amazon": "https://www.amazon.in/s?k=kundan+choker", "tanishq": "https://www.tanishq.co.in"}},
                        {"item_type": "Meenakari Jhumkas", "description": "Matching Jhumkas with intricate meenakari work", "style": "Meenakari", "estimated_price": 7500, "shopping_links": {"amazon": "https://www.amazon.in/s?k=meenakari+jhumka", "caratlane": "https://www.caratlane.com"}},
                        {"item_type": "Bridal Kada Bangles", "description": "Set of 2 embellished kada bangles with zircon accents", "style": "Bridal", "estimated_price": 4700, "shopping_links": {"amazon": "https://www.amazon.in/s?k=bridal+kada+bangles", "bluestone": "https://www.bluestone.com"}}
                    ],
                    "styling_tips": ["Pair the choker with a sweetheart neckline.", "Match gold tones across all pieces."]
                }
            },
            {
                "id": str(uuid.uuid4()),
                "timestamp": (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%b %d, %Y, %I:%M %p"),
                "created_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                "recommendation_type": "party",
                "type": "party",
                "input_summary": "Birthday • 25 Guests • Venue: Home",
                "result_summary": "₹30,000 (Remaining: ₹500)",
                "input_data": {"total_budget": 30000, "num_guests": 25, "party_type": "Birthday", "venue_type": "Home"},
                "full_result": {
                    "total_budget": 30000,
                    "remaining_budget": 500,
                    "budget_breakdown": [
                        {"category": "catering", "allocation": 15000, "items": [{"name": "Party Buffet Box & Starters", "description": "Multi-course feast for 25 guests", "estimated_price": 600, "quantity": 25, "shopping_links": {"swiggy": "https://www.swiggy.com", "zomato": "https://www.zomato.com"}}]},
                        {"category": "decoration", "allocation": 5500, "items": [{"name": "Metallic Balloon Arch & Banner", "description": "Happy Birthday neon & balloons", "estimated_price": 5500, "quantity": 1, "shopping_links": {"amazon": "https://www.amazon.in/s?k=birthday+balloon+arch", "meesho": "https://www.meesho.com"}}]},
                        {"category": "entertainment", "allocation": 5000, "items": [{"name": "Karaoke & Wireless Sound System", "description": "Bluetooth party speaker", "estimated_price": 5000, "quantity": 1, "shopping_links": {"bookmyshow": "https://in.bookmyshow.com"}}]},
                        {"category": "contingency", "allocation": 4000, "items": [{"name": "Tableware & Drinks Buffer", "description": "Cutlery and extra ice/refreshments", "estimated_price": 4000, "quantity": 1, "shopping_links": {"bigbasket": "https://www.bigbasket.com"}}]}
                    ],
                    "calculation_table_inr": [
                        {"category": "Catering", "items_count": 25, "total_cost": 15000, "percentage_of_budget": 50.0},
                        {"category": "Decoration", "items_count": 1, "total_cost": 5500, "percentage_of_budget": 18.3},
                        {"category": "Entertainment", "items_count": 1, "total_cost": 5000, "percentage_of_budget": 16.7},
                        {"category": "Contingency", "items_count": 1, "total_cost": 4000, "percentage_of_budget": 13.3}
                    ],
                    "venue_suggestions": [{"name": "Home Living Room & Terrace", "type": "Home", "capacity": 35, "estimated_cost": 0, "search_links": {"google": "https://www.google.com"}}],
                    "additional_suggestions": ["Order finger foods in advance via Swiggy.", "Set up a photo corner with ring light."]
                }
            },
            {
                "id": str(uuid.uuid4()),
                "timestamp": (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%b %d, %Y, %I:%M %p"),
                "created_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                "recommendation_type": "home",
                "type": "home",
                "input_summary": "Living Room, Kitchen • 5 Lights • 4 Fans • 2 Furniture",
                "result_summary": "₹50,000 (Remaining: ₹1,200)",
                "input_data": {"total_budget": 50000, "num_lights": 5, "num_fans": 4, "num_furniture": 2, "num_dining_tables": 1},
                "full_result": {
                    "total_budget": 50000,
                    "remaining_budget": 1200,
                    "budget_breakdown": [
                        {"category": "Lighting", "allocation": 6500, "items": [{"name": "Philips Warm LED Recessed Panels", "description": "Energy saving 15W LED light pack", "estimated_price": 1300, "quantity": 5, "shopping_links": {"amazon": "https://www.amazon.in", "ikea": "https://www.ikea.com"}}]},
                        {"category": "Ceiling Fans", "allocation": 12000, "items": [{"name": "Atomberg BLDC Smart Remote Fans", "description": "5-star energy saving BLDC ceiling fan", "estimated_price": 3000, "quantity": 4, "shopping_links": {"amazon": "https://www.amazon.in", "flipkart": "https://www.flipkart.com"}}]},
                        {"category": "Furniture", "allocation": 18500, "items": [{"name": "Contemporary Fabric 3-Seater Sofa", "description": "Comfortable wooden frame sofa", "estimated_price": 18500, "quantity": 1, "shopping_links": {"ikea": "https://www.ikea.com", "flipkart": "https://www.flipkart.com"}}]},
                        {"category": "Dining & Tables", "allocation": 11800, "items": [{"name": "Solid Sheesham Wood 4-Seater Dining Set", "description": "Minimalist dining table with chairs", "estimated_price": 11800, "quantity": 1, "shopping_links": {"ikea": "https://www.ikea.com", "amazon": "https://www.amazon.in"}}]}
                    ],
                    "calculation_table": [
                        {"category": "Lighting", "items_count": 5, "total_cost": 6500, "percentage_of_budget": 13.0},
                        {"category": "Ceiling Fans", "items_count": 4, "total_cost": 12000, "percentage_of_budget": 24.0},
                        {"category": "Furniture", "items_count": 1, "total_cost": 18500, "percentage_of_budget": 37.0},
                        {"category": "Dining & Tables", "items_count": 1, "total_cost": 11800, "percentage_of_budget": 23.6}
                    ],
                    "additional_suggestions": ["Opt for BLDC fans for up to 65% power savings.", "Use warm 3000K lighting in living room for an inviting feel."]
                }
            }
        ]
        save_history_db(user_recommendations)

init_seed_users()

# Background Session Cleanup Task
async def cleanup_expired_sessions():
    """Background task to clean up expired user sessions inactive for > 30 minutes"""
    while True:
        try:
            current_time = datetime.now(timezone.utc)
            expired_sessions = []
            for username, session in list(active_sessions.items()):
                last_act = session.get("last_activity")
                if last_act is not None:
                    if isinstance(last_act, str):
                        try:
                            last_act = datetime.fromisoformat(last_act)
                        except Exception:
                            last_act = current_time
                    if hasattr(last_act, "tzinfo") and last_act.tzinfo is None:
                        last_act = last_act.replace(tzinfo=timezone.utc)
                    if (current_time - last_act).total_seconds() > 1800:  # 30 minutes
                        expired_sessions.append(username)
            for username in expired_sessions:
                print(f"Removing expired session for {username}")
                active_sessions.pop(username, None)
        except Exception as e:
            print(f"Session cleanup error: {e}")
        await asyncio.sleep(300)  # Check every 5 minutes

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    task = asyncio.create_task(cleanup_expired_sessions())
    yield
    # Shutdown
    task.cancel()

# Initialize FastAPI App
app = FastAPI(
    title="PocketSmart: AI Budget Planner",
    description="Your Smart Budget & Recommendation Assistant using Google Gemini AI",
    version="2.0.0",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static and templates
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

def render_template(request: Request, name: str, context: Optional[dict] = None, status_code: int = 200) -> HTMLResponse:
    ctx = {"request": request}
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request=request, name=name, context=ctx, status_code=status_code)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


# Auth and Security Helpers
def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "sub": data.get("sub", "")})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_token(request: Request) -> Optional[str]:
    # 1. Check Authorization Bearer header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
    # 2. Check cookie
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        if cookie_token.startswith("Bearer "):
            return cookie_token.split(" ")[1]
        return cookie_token
    return None

async def get_current_user_optional(request: Request) -> Optional[UserInDB]:
    token = await get_token(request)
    if not token or token in blacklisted_tokens:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username or username not in users_db:
            return None
        user_raw = users_db[username]
        # Update session activity
        if username in active_sessions:
            active_sessions[username]["last_activity"] = datetime.now(timezone.utc)
        else:
            active_sessions[username] = {
                "username": username,
                "login_time": datetime.now(timezone.utc),
                "last_activity": datetime.now(timezone.utc),
                "token": token,
                "user_data": {}
            }
        return UserInDB(**user_raw)
    except Exception:
        return None

async def get_current_active_user(request: Request) -> UserInDB:
    user = await get_current_user_optional(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def save_to_history(username: str, recommendation_type: str, input_data: dict, result: dict):
    if username not in user_recommendations:
        user_recommendations[username] = []
    
    # Create descriptive summary
    summary_input = ""
    if recommendation_type == "home":
        rooms = []
        if input_data.get("has_living_room"): rooms.append("Living")
        if input_data.get("has_kitchen"): rooms.append("Kitchen")
        if input_data.get("has_bedroom"): rooms.append("Bedroom")
        rooms_str = ", ".join(rooms) if rooms else "General"
        summary_input = f"{rooms_str} • {input_data.get('num_lights', 0)} Lights, {input_data.get('num_fans', 0)} Fans"
    elif recommendation_type == "party":
        summary_input = f"{input_data.get('party_type', 'Event')} • {input_data.get('num_guests', 0)} Guests • {input_data.get('venue_type', 'Venue')}"
    elif recommendation_type == "jewelry":
        summary_input = f"{input_data.get('occasion', 'Event')} • {input_data.get('preferences', 'Styling')}"

    tot = result.get("total_budget", input_data.get("total_budget", 0))
    rem = result.get("remaining_budget", 0)
    result_summary = f"₹{tot:,.0f} (Remaining: ₹{rem:,.0f})"

    item_id = str(uuid.uuid4())
    record = {
        "id": item_id,
        "timestamp": datetime.now(timezone.utc).strftime("%b %d, %Y, %I:%M %p"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recommendation_type": recommendation_type,
        "type": recommendation_type,
        "input_summary": summary_input,
        "result_summary": result_summary,
        "input_data": input_data,
        "full_result": result
    }
    user_recommendations[username].insert(0, record)
    save_history_db(user_recommendations)
    return item_id


# =====================================================================
# HTML PAGES & AUTHENTICATION ROUTING
# =====================================================================

@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    """Landing Home Page with Hero, Feature cards, Testimonials, CTA and Footer"""
    user = await get_current_user_optional(request)
    return render_template(request, "index.html", {"user": user})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page or redirect to dashboard if logged in"""
    user = await get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return render_template(request, "login.html", {"user": None, "error": None})


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    """Process login form submission"""
    user_data = users_db.get(username.strip())
    if not user_data or not verify_password(password, user_data.get("hashed_password", "")):
        return render_template(
            request, 
            "login.html", 
            {"user": None, "error": "Invalid username or password. Please try again."},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    # Issue JWT Token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(data={"sub": username}, expires_delta=access_token_expires)

    # Track active session
    active_sessions[username] = {
        "username": username,
        "login_time": datetime.now(timezone.utc),
        "last_activity": datetime.now(timezone.utc),
        "token": token,
        "user_data": active_sessions.get(username, {}).get("user_data", {})
    }

    # Redirect to dashboard with HTTPOnly cookie
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    return response


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Serve registration page"""
    user = await get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return render_template(request, "register.html", {"user": None, "error": None})


@app.post("/register")
async def register_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Handle new user registration"""
    username = username.strip()
    email = email.strip()
    
    if not username or not email or not password:
        return render_template(
            request,
            "register.html",
            {"user": None, "error": "All fields are required."},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if password != confirm_password:
        return render_template(
            request,
            "register.html",
            {"user": None, "error": "Passwords do not match."},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if username in users_db:
        return render_template(
            request,
            "register.html",
            {"user": None, "error": f"Username '{username}' is already taken. Please choose another."},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    # Hash and save
    hashed = get_password_hash(password)
    users_db[username] = {
        "username": username,
        "email": email,
        "full_name": username.title(),
        "hashed_password": hashed,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    save_users(users_db)

    # Create session & token
    token = create_access_token(data={"sub": username})
    active_sessions[username] = {
        "username": username,
        "login_time": datetime.now(timezone.utc),
        "last_activity": datetime.now(timezone.utc),
        "token": token,
        "user_data": {}
    }

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    return response


@app.get("/logout")
@app.post("/logout")
async def logout(request: Request):
    """Logout user, blacklist token, clear cookie and redirect to login"""
    token = await get_token(request)
    if token:
        blacklisted_tokens.add(token)
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            if username in active_sessions:
                del active_sessions[username]
        except Exception:
            pass
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token")
    return response


@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 compatible token login, returns JSON token"""
    username = form_data.username.strip()
    user = users_db.get(username)
    if not user or not verify_password(form_data.password, user.get("hashed_password", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": username}, expires_delta=access_token_expires)

    active_sessions[username] = {
        "username": username,
        "login_time": datetime.now(timezone.utc),
        "last_activity": datetime.now(timezone.utc),
        "token": access_token,
        "user_data": active_sessions.get(username, {}).get("user_data", {})
    }

    response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    return response


# =====================================================================
# SESSION INFORMATION ENDPOINTS
# =====================================================================

@app.get("/session-info")
async def get_session_info(current_user: UserInDB = Depends(get_current_active_user)):
    """Retrieve metadata about the current user session"""
    if current_user.username in active_sessions:
        session = active_sessions[current_user.username]
        login_time = session.get("login_time")
        if isinstance(login_time, str):
            try:
                login_time = datetime.fromisoformat(login_time)
            except Exception:
                login_time = datetime.now(timezone.utc)
        if hasattr(login_time, "tzinfo") and login_time.tzinfo is None:
            login_time = login_time.replace(tzinfo=timezone.utc)
        session_duration = int((datetime.now(timezone.utc) - login_time).total_seconds() // 60) if login_time else 0
        return {
            "username": session.get("username"),
            "login_time": str(session.get("login_time")),
            "last_activity": str(session.get("last_activity")),
            "session_duration_minutes": session_duration,
            "user_data": session.get("user_data", {})
        }
    raise HTTPException(status_code=404, detail="No active session found")


@app.post("/session-data")
async def update_session_data(
    data: Dict[str, Any],
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Update session data for personalization and recommendation tracking"""
    if current_user.username in active_sessions:
        active_sessions[current_user.username]["user_data"].update(data)
        active_sessions[current_user.username]["last_activity"] = datetime.now(timezone.utc)
        return {
            "message": "Session data updated",
            "data": active_sessions[current_user.username]["user_data"]
        }
    raise HTTPException(status_code=404, detail="No active session found")


# =====================================================================
# USER DASHBOARD
# =====================================================================

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """User Dashboard page with welcome greeting, planner cards, and recent history"""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    recent_history = user_recommendations.get(user.username, [])[:5]
    return render_template(request, "dashboard.html", {
        "user": user,
        "recent_history": recent_history
    })


# =====================================================================
# 1. HOME INTERIOR PLANNER ROUTES
# =====================================================================

@app.get("/home-planner", response_class=HTMLResponse)
async def home_planner_page(request: Request):
    """Home budget planner page"""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return render_template(request, "home_planner.html", {"user": user})


@app.post("/home-budget")
@app.post("/generate-home")
async def plan_home_budget(
    budget_input: HomeBudgetInput,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Generate home budget recommendations and save to history & session"""
    try:
        # Update session data
        if current_user.username in active_sessions:
            active_sessions[current_user.username]["user_data"]["last_home_budget"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "budget": budget_input.total_budget,
                "requirements": {
                    "lights": budget_input.num_lights,
                    "fans": budget_input.num_fans,
                    "furniture": budget_input.num_furniture,
                    "dining_tables": budget_input.num_dining_tables
                }
            }

        # Generate AI recommendations
        result = gemini_utils.get_home_recommendations(budget_input)

        # Save to history
        rec_id = save_to_history(
            username=current_user.username,
            recommendation_type="home",
            input_data=budget_input.model_dump(),
            result=result
        )
        result["recommendation_id"] = rec_id
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {str(e)}")


# =====================================================================
# 2. PARTY PLANNER ROUTES
# =====================================================================

@app.get("/party-planner", response_class=HTMLResponse)
async def party_planner_page(request: Request):
    """Party budget planner page"""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return render_template(request, "party_planner.html", {"user": user})


@app.post("/party-budget")
@app.post("/generate-party")
async def plan_party_budget(
    budget_input: PartyBudgetInput,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Generate party budget recommendations and save to history & session"""
    try:
        if current_user.username in active_sessions:
            active_sessions[current_user.username]["user_data"]["last_party_budget"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "budget": budget_input.total_budget,
                "party_type": budget_input.party_type,
                "guests": budget_input.num_guests
            }

        result = gemini_utils.get_party_recommendations(budget_input)

        rec_id = save_to_history(
            username=current_user.username,
            recommendation_type="party",
            input_data=budget_input.model_dump(),
            result=result
        )
        result["recommendation_id"] = rec_id
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {str(e)}")


# =====================================================================
# 3. JEWELRY PLANNER ROUTES (TEXT + OPTIONAL IMAGE)
# =====================================================================

@app.get("/jewelry-planner", response_class=HTMLResponse)
async def jewelry_planner_page(request: Request):
    """Jewelry budget planner page"""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return render_template(request, "jewelry_planner.html", {"user": user})


@app.post("/jewelry-budget")
@app.post("/generate-jewelry")
async def plan_jewelry_budget(
    total_budget: float = Form(...),
    occasion: str = Form(...),
    preferences: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Generate jewelry recommendations with optional outfit image upload"""
    try:
        image_path = None
        saved_filename = None
        if image and image.filename:
            file_extension = os.path.splitext(image.filename)[1].lower()
            if not file_extension:
                file_extension = ".jpg"
            saved_filename = f"{uuid.uuid4()}{file_extension}"
            image_path = os.path.join(UPLOADS_DIR, saved_filename)
            with open(image_path, "wb") as buffer:
                shutil.copyfileobj(image.file, buffer)

        budget_input = JewelryBudgetInput(
            total_budget=total_budget,
            occasion=occasion,
            preferences=preferences
        )

        if current_user.username in active_sessions:
            active_sessions[current_user.username]["user_data"]["last_jewelry_budget"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "budget": budget_input.total_budget,
                "occasion": budget_input.occasion,
                "has_image": image_path is not None
            }

        result = gemini_utils.get_jewelry_recommendations(budget_input, image_path)
        if saved_filename:
            result["uploaded_image_url"] = f"/static/uploads/{saved_filename}"

        input_data = budget_input.model_dump()
        if saved_filename:
            input_data["image"] = saved_filename

        rec_id = save_to_history(
            username=current_user.username,
            recommendation_type="jewelry",
            input_data=input_data,
            result=result
        )
        result["recommendation_id"] = rec_id
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating recommendations: {str(e)}")


# =====================================================================
# HISTORY AND DETAILS ROUTES
# =====================================================================

@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    """Recommendation history page"""
    user = await get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    history_items = user_recommendations.get(user.username, [])
    return render_template(request, "history.html", {
        "user": user,
        "history": history_items
    })


@app.get("/recommendation-history")
async def get_recommendation_history(current_user: UserInDB = Depends(get_current_active_user)):
    """Retrieve all recommendation queries for current user in JSON format"""
    if current_user.username not in user_recommendations:
        return {"history": []}

    history = sorted(
        user_recommendations[current_user.username],
        key=lambda x: x.get("created_at", ""),
        reverse=True
    )
    
    history_data = []
    for item in history:
        history_data.append({
            "id": item.get("id"),
            "timestamp": item.get("timestamp"),
            "type": item.get("recommendation_type") or item.get("type"),
            "input": item.get("input_summary"),
            "summary": item.get("result_summary")
        })
    return {"history": history_data}


@app.get("/recommendations-details/{recommendation_id}")
async def get_recommendation_details(
    recommendation_id: str,
    current_user: UserInDB = Depends(get_current_active_user)
):
    """Get the full details of a specific past recommendation"""
    if current_user.username not in user_recommendations:
        raise HTTPException(status_code=404, detail="No recommendations found")

    for item in user_recommendations[current_user.username]:
        if item.get("id") == recommendation_id:
            return {
                "id": item.get("id"),
                "timestamp": item.get("timestamp"),
                "type": item.get("recommendation_type") or item.get("type"),
                "input": item.get("input_summary"),
                "input_data": item.get("input_data"),
                "full_result": item.get("full_result")
            }

    raise HTTPException(status_code=404, detail="Recommendation not found")


# Main Entry Point
if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading

    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    display_host = "localhost" if host in ["0.0.0.0", "127.0.0.1"] else host
    app_url = f"http://{display_host}:{port}"

    print("\n" + "=" * 60)
    print(" 🚀 PocketSmart: AI Budget & Recommendation Assistant")
    print("=" * 60)
    print(f" 🌐 Default Application Link: {app_url}")
    print(f" 📖 API Documentation:        {app_url}/docs")
    print(f" 📡 Server Address:           http://{host}:{port}")
    print("=" * 60 + "\n")

    def open_browser():
        import time
        time.sleep(1.2)
        try:
            webbrowser.open(app_url)
        except Exception:
            pass

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("app:app", host=host, port=port, reload=True)

