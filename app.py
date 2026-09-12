import streamlit as st
import os
import json
import base64
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import time
from datetime import datetime, timezone
import streamlit.components.v1 as components

# --- Open the secure vault & Bridge Streamlit Cloud Secrets ---
load_dotenv()

def get_secret(key, default=None):
    if key in os.environ and os.environ[key]:
        return os.environ[key]
    try:
        if key in st.secrets and st.secrets[key]:
            return st.secrets[key]
    except Exception:
        pass
    return default

MASTER_API_KEY = get_secret("GEMINI_API_KEY")
CLIENT_ID = get_secret("GOOGLE_CLIENT_ID")
CLIENT_SECRET = get_secret("GOOGLE_CLIENT_SECRET")

# Dynamic Routing: Uses Cloud URL unless REDIRECT_URI is explicitly set in .env for localhost
REDIRECT_URI = get_secret("REDIRECT_URI", "https://cruise-comment-ai.streamlit.app") 

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# --- Page Config ---
st.set_page_config(layout="wide", page_title="Cruise Comment", initial_sidebar_state="expanded")

# --- Persistent Context Storage ---
CONTEXT_FILE = ".cruise_context"
KEYS_FILE = ".cruise_keys.json"
TOKENS_FILE = ".youtube_tokens.json"
VERIFIERS_FILE = ".oauth_verifiers.json"

loaded_context = ""
if os.path.exists(CONTEXT_FILE):
    with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
        loaded_context = f.read().strip()

saved_keys = {}
if os.path.exists(KEYS_FILE):
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            saved_keys = json.load(f)
    except Exception:
        saved_keys = {}

def update_persisted_keys(api_key=None, client_id=None, client_secret=None):
    if os.path.exists(KEYS_FILE):
        try:
            with open(KEYS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}
    if api_key is not None: data["api_key"] = api_key.strip()
    if client_id is not None: data["client_id"] = client_id.strip()
    if client_secret is not None: data["client_secret"] = client_secret.strip()
    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)

def save_verifier(state, verifier):
    data = {}
    if os.path.exists(VERIFIERS_FILE):
        try:
            with open(VERIFIERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except: pass
    data[state] = verifier
    with open(VERIFIERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)

def get_verifier(state):
    if os.path.exists(VERIFIERS_FILE):
        try:
            with open(VERIFIERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(state)
        except: pass
    return None

# --- Initialize ALL Session States Safely ---
defaults = {
    "youtube_creds": None,
    "channel_id": None,           
    "channel_name": "YouTube Account", 
    "channel_logo": "",           
    "replied_comments": set(),
    "sent_replies_log": {},
    "processed_history": [], 
    "ai_drafts": {},
    "ai_errors": {},
    "user_gemini_api_key": saved_keys.get("api_key", ""),
    "user_client_id": saved_keys.get("client_id", ""),
    "user_client_secret": saved_keys.get("client_secret", ""),
    "saved_channel_context": loaded_context, 
    "context_locked": bool(loaded_context),  
    "global_mood": "Friendly",
    "global_length": "Medium",
    "global_ai_mode": "Standard", 
    "video_title_cache": {},
    "video_desc_cache": {},
    "selected_video_filter": "All Videos",
    "video_mapping_cache": {},
    "channel_comments": [],
    "master_comments_cache": [],
    "auto_reply_queue": [],   
    "auto_reply_total": 0,    
    "auto_reply_success": 0,
    "auto_reply_paused": False,
    "last_scrolled_id": None,
    "autopilot_active": False,
    "autopilot_interval": 5,
    "session_visible_handled": set(),
    "queue_warning": None,
    "active_ai_model": "gemini-3.5-flash"
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# Load Persisted Session Tokens so Refresh Doesn't Log User Out
if st.session_state["youtube_creds"] is None and os.path.exists(TOKENS_FILE):
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            st.session_state["youtube_creds"] = json.load(f)
    except Exception:
        pass

def get_relative_time(dt):
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 10: return "just now"
    if seconds < 60: return f"{seconds} seconds ago"
    minutes = seconds // 60
    if minutes < 60: return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24: return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30: return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    if months < 12: return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"

# Original Minimal layout styling
st.markdown("""
    
""", unsafe_allow_html=True)

# --- Handle OAuth Callback ---
query_params = st.query_params
if "code" in query_params and st.session_state.get("youtube_creds") is None:
    code = query_params.get("code")
    state_param = query_params.get("state", "")
    
    if isinstance(code, list): code = code[0]
    if isinstance(state_param, list): state_param = state_param[0]
    
    try:
        active_cid = saved_keys.get("client_id") or st.session_state.get("user_client_id") or MASTER_CLIENT_ID
        active_sec = saved_keys.get("client_secret") or st.session_state.get("user_client_secret") or MASTER_CLIENT_SECRET
        
        if not active_cid or not active_sec:
            raise ValueError("Google Client ID or Client Secret missing. Please re-enter them in the Setup panel.")
            
        client_config = {
            "web": {
                "client_id": active_cid,
                "client_secret": active_sec,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
            redirect_uri=APP_URL
        )
        
        if state_param:
            verifier = get_verifier(str(state_param))
            if verifier:
                flow.code_verifier = verifier
                
        if not hasattr(flow, 'code_verifier') or not flow.code_verifier:
            if os.path.exists(".verifier"):
                with open(".verifier", "r", encoding="utf-8") as f:
                    flow.code_verifier = f.read().strip()
                
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        creds_dict = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes
        }
        
        st.session_state["youtube_creds"] = creds_dict
        st.session_state["force_fetch"] = True
        
        with open(TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(creds_dict, f)
        
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.error(f"Connection failed: {e}")

# --- Core App Structure ---
if st.session_state.get("youtube_creds") is not None:
    
    youtube = None
    live_comments = []

    try:
        from google.oauth2.credentials import Credentials
        creds = Credentials(**st.session_state["youtube_creds"])
        youtube = build("youtube", "v3", credentials=creds)
        
        if st.session_state["channel_id"] is None:
            channel_response = youtube.channels().list(part="id,snippet", mine=True).execute()
            if channel_response.get("items"):
                st.session_state["channel_logo"] = channel_response["items"][0]["snippet"]["thumbnails"]["default"]["url"]
                st.session_state["channel_name"] = channel_response["items"][0]["snippet"]["title"]
                st.session_state["channel_id"] = channel_response["items"][0]["id"]
        
        channel_id = st.session_state["channel_id"]
        channel_name = st.session_state["channel_name"]
        channel_logo = st.session_state["channel_logo"]
        
        if channel_id:
            if not st.session_state.get("channel_comments") or st.session_state.get("force_fetch"):
                with st.spinner("Fetching latest channel activity..."):
                    fetched_comments = []
                    next_token = None
                    
                    for _ in range(5):
                        try:
                            req = youtube.commentThreads().list(
                                part="snippet,replies",
                                allThreadsRelatedToChannelId=channel_id,
                                maxResults=100,
                                order="time",
                                textFormat="plainText",
                                pageToken=next_token
                            ).execute()
                            fetched_comments.extend(req.get("items", []))
                            next_token = req.get("nextPageToken")
                            if not next_token:
                                break
                        except Exception:
                            break
                            
                    st.session_state["channel_comments"] = fetched_comments
                    st.session_state["force_fetch"] = False
                    
                    missing_vids = []
                    for item in fetched_comments:
                        vid = item["snippet"]["topLevelComment"]["snippet"].get("videoId", "")
                        if vid and vid not in st.session_state["video_title_cache"]:
                            missing_vids.append(vid)
                    
                    if missing_vids:
                        unique_vids = list(set(missing_vids))[:50]
                        try:
                            vid_response = youtube.videos().list(
                                part="snippet",
                                id=",".join(unique_vids)
                            ).execute()
                            for v_item in vid_response.get("items", []):
                                st.session_state["video_title_cache"][v_item["id"]] = v_item["snippet"]["title"]
                                st.session_state["video_desc_cache"][v_item["id"]] = v_item["snippet"].get("description", "")
                        except Exception:
                            pass
            
            live_comments = st.session_state["channel_comments"]
            
            for item in live_comments:
                cid = item["id"]
                top_comment_snippet = item["snippet"]["topLevelComment"]["snippet"]
                author_id = top_comment_snippet.get("authorChannelId", {}).get("value", "")
                
                owner_replied = False
                
                if author_id == channel_id:
                    owner_replied = True
                elif item["snippet"].get("totalReplyCount", 0) > 0:
                    if "replies" in item:
                        for reply in item["replies"].get("comments", []):
                            reply_author = reply["snippet"].get("authorChannelId", {}).get("value", "")
                            if reply_author == channel_id:
                                owner_replied = True
                                break
                
                if owner_replied:
                    st.session_state["replied_comments"].add(cid)
                    if cid not in st.session_state["sent_replies_log"]:
                        st.session_state["sent_replies_log"][cid] = "Previously replied on YouTube."
                        if cid not in st.session_state["processed_history"]:
                            st.session_state["processed_history"].append(cid)
                        
    except Exception as e:
        channel_id = st.session_state.get("channel_id")
        channel_name = st.session_state.get("channel_name", "YouTube Account")
        channel_logo = st.session_state.get("channel_logo", "")
        live_comments = st.session_state.get("channel_comments", [])

    total_fetched = len(live_comments)
    handled_set = st.session_state.get("replied_comments", set())
    pending_comments = [c for c in live_comments if c["id"] not in handled_set]
    pending_count = len(pending_comments)
    handled_count = len(handled_set)

    handled_pct = int((handled_count / total_fetched) * 100) if total_fetched > 0 else 0
    pending_pct = int((pending_count / total_fetched) * 100) if total_fetched > 0 else 0

    def pause_auto_reply():
        st.session_state["auto_reply_paused"] = True

    def resume_auto_reply():
        st.session_state["auto_reply_paused"] = False
        st.session_state.pop("queue_warning", None)

    def force_refresh_comments():
        st.session_state["force_fetch"] = True
        st.session_state.pop("channel_comments", None)
        st.session_state["session_visible_handled"] = set()

    # --- Sidebar ---
    with st.sidebar:
        st.title("YouTube")
        st.markdown(f"""
