import streamlit as st
import os
from dotenv import load_dotenv
from google import genai
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import time
from datetime import datetime, timezone
import streamlit.components.v1 as components

# --- Open the secure vault ---
load_dotenv()
MASTER_API_KEY = os.getenv("GEMINI_API_KEY")
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

# Dynamic Routing. It will use your live URL if available, otherwise defaults to local testing.
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8501") 

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# --- Page Config ---
st.set_page_config(
    layout="wide", 
    page_title="Cruise Comment", 
    page_icon="ChatGPT Image Aug 26, 2026, 11_48_10 PM.png",
    initial_sidebar_state="expanded"
)

# --- Persistent Context Storage ---
CONTEXT_FILE = ".cruise_context"
loaded_context = ""
if os.path.exists(CONTEXT_FILE):
    with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
        loaded_context = f.read().strip()

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
    "autopilot_interval": 5
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

def get_relative_time(dt):
    """Calculates human-readable relative time (e.g. '5 minutes ago')."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{seconds} seconds ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"

# --- Strict Apple-Inspired Monochromatic Design System ---
st.markdown("""
    <style>
        /* Typography & Core Variables */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
        
        .stApp { 
            background-color: #FBFBFD !important; 
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif !important;
            color: #111111 !important;
        }

        /* Subtle Entrance Animation */
        @keyframes fadeSlideUp {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        /* SCROLL FIX */
        .stAppViewContainer, .stMain, .stAppViewBlockContainer {
            overflow: auto !important;
        }
        .block-container, [data-testid="stVerticalBlock"] {
            overflow: visible !important;
            clip-path: none !important;
        }
        
        [data-testid="block-container"] {
            animation: fadeSlideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards;
            padding-top: 2rem !important; 
            padding-bottom: 2rem !important;
            max-width: 1040px !important;
        }

        header[data-testid="stHeader"] { display: none; }
        
        /* FULL COVERAGE STICKY HEADER FIX */
        div[data-testid="stVerticalBlock"] > div:has(.sticky-anchor-container) {
            position: -webkit-sticky !important;
            position: sticky !important;
            top: 0px !important; 
            z-index: 999999 !important;
            background-color: #FBFBFD !important; 
            padding: 2.5rem 1rem 1rem 1rem !important; 
            margin: -2.5rem -1rem 1.5rem -1rem !important; 
            border-bottom: 1px solid #EAEAEA !important;
            box-shadow: 0 8px 12px -10px rgba(0,0,0,0.05); 
            width: calc(100% + 4rem) !important;
        }

        /* System Header */
        .system-header {
            margin-bottom: 12px;
            text-align: center;
        }
        .main-title {
            font-size: 36px;
            font-weight: 600;
            color: #111111;
            margin: 0 0 4px 0;
            letter-spacing: -0.04em;
            line-height: 1.1;
        }
        .sub-title {
            font-size: 15px;
            color: #555555;
            margin: 0;
            font-weight: 400;
            letter-spacing: -0.01em;
        }

        /* HORIZONTAL METRICS BANNER */
        .metrics-banner {
            background-color: #3A3A3C;
            border-radius: 12px;
            padding: 12px;
            display: flex;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 32px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        .metric-box {
            background-color: #FFFFFF;
            border-radius: 8px;
            padding: 12px 20px;
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        .metric-label {
            font-size: 13px;
            color: #555555;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .metric-value {
            font-size: 20px;
            font-weight: 600;
            color: #111111;
        }

        /* 7-IMAGE OVERLAPPING HERO GALLERY FIX */
        .hero-gallery {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            justify-content: center !important;
            align-items: center !important;
            margin: 24px auto 48px auto !important; 
            width: 100% !important;
            min-height: 300px !important;
        }
        .hero-item {
            position: relative !important;
            flex: 0 0 auto !important;
            border-radius: 18px !important; 
            overflow: hidden !important;
            box-shadow: 0 8px 24px rgba(0,0,0,0.08) !important;
            transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
            background: #FFFFFF !important;
            filter: brightness(1.02) contrast(1.02) !important; 
            margin: 0 -12px !important; 
            border: 3px solid #FBFBFD !important; 
        }
        .hero-item:hover {
            transform: translateY(-8px) scale(1.03) !important;
            box-shadow: 0 16px 40px rgba(0,0,0,0.15) !important;
            filter: brightness(1.08) contrast(1.05) !important;
            z-index: 20 !important; 
        }
        .hero-item img {
            display: block !important;
            object-fit: cover !important;
            width: 100% !important;
            height: 100% !important;
        }
        
        .hero-main  { width: 240px !important; height: 280px !important; z-index: 4 !important; }
        .hero-side  { width: 190px !important; height: 230px !important; z-index: 3 !important; }
        .hero-far   { width: 140px !important; height: 180px !important; z-index: 2 !important; }
        .hero-outer { width: 100px !important; height: 130px !important; z-index: 1 !important; }

        .hero-outer.left { top: 24px !important; }
        .hero-far.left   { top: -16px !important; }
        .hero-side.left  { top: 12px !important; }
        .hero-main       { top: 0px !important; }
        .hero-side.right { top: -12px !important; }
        .hero-far.right  { top: 16px !important; }
        .hero-outer.right{ top: -24px !important; }

        /* PERFECT SYMMETRICAL FLEX GRID FOR PRICING TIERS */
        [data-testid="column"]:has(.pricing-card-marker) { display: flex; flex-direction: column; }
        [data-testid="column"]:has(.pricing-card-marker) > div { flex: 1; display: flex; flex-direction: column; }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.pricing-card-marker) {
            flex: 1; display: flex; flex-direction: column; padding: 24px !important; 
            background-color: #FFFFFF !important; border-radius: 8px !important;
            border: 1px solid #E5E5EA !important; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.01) !important;
            margin-bottom: 0 !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.pricing-card-marker) > div[data-testid="stVerticalBlock"] {
            flex: 1; display: flex; flex-direction: column;
        }
        div.element-container:has(.pricing-bottom-zone) { margin-top: auto !important; width: 100%; }
        .bottom-action-group {
            display: flex; flex-direction: column; gap: 8px; min-height: 90px; justify-content: flex-start; 
        }

        /* Pricing Internal Formatting */
        .section-title { font-size: 18px; font-weight: 600; color: #111111; margin-bottom: 16px; letter-spacing: -0.01em; }
        .tier-feature { font-size: 13px; color: #555555; margin-bottom: 8px; display: flex; align-items: flex-start; gap: 6px; line-height: 1.3; }
        .tier-feature span { color: #111111; font-weight: 600; }
        .beta-tag { font-size: 10px; background-color: #E5E5EA; color: #555; padding: 2px 6px; border-radius: 8px; margin-left: 4px; vertical-align: middle; }

        /* Collapsible API Guide */
        details.api-guide {
            background-color: #F8F8FA;
            border: 1px solid #E5E5EA;
            border-radius: 6px;
            padding: 8px 12px;
            margin-bottom: 12px;
            font-size: 12px;
        }
        details.api-guide summary {
            font-weight: 500;
            color: #333333;
            cursor: pointer;
            outline: none;
        }
        details.api-guide ol {
            margin: 8px 0 4px 16px;
            padding: 0;
            color: #555555;
            line-height: 1.4;
        }

        /* Clean Connected Cards */
        [data-testid="stVerticalBlockBorderWrapper"]:not(:has(.pricing-card-marker)) {
            background-color: #FFFFFF !important;
            border-radius: 8px !important; border: 1px solid #E5E5EA !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.01) !important; padding: 16px !important; margin-bottom: 12px !important;
        }
        
        [data-testid="stVerticalBlockBorderWrapper"]:not(:has(.pricing-card-marker)) [data-testid="stVerticalBlockBorderWrapper"] {
            padding: 12px !important; background-color: #FBFBFD !important;
            border: 1px solid #EAEAEA !important; box-shadow: none !important;
            border-radius: 6px !important; margin-top: 8px !important; margin-bottom: 0 !important;
        }

        /* Handled/Success State Card */
        .handled-card {
            background-color: #F2FDF5 !important;
            border: 1px solid #34C759 !important;
            border-radius: 8px !important;
            padding: 16px !important;
            margin-bottom: 16px !important;
            box-shadow: 0 2px 8px rgba(52, 199, 89, 0.08) !important;
        }
        .handled-badge {
            font-size: 12px;
            font-weight: 600;
            color: #248A3D;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        /* Input Clean-up - Forced Light Mode for Inputs */
        [data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {
            background-color: #F5F5F7 !important; border: 1px solid #D1D1D6 !important; border-radius: 6px !important;
            box-shadow: none !important; transition: border-color 0.15s ease; height: 38px !important; 
        }
        [data-baseweb="textarea"] > div { height: auto !important; }
        [data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within { border-color: #007AFF !important; box-shadow: 0 0 0 1px #007AFF !important; }
        [data-baseweb="input"] input, [data-baseweb="textarea"] textarea { background-color: transparent !important; color: #111111 !important; -webkit-text-fill-color: #111111 !important; font-size: 13px !important; padding: 8px 12px !important; line-height: 1.4 !important; }
        [data-baseweb="input"] input::placeholder, [data-baseweb="textarea"] textarea::placeholder { color: #888888 !important; -webkit-text-fill-color: #888888 !important; }
        
        /* TOGGLE SWITCH (RED/GREEN) */
        div[data-testid="stToggle"] input + div { background-color: #FF3B30 !important; } 
        div[data-testid="stToggle"] input:checked + div { background-color: #34C759 !important; } 

        /* ALL Native Buttons */
        .stButton > button, [data-testid="baseButton-primary"] {
            background-color: #3A3A3C !important; color: #FFFFFF !important; border: 1px solid #3A3A3C !important;
            border-radius: 6px !important; font-weight: 500 !important; font-size: 13px !important; padding: 6px 12px !important;
            transition: all 0.15s ease !important; min-height: 38px !important; filter: grayscale(100%) contrast(1.2); width: 100% !important;
        }
        .stButton > button:hover, [data-testid="baseButton-primary"]:hover { background-color: #2C2C2E !important; border-color: #2C2C2E !important; }
        
        /* STOP/RESUME BUTTON OVERRIDES */
        .stop-btn-wrapper .stButton > button { background-color: #FF3B30 !important; border-color: #FF3B30 !important; color: #FFFFFF !important; filter: none !important; font-size: 14px !important; font-weight: 600 !important; }
        .stop-btn-wrapper .stButton > button:hover { background-color: #D70015 !important; border-color: #D70015 !important; }
        
        .resume-btn-wrapper .stButton > button { background-color: #34C759 !important; border-color: #34C759 !important; color: #FFFFFF !important; filter: none !important; font-size: 14px !important; font-weight: 600 !important; }
        .resume-btn-wrapper .stButton > button:hover { background-color: #248A3D !important; border-color: #248A3D !important; }
        
        .completed-btn-wrapper .stButton > button { background-color: #F0F0F2 !important; border-color: #E5E5EA !important; color: #888888 !important; pointer-events: none; filter: none !important; font-size: 14px !important; font-weight: 600 !important; }

        /* Clickable Grey Video Title Box */
        button[title="Filter_Video_Btn"] {
            background-color: #F0F0F2 !important;
            color: #555555 !important;
            border: 1px solid #EAEAEA !important;
            border-radius: 6px !important;
            font-size: 11px !important;
            font-weight: 600 !important;
            padding: 4px 10px !important;
            min-height: 26px !important;
            width: auto !important;
            display: inline-flex !important;
            align-items: center;
            text-transform: uppercase !important;
            letter-spacing: 0.04em !important;
            margin-bottom: 6px !important;
            box-shadow: 0 1px 2px rgba(0,0,0,0.02) !important;
            transition: all 0.15s ease !important;
            text-align: left !important;
        }
        button[title="Filter_Video_Btn"]:hover {
            background-color: #E5E5EA !important;
            color: #111111 !important;
            border-color: #D1D1D6 !important;
            transform: translateY(-1px);
            box-shadow: 0 2px 4px rgba(0,0,0,0.05) !important;
        }
        button[title="Filter_Video_Btn"] p {
            font-size: 11px !important;
            font-weight: 600 !important;
            color: inherit !important;
            margin: 0 !important;
        }

        [data-testid="stSidebar"] .stButton > button { filter: none !important; }
        [data-testid="stSidebar"] .stButton > button p::before { content: "● "; color: #FF3B30; font-size: 14px; }
        
        /* Anchor Action Links for Tiers */
        .auth-btn { display: inline-block; background-color: #3A3A3C !important; color: #FFFFFF !important; border-radius: 6px !important; font-weight: 500 !important; font-size: 13px !important; text-align: center !important; width: 100% !important; padding: 10px 12px !important; text-decoration: none !important; box-sizing: border-box; filter: none !important; height: 38px; line-height: 18px; }
        .auth-btn:hover { background-color: #2C2C2E !important; color: #FFFFFF !important; }
        .disabled-btn { background-color: #F0F0F2 !important; color: #888888 !important; border: 1px solid #E5E5EA !important; pointer-events: none !important; }

        /* Green Active Pulse Indicator */
        @keyframes subtlePulse { 0% { opacity: 0.3; transform: scale(0.95); } 50% { opacity: 1; transform: scale(1); } 100% { opacity: 0.3; transform: scale(0.95); } }
        .status-dot { height: 6px; width: 6px; background-color: #34C759 !important; border-radius: 50%; display: inline-block; margin-right: 8px; animation: subtlePulse 2.5s infinite ease-in-out; vertical-align: middle; }
        .status-badge { display: inline-flex; align-items: center; font-size: 13px; color: #111111; background: #F0F0F2; padding: 4px 10px; border-radius: 6px; font-weight: 500; margin-top: 12px; }

        /* Sidebar Control Center */
        [data-testid="stSidebar"] { background-color: #F5F5F7 !important; border-right: 1px solid #E5E5EA !important; padding-top: 32px; }
        .sb-section { margin-bottom: 32px; padding: 0 12px; }
        .sb-header { font-size: 11px; font-weight: 600; color: #888888; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 12px; }
        .sb-account-card { background: #FFFFFF; border: 1px solid #E5E5EA; border-radius: 8px; padding: 10px; display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
        .sb-account-card img { width: 28px; height: 28px; border-radius: 50%; border: 1px solid #E5E5EA; }
        .sb-account-name { font-size: 13px; font-weight: 600; color: #111111; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .sb-account-meta { font-size: 11px; color: #888888; }
        .sb-item { font-size: 13px; color: #555555; padding: 5px 0; display: flex; justify-content: space-between; align-items: center; }
        .sb-item-val { font-weight: 500; color: #111111; }
        .sb-divider { height: 1px; background-color: #E5E5EA; margin: 24px 12px; }

        /* Comments Hierarchy */
        .comment-header { margin-bottom: 8px; display: flex; align-items: baseline; gap: 8px; }
        .comment-author { font-size: 14px; font-weight: 600; color: #111111; }
        .comment-date { font-size: 12px; color: #888888; }
        .comment-relative { font-size: 12px; color: #888888; font-weight: 400; }
        .comment-text { font-size: 15px; color: #111111; line-height: 1.5; margin-bottom: 16px; }
        .video-thumbnail-container { border-radius: 6px; overflow: hidden; border: 1px solid #EAEAEA; margin-bottom: 16px; }
        .video-thumbnail-container img { width: 100%; display: block; object-fit: cover; }
        
        .empty-state { padding: 64px 20px; text-align: center; background: #FFFFFF; border: 1px solid #E5E5EA; border-radius: 8px; }
        .empty-title { font-size: 16px; font-weight: 500; color: #111; margin-bottom: 4px; }
        .empty-sub { font-size: 14px; color: #666; }
    </style>
""", unsafe_allow_html=True)

# --- Handle OAuth Callback ---
query_params = st.query_params
if "code" in query_params and st.session_state.get("youtube_creds") is None:
    code = query_params["code"]
    try:
        client_config = {
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
            redirect_uri=REDIRECT_URI
        )
        if os.path.exists(".verifier"):
            with open(".verifier", "r") as f:
                flow.code_verifier = f.read().strip()
        elif st.session_state.get("saved_code_verifier") is not None:
            flow.code_verifier = st.session_state["saved_code_verifier"]
            
        flow.fetch_token(code=code)
        credentials = flow.credentials
        st.session_state["youtube_creds"] = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes
        }
        if os.path.exists(".verifier"):
            os.remove(".verifier")
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
            is_replying = bool(st.session_state.get("auto_reply_queue"))
            
            if is_replying and "cached_live_comments" in st.session_state:
                live_comments = st.session_state["cached_live_comments"]
            else:
                channel_req = youtube.commentThreads().list(
                    part="snippet",
                    allThreadsRelatedToChannelId=channel_id,
                    maxResults=100, 
                    textFormat="plainText"
                ).execute()
                st.session_state["channel_comments"] = channel_req.get("items", [])
                
                target_vid = None
                selected_filter_title = st.session_state.get("selected_video_filter", "All Videos")
                
                if "  [" in selected_filter_title:
                    clean_filter_title = selected_filter_title.split("  [")[0].strip()
                else:
                    clean_filter_title = selected_filter_title

                if clean_filter_title != "All Videos":
                    for full_title, vid_id in st.session_state.get("video_mapping_cache", {}).items():
                        if clean_filter_title in full_title or full_title.startswith(clean_filter_title):
                            target_vid = vid_id
                            break
                    
                if target_vid:
                    vid_req = youtube.commentThreads().list(
                        part="snippet",
                        videoId=target_vid,
                        maxResults=100, 
                        textFormat="plainText"
                    ).execute()
                    live_comments = vid_req.get("items", [])
                else:
                    live_comments = st.session_state["channel_comments"]
                
                missing_vids = []
                for item in st.session_state["channel_comments"] + live_comments:
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
                
                st.session_state["cached_live_comments"] = live_comments
                st.session_state["master_comments_cache"] = live_comments
            
            for item in live_comments:
                cid = item["id"]
                if item["snippet"].get("totalReplyCount", 0) > 0:
                    st.session_state["replied_comments"].add(cid)
                    if cid not in st.session_state["sent_replies_log"]:
                        st.session_state["sent_replies_log"][cid] = "Previously replied on YouTube."
                        if cid not in st.session_state["processed_history"]:
                            st.session_state["processed_history"].append(cid)
                        
    except Exception as e:
        channel_id = st.session_state.get("channel_id")
        channel_name = st.session_state.get("channel_name", "YouTube Account")
        channel_logo = st.session_state.get("channel_logo", "")
        
        if st.session_state.get("master_comments_cache"):
            live_comments = st.session_state["master_comments_cache"]
        elif st.session_state.get("channel_comments"):
            target_vid = None
            selected_filter_title = st.session_state.get("selected_video_filter", "All Videos")
            
            if "  [" in selected_filter_title:
                clean_filter_title = selected_filter_title.split("  [")[0].strip()
            else:
                clean_filter_title = selected_filter_title

            if clean_filter_title != "All Videos":
                for full_title, vid_id in st.session_state.get("video_mapping_cache", {}).items():
                    if clean_filter_title in full_title or full_title.startswith(clean_filter_title):
                        target_vid = vid_id
                        break
                
            if target_vid:
                live_comments = [c for c in st.session_state["channel_comments"] if c["snippet"]["topLevelComment"]["snippet"].get("videoId") == target_vid]
            else:
                live_comments = st.session_state["channel_comments"]
        else:
            live_comments = []

    total_fetched = len(live_comments)
    handled_set = st.session_state.get("replied_comments", set())
    pending_comments = [c for c in live_comments if c["id"] not in handled_set]
    pending_count = len(pending_comments)
    handled_count = len(handled_set)

    # OPTIONS
    mood_options = ["Friendly", "Professional", "Funny", "Sassy"]
    length_options = ["Small", "Medium", "Long"]
    sort_options = ["Newest to Oldest", "Oldest to Newest", "Video Name (A-Z)"]
    view_options = ["All Comments", "Unresponded", "Handled"]
    limit_options = ["5", "10", "20", "50", "100", "All"]

    handled_pct = int((handled_count / total_fetched) * 100) if total_fetched > 0 else 0
    pending_pct = int((pending_count / total_fetched) * 100) if total_fetched > 0 else 0

    # --- Sidebar ---
    with st.sidebar:
        st.markdown("<div class='sb-section'>", unsafe_allow_html=True)
        st.markdown("<div class='sb-header'>YOUTUBE</div>", unsafe_allow_html=True)
        fallback_img = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23CCC' d='M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z'/%3E%3C/svg%3E"
        st.markdown(f"""
            <div class="sb-account-card">
                <img src="{channel_logo if channel_logo else fallback_img}" alt="Profile">
                <div class="sb-account-details">
                    <div class="sb-account-name">{channel_name}</div>
                    <div class="sb-account-meta">Connected</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("Disconnect", use_container_width=True):
            st.session_state["youtube_creds"] = None
            st.rerun()
        st.markdown("</div><div class='sb-divider'></div>", unsafe_allow_html=True)
        
        st.markdown("<div class='sb-section'>", unsafe_allow_html=True)
        st.markdown("<div class='sb-header'>INSTAGRAM</div>", unsafe_allow_html=True)
        st.markdown(f'<a href="#" target="_top" class="auth-btn disabled-btn"><span style="color: #888888; margin-right: 6px; font-size: 16px;">●</span>Connect Instagram <span class="beta-tag">BETA</span></a>', unsafe_allow_html=True)
        st.markdown("</div><div class='sb-divider'></div>", unsafe_allow_html=True)

        st.markdown("<div class='sb-section'>", unsafe_allow_html=True)
        st.markdown("<div class='sb-header'>CRUISE AUTOPILOT ✈️</div>", unsafe_allow_html=True)
        st.markdown("""
            <div style='font-size:12px; color:#555; margin-bottom:12px; line-height:1.4;'>
                Run Cruise in the background to automatically scan for and reply to new comments.
            </div>
        """, unsafe_allow_html=True)
        
        autopilot_on = st.toggle("Enable Autopilot", value=st.session_state.get("autopilot_active", False), key="autopilot_toggle")
        
        if autopilot_on:
            autopilot_interval = st.number_input("Scan Interval (Minutes)", min_value=1, max_value=1440, value=st.session_state.get("autopilot_interval", 5), key="autopilot_interval_input", help="How often should Cruise check YouTube for new comments?")
            st.session_state["autopilot_interval"] = autopilot_interval
            
        if autopilot_on != st.session_state.get("autopilot_active", False):
            st.session_state["autopilot_active"] = autopilot_on
            if autopilot_on:
                st.session_state["autopilot_next_run"] = time.time() 
            else:
                st.session_state.pop("autopilot_next_run", None)
                st.session_state.pop("autopilot_force_fetch", None)
            st.rerun()
            
        st.markdown("</div><div class='sb-divider'></div>", unsafe_allow_html=True)

        st.markdown("<div class='sb-section'>", unsafe_allow_html=True)
        st.markdown("<div class='sb-header'>TODAY</div>", unsafe_allow_html=True)
        st.markdown(f"""
            <div class="sb-item">Comments <span class="sb-item-val">{total_fetched}</span></div>
            <div class="sb-item">Replies sent <span class="sb-item-val">{handled_count}</span></div>
            <div class="sb-item">Need attention <span class="sb-item-val" style="color:{'#111' if pending_count > 0 else '#888'};">{pending_count}</span></div>
        """, unsafe_allow_html=True)
        st.markdown("</div><div class='sb-divider'></div>", unsafe_allow_html=True)

        st.markdown("<div class='sb-section'>", unsafe_allow_html=True)
        st.markdown("<div class='sb-header'>SETUP</div>", unsafe_allow_html=True)
        has_context = bool(st.session_state.get("saved_channel_context"))
        st.markdown(f"""
            <div class="sb-item">YouTube connected <span class="sb-item-val">✓</span></div>
            <div class="sb-item">Reply style saved <span class="sb-item-val" style="color:{'#111' if has_context else '#CCC'};">{'✓' if has_context else '○'}</span></div>
        """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    def set_video_filter(target_option):
        st.session_state["selected_video_filter"] = target_option

    def pause_auto_reply():
        st.session_state["auto_reply_paused"] = True

    def resume_auto_reply():
        st.session_state["auto_reply_paused"] = False

    # --- Dashboard View ---
    if channel_id is not None:
        
        st.markdown("""
        <div class="system-header" style="text-align: left;">
            <h1 class="main-title">Cruise Comment</h1>
            <p class="sub-title">Your audience engagement, on cruise control.</p>
            <div class="status-badge"><span class="status-dot"></span> Cruise is active</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"""
        <div class="metrics-banner">
            <div class="metric-box">
                <span class="metric-label">Recent comments:</span>
                <span class="metric-value">{total_fetched}</span>
            </div>
            <div class="metric-box">
                <span class="metric-label">Replies handled:</span>
                <span class="metric-value">{handled_count} <span style="font-size:14px; color:#888; font-weight:500;">({handled_pct}%)</span></span>
            </div>
            <div class="metric-box">
                <span class="metric-label">Need attention:</span>
                <span class="metric-value">{pending_count} <span style="font-size:14px; color:#888; font-weight:500;">({pending_pct}%)</span></span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="section-title">Reply Style</div>', unsafe_allow_html=True)
        
        with st.container(border=True):
            if not st.session_state.get("context_locked"):
                current_niche_input = st.text_area(
                    "Instructions", 
                    value=st.session_state.get("saved_channel_context", ""),
                    placeholder="e.g., We review mid-range motorcycles. Be objective but friendly. End with a question.",
                    height=60,
                    label_visibility="collapsed"
                )
                col1, col2 = st.columns([5, 1])
                with col2:
                    if st.button("💾 Save", use_container_width=True):
                        st.session_state["saved_channel_context"] = current_niche_input
                        st.session_state["context_locked"] = True
                        with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
                            f.write(current_niche_input.strip())
                        st.rerun()
            else:
                col1, col2 = st.columns([5, 1], gap="medium")
                with col1:
                    display_text = st.session_state.get('saved_channel_context', '')
                    if not display_text: display_text = "No custom style provided."
                    st.markdown(f"<div style='font-size:14px; color:#111; padding: 6px 0; line-height: 1.5;'>{display_text}</div>", unsafe_allow_html=True)
                with col2:
                    if st.button("✎ Edit", use_container_width=True):
                        st.session_state["context_locked"] = False
                        st.rerun()

        # SMART VIDEO SORTING & DYNAMIC COUNTERS
        all_comments_for_dropdown = st.session_state.get("channel_comments", [])
        unique_video_ids = list(set([c["snippet"]["topLevelComment"]["snippet"].get("videoId", "") for c in all_comments_for_dropdown if c["snippet"]["topLevelComment"]["snippet"].get("videoId")]))
        
        video_unresponded_counts = {}
        video_mapping = {}

        for vid in unique_video_ids:
            pending_for_vid = [
                c for c in all_comments_for_dropdown 
                if c["snippet"]["topLevelComment"]["snippet"].get("videoId") == vid and c["id"] not in handled_set
            ]
            video_unresponded_counts[vid] = len(pending_for_vid)

        sorted_vids = sorted(unique_video_ids, key=lambda v: video_unresponded_counts[v], reverse=True)
        
        total_pending_all = len([c for c in all_comments_for_dropdown if c["id"] not in handled_set])
        all_videos_label = f"All Videos  [{total_pending_all} pending]"

        video_options = [all_videos_label]
        video_mapping[all_videos_label] = None

        for vid in sorted_vids:
            base_title = st.session_state["video_title_cache"].get(vid, f"Video {vid}")
            count = video_unresponded_counts[vid]
            
            if len(base_title) > 22:
                short_title = base_title[:19].strip() + "..."
            else:
                short_title = base_title
                
            display_title = f"{short_title}  [{count} pending]"
            
            if display_title in video_mapping:
                display_title = f"{short_title} (2)  [{count} pending]"
                
            video_options.append(display_title)
            video_mapping[display_title] = vid

        st.session_state["video_mapping_cache"] = video_mapping

        current_selection = st.session_state.get("selected_video_filter", all_videos_label)
        if current_selection not in video_options:
            matched = False
            if "  [" in current_selection:
                base_curr = current_selection.rsplit("  [", 1)[0]
                for opt in video_options:
                    if opt.startswith(base_curr + "  ["):
                        current_selection = opt
                        matched = True
                        break
            if not matched:
                current_selection = all_videos_label
                
        st.session_state["selected_video_filter"] = current_selection

        with st.container():
            st.markdown('<div class="sticky-anchor-container"></div>', unsafe_allow_html=True)
            
            col_t, col_v, col_f, col_s, col_m, col_len, col_mod, col_l, col_b = st.columns([1.5, 1.4, 1.0, 1.0, 1.0, 1.1, 1.4, 0.7, 1.6], vertical_alignment="bottom")
            
            with col_t:
                header_text = current_selection
                if header_text.startswith("All Videos"):
                    header_text = f"All Comments  [{total_pending_all} pending]"
                st.markdown(f'<div class="section-title" style="filter: grayscale(100%); margin-bottom: 0; font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{header_text}">💬 {header_text}</div>', unsafe_allow_html=True)
            
            with col_v:
                st.markdown("<div style='font-size:11px; font-weight:600; color:#888; text-transform:uppercase; margin-bottom:4px; letter-spacing:0.04em;'>Video</div>", unsafe_allow_html=True)
                selected_video_title = st.selectbox("Video", video_options, index=video_options.index(current_selection), key="dropdown_video_filter", label_visibility="collapsed")
                st.session_state["selected_video_filter"] = selected_video_title
                
            with col_f:
                st.markdown("<div style='font-size:11px; font-weight:600; color:#888; text-transform:uppercase; margin-bottom:4px; letter-spacing:0.04em;'>View</div>", unsafe_allow_html=True)
                filter_view = st.selectbox("View", view_options, index=view_options.index("All Comments"), label_visibility="collapsed")
            with col_s:
                st.markdown("<div style='font-size:11px; font-weight:600; color:#888; text-transform:uppercase; margin-bottom:4px; letter-spacing:0.04em;'>Sort By</div>", unsafe_allow_html=True)
                sort_order = st.selectbox("Sort", sort_options, index=sort_options.index("Newest to Oldest"), label_visibility="collapsed")
            with col_m:
                st.markdown("<div style='font-size:11px; font-weight:600; color:#888; text-transform:uppercase; margin-bottom:4px; letter-spacing:0.04em;'>Reply Mood</div>", unsafe_allow_html=True)
                global_mood = st.selectbox("Mood", mood_options, index=mood_options.index(st.session_state["global_mood"]), key="global_mood_select", label_visibility="collapsed")
                st.session_state["global_mood"] = global_mood
            with col_len:
                st.markdown("<div style='font-size:11px; font-weight:600; color:#888; text-transform:uppercase; margin-bottom:4px; letter-spacing:0.04em;'>Comment Length</div>", unsafe_allow_html=True)
                global_length = st.selectbox("Comment Length", length_options, index=length_options.index(st.session_state["global_length"]), key="global_length_select", label_visibility="collapsed")
                st.session_state["global_length"] = global_length
            
            with col_mod:
                st.markdown("""
                    <div style='font-size:11px; font-weight:600; color:#888; text-transform:uppercase; margin-bottom:4px; letter-spacing:0.04em; display:flex; align-items:center; gap:4px;'>
                        Enhanced Reply
                        <div title="Context-based comment reply: Analyzes up to 100 surrounding comments for situational awareness, inside jokes, and vibe checks (Uses more Gemini tokens)." style="cursor:help; background:#EAEAEA; color:#555; border-radius:50%; width:14px; height:14px; display:inline-flex; align-items:center; justify-content:center; font-size:10px; font-weight:bold; font-family:monospace;">i</div>
                    </div>
                """, unsafe_allow_html=True)
                is_enhanced = st.toggle("Enhanced Reply", value=(st.session_state.get("global_ai_mode") == "Deep Context"), label_visibility="collapsed", key="enhanced_reply_toggle")
                st.session_state["global_ai_mode"] = "Deep Context" if is_enhanced else "Standard"

            with col_l:
                st.markdown("<div style='font-size:11px; font-weight:600; color:#888; text-transform:uppercase; margin-bottom:4px; letter-spacing:0.04em;'>Limit</div>", unsafe_allow_html=True)
                reply_limit_str = st.selectbox("Limit", limit_options, index=limit_options.index("All"), label_visibility="collapsed")

            display_comments = live_comments
            
            active_filter = st.session_state["selected_video_filter"]
            target_vid = video_mapping.get(active_filter)

            if target_vid is not None:
                display_comments = [c for c in display_comments if c["snippet"]["topLevelComment"]["snippet"].get("videoId") == target_vid]

            if filter_view == "Unresponded":
                display_comments = [c for c in display_comments if c["id"] not in handled_set]
            elif filter_view == "Handled":
                display_comments = [c for c in display_comments if c["id"] in handled_set]

            if sort_order == "Newest to Oldest":
                display_comments = sorted(display_comments, key=lambda x: x["snippet"]["topLevelComment"]["snippet"]["publishedAt"], reverse=True)
            elif sort_order == "Oldest to Newest":
                display_comments = sorted(display_comments, key=lambda x: x["snippet"]["topLevelComment"]["snippet"]["publishedAt"], reverse=False)
            else:
                display_comments = sorted(
                    display_comments, 
                    key=lambda x: st.session_state["video_title_cache"].get(x["snippet"]["topLevelComment"]["snippet"].get("videoId", ""), "").lower()
                )

            with col_b:
                is_replying_btn = bool(st.session_state.get("auto_reply_queue"))
                btn_text = "🤖 Auto-Replying..." if is_replying_btn else "🤖 Reply All with AI"
                
                if st.button(btn_text, type="primary", disabled=is_replying_btn, use_container_width=True):
                    if MASTER_API_KEY:
                        pending_in_view = [c for c in display_comments if c["id"] not in st.session_state["replied_comments"]]
                        
                        if not pending_in_view:
                            st.toast("No pending comments in the current view to reply to!")
                        else:
                            limit = len(pending_in_view) if reply_limit_str == "All" else int(reply_limit_str)
                            st.session_state["auto_reply_queue"] = pending_in_view[:limit]
                            st.session_state["auto_reply_total"] = limit
                            st.session_state["auto_reply_success"] = 0
                            st.session_state["auto_reply_paused"] = False 
                            st.rerun() 
                    else:
                        st.error("API Key missing.")

            # ROW 2: PROGRESS DASHBOARD (Locked inside Sticky Header)
            if st.session_state.get("auto_reply_total") > 0:
                st.markdown("<hr style='margin: 16px 0; border: none; border-top: 1px solid #EAEAEA;'>", unsafe_allow_html=True)
                
                total = st.session_state["auto_reply_total"]
                left = len(st.session_state["auto_reply_queue"])
                done = total - left
                
                p_col, b_col = st.columns([7.5, 2.5], vertical_alignment="center")
                with p_col:
                    st.markdown(f"<div style='font-size: 16px; font-weight: 600; color: #111; margin-bottom: 8px;'>🚀 Cruising through comments... {done} of {total} sent.</div>", unsafe_allow_html=True)
                    st.progress(done / total if total > 0 else 0.0)
                with b_col:
                    c_stop, c_res = st.columns(2)
                    with c_stop:
                        if left > 0:
                            if not st.session_state.get("auto_reply_paused"):
                                st.markdown('<div class="stop-btn-wrapper">', unsafe_allow_html=True)
                                st.button("🛑 Stop", key="stop_q_btn", on_click=pause_auto_reply, use_container_width=True)
                                st.markdown('</div>', unsafe_allow_html=True)
                    with c_res:
                        if left > 0:
                            if st.session_state.get("auto_reply_paused"):
                                st.markdown('<div class="resume-btn-wrapper">', unsafe_allow_html=True)
                                st.button("▶ Resume", key="resume_q_btn", on_click=resume_auto_reply, use_container_width=True)
                                st.markdown('</div>', unsafe_allow_html=True)
                        else:
                            st.markdown('<div class="completed-btn-wrapper">', unsafe_allow_html=True)
                            st.button("✅ Completed", disabled=True, use_container_width=True)
                            st.markdown('</div>', unsafe_allow_html=True)

            elif st.session_state.get("autopilot_active"):
                st.markdown("<hr style='margin: 16px 0; border: none; border-top: 1px solid #EAEAEA;'>", unsafe_allow_html=True)
                next_run = st.session_state.get("autopilot_next_run", time.time())
                remaining = int(next_run - time.time())
                if remaining < 0: remaining = 0
                
                interval_sec = st.session_state.get("autopilot_interval", 5) * 60
                prog = 1.0 - (remaining / interval_sec)
                if prog < 0.0: prog = 0.0
                if prog > 1.0: prog = 1.0
                
                p_col, b_col = st.columns([7.5, 2.5], vertical_alignment="center")
                with p_col:
                    if st.session_state.get("autopilot_force_fetch"):
                        st.markdown(f"<div style='font-size: 16px; font-weight: 600; color: #111; margin-bottom: 8px;'><span class='status-dot' style='background-color: #007AFF !important; animation: subtlePulse 1.5s infinite ease-in-out;'></span>✈️ Autopilot Active: Scanning YouTube for new comments...</div>", unsafe_allow_html=True)
                        st.progress(1.0)
                    else:
                        st.markdown(f"<div style='font-size: 16px; font-weight: 600; color: #111; margin-bottom: 8px;'>✈️ Autopilot Active: Sleeping. Next scan in {remaining}s...</div>", unsafe_allow_html=True)
                        st.progress(prog)
                with b_col:
                    st.markdown('<div class="stop-btn-wrapper">', unsafe_allow_html=True)
                    if st.button("🛑 Stop Autopilot", key="stop_autopilot_btn", use_container_width=True):
                        st.session_state["autopilot_active"] = False
                        st.session_state.pop("autopilot_next_run", None)
                        st.session_state.pop("autopilot_force_fetch", None)
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)

                components.html("""
                    <script>
                        const buttons = window.parent.document.querySelectorAll('button');
                        buttons.forEach(btn => {
                            if (btn.innerText.includes('🛑 Stop')) {
                                btn.style.backgroundColor = '#FF3B30';
                                btn.style.borderColor = '#FF3B30';
                                btn.style.color = '#FFFFFF';
                            }
                            if (btn.innerText.includes('▶ Resume')) {
                                btn.style.backgroundColor = '#34C759';
                                btn.style.borderColor = '#34C759';
                                btn.style.color = '#FFFFFF';
                            }
                            if (btn.innerText.includes('✅ Completed')) {
                                btn.style.backgroundColor = '#F0F0F2';
                                btn.style.borderColor = '#E5E5EA';
                                btn.style.color = '#888888';
                            }
                        });
                        
                        const toggles = window.parent.document.querySelectorAll('div[data-testid="stToggle"] input[type="checkbox"]');
                        toggles.forEach(t => {
                            const track = t.nextElementSibling;
                            if (track) {
                                track.style.backgroundColor = t.checked ? '#34C759' : '#FF3B30';
                                t.addEventListener('change', (e) => {
                                    track.style.backgroundColor = e.target.checked ? '#34C759' : '#FF3B30';
                                });
                            }
                        });
                    </script>
                """, height=0)

        is_replying_active = bool(st.session_state.get("auto_reply_queue"))
        processing_id = None
        if is_replying_active and not st.session_state.get("auto_reply_paused"):
            processing_id = st.session_state["auto_reply_queue"][0]["id"]

        if live_comments:
            for item in display_comments:
                comment_id = item["id"]
                video_id = item["snippet"]["topLevelComment"]["snippet"].get("videoId", "")
                
                target_option = all_videos_label
                for opt, vid in video_mapping.items():
                    if vid == video_id:
                        target_option = opt
                        break
                
                comment_snippet = item["snippet"]["topLevelComment"]["snippet"]
                author = comment_snippet["authorDisplayName"]
                text = comment_snippet["textDisplay"]
                raw_date = comment_snippet["publishedAt"]
                
                parsed_date = datetime.strptime(raw_date, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                formatted_date = parsed_date.strftime("%b %d, %Y · %I:%M %p")
                relative_time = get_relative_time(parsed_date)
                
                if comment_id == processing_id:
                    st.markdown(f"""
                        <div id="processing-card-{comment_id}" style="background-color: #F8F8FA; border: 2px solid #111; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.08);">
                            <div style="font-size: 12px; font-weight: 700; color: #111; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; letter-spacing: 0.05em;">
                                <span class="status-dot" style="background-color: #FF9500 !important; animation: subtlePulse 1.5s infinite ease-in-out;"></span>
                                CRUISING... DRAFTING REPLY
                            </div>
                            <div class="comment-header">
                                <span class="comment-author">{author}</span>
                                <span class="comment-date">{formatted_date}</span>
                            </div>
                            <div class="comment-text" style="color: #444; margin-bottom: 0;">"{text}"</div>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    if st.session_state.get("last_scrolled_id") != comment_id:
                        components.html(f"""
                            <script>
                                const parent = window.parent.document;
                                const el = parent.getElementById('processing-card-{comment_id}');
                                if(el) {{
                                    el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                                }}
                            </script>
                        """, height=0, width=0)
                        st.session_state["last_scrolled_id"] = comment_id
                    continue 

                if comment_id in handled_set:
                    sent_text = st.session_state.get("sent_replies_log", {}).get(comment_id, "Previously replied on YouTube.")
                    
                    with st.container():
                        st.markdown(f"""
                            <div class="handled-card">
                                <div style="display: flex; justify-content: space-between; gap: 20px; align-items: flex-start;">
                                    <div style="flex: 1;">
                                        <div class="comment-header">
                                            <span class="comment-author">{author}</span>
                                            <span class="comment-date">{formatted_date}</span>
                                            <span class="comment-relative">({relative_time})</span>
                                        </div>
                                        <div class="comment-text" style="color: #666; margin-bottom: 12px; font-size: 15px;">"{text}"</div>
                                        <div class="handled-badge" style="margin-bottom: 8px;">
                                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                                            Handled / Sent
                                        </div>
                                        <div class="handled-reply" style="font-size: 14px; background: #FFFFFF; border: 1px solid #E5F3E9; padding: 12px; border-radius: 6px;">{sent_text}</div>
                                    </div>
                                    <div style="width: 160px; flex-shrink: 0; display: flex; flex-direction: column; gap: 8px;">
                                        <img src="https://img.youtube.com/vi/{video_id}/mqdefault.jpg" style="width: 100%; border-radius: 6px; border: 1px solid #EAEAEA; object-fit: cover;">
                                    </div>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)
                    continue
                
                with st.container(border=True):
                    st.button(
                        f"▶ Filter to this Video", 
                        key=f"vt_pending_{comment_id}", 
                        help="Filter_Video_Btn",
                        on_click=set_video_filter,
                        args=(target_option,)
                    )
                    
                    st.markdown(f"""
                        <div class="comment-header" style="margin-top: 8px;">
                            <span class="comment-author">{author}</span>
                            <span class="comment-date">{formatted_date}</span>
                            <span class="comment-relative">({relative_time})</span>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    txt_col, thumb_col = st.columns([5, 1], gap="medium")
                    with txt_col:
                        st.markdown(f'<div class="comment-text">"{text}"</div>', unsafe_allow_html=True)
                    with thumb_col:
                        if video_id:
                            st.markdown(f"""
                                <div class="video-thumbnail-container">
                                    <img src="https://img.youtube.com/vi/{video_id}/mqdefault.jpg" alt="Thumbnail">
                                </div>
                            """, unsafe_allow_html=True)
                    
                    if comment_id in st.session_state.get("ai_drafts", {}):
                        with st.container(border=True):
                            st.markdown("<div style='font-size:11px; font-weight:600; color:#555; text-transform:uppercase; margin-bottom:8px; letter-spacing:0.04em; filter: grayscale(100%);'>🤖 AI Draft Verification</div>", unsafe_allow_html=True)
                            
                            edited_draft = st.text_area(
                                "AI Draft", 
                                value=st.session_state["ai_drafts"][comment_id], 
                                height=68, 
                                label_visibility="collapsed",
                                key=f"edit_ai_{comment_id}"
                            )
                            
                            ca1, ca2 = st.columns([6, 1])
                            with ca2:
                                if st.button("Send ➤", type="primary", key=f"send_ai_{comment_id}", use_container_width=True):
                                    final_reply = st.session_state[f"edit_ai_{comment_id}"]
                                    if final_reply.strip():
                                        try:
                                            youtube.comments().insert(
                                                part="snippet",
                                                body={"snippet": {"parentId": comment_id, "textOriginal": final_reply}}
                                            ).execute()
                                            
                                            st.session_state["replied_comments"].add(comment_id)
                                            st.session_state["sent_replies_log"][comment_id] = final_reply
                                            st.rerun() 
                                        except Exception:
                                            st.error("Network communication failed.")
                                    else:
                                        st.warning("Reply cannot be empty.")
                    else:
                        ca_btn, ca_mood, ca_len, ca_empty = st.columns([2.5, 1.5, 1.5, 2.5], vertical_alignment="bottom")
                        with ca_btn:
                            if st.button("🤖 Draft AI Reply", key=f"ai_{comment_id}", use_container_width=True):
                                if MASTER_API_KEY:
                                    with st.spinner("Drafting..."):
                                        try:
                                            client = genai.Client(api_key=MASTER_API_KEY)
                                            active_context = st.session_state.get("saved_channel_context", "General vlogging") 
                                            chosen_mood = st.session_state.get(f"mood_{comment_id}", st.session_state["global_mood"])
                                            chosen_length = st.session_state.get(f"len_{comment_id}", st.session_state["global_length"])
                                            
                                            single_vid_title = st.session_state["video_title_cache"].get(video_id, "Unknown Title")
                                            single_vid_desc = st.session_state["video_desc_cache"].get(video_id, "No description provided.")

                                            ambient_prompt_section = ""
                                            ambient_rule = ""
                                            if st.session_state.get("global_ai_mode") == "Deep Context":
                                                ambient_comments = [c["snippet"]["topLevelComment"]["snippet"]["textDisplay"] for c in live_comments if c["snippet"]["topLevelComment"]["snippet"].get("videoId") == video_id]
                                                ambient_text = "\n- ".join(ambient_comments[:100]) if ambient_comments else "No other comments available."
                                                ambient_prompt_section = f"\nAudience Sentiment (Read the Room):\nHere are other recent comments on this exact video. Use this to understand the general mood, inside jokes, or ongoing debates. Do NOT reply to these.\n{ambient_text}\n"
                                                ambient_rule = "7. Ambient Context: Keep the running jokes or context from the 'Audience Sentiment' in mind, but ONLY reply to the TARGET COMMENT."

                                            length_instruction = ""
                                            if chosen_length == "Small":
                                                length_instruction = "Keep it to a VERY short, single sentence (e.g., 'Hi!', 'Thank you for watching!') or just emojis."
                                            elif chosen_length == "Medium":
                                                length_instruction = "Provide a standard, medium-length response (1-2 sentences)."
                                            elif chosen_length == "Long":
                                                length_instruction = "Provide a longer, detailed and thoughtful response."

                                            prompt = f"""You are a professional YouTube creator responding to viewer comments.
Your channel's specific niche and style: {active_context}

Context about the video they commented on:
- Video Title: {single_vid_title}
- Video Description: {single_vid_desc}
{ambient_prompt_section}
TARGET COMMENT TO REPLY TO: "{text}"

Criteria:
1. Tone: MUST be heavily styled in a {chosen_mood.upper()} tone. Genuine and authentic.
2. Length: {length_instruction}
3. Questions: DO NOT ask questions automatically. ONLY ask a question if the target comment is vague/hard to understand, OR if it is a negative/angry comment (be friendly and try to understand their point). Otherwise, do not ask anything.
4. Punctuation STRICT RULE: NEVER use the dash/hyphen symbol (-). ONLY use periods, commas, exclamation marks, and question marks.
5. Negativity: Respond gracefully but firmly. No unnecessary apologies.
6. Video Context: Analyze the Video Title and Description. If the viewer asks for a link, price, or detail, and it is explicitly in the description, provide it! If not, reply naturally.
{ambient_rule}

Output ONLY the reply text."""
                                            
                                            response = client.models.generate_content(
                                                model="gemini-3.5-flash-lite", 
                                                contents=prompt
                                            )
                                            st.session_state["ai_drafts"][comment_id] = response.text.strip()
                                            st.rerun()
                                        except Exception:
                                            st.error("Service unavailable.")
                                else:
                                    st.error("System configuration missing.")
                        with ca_mood:
                            st.markdown("<div style='font-size:11px; font-weight:600; color:#888; text-transform:uppercase; margin-bottom:4px; letter-spacing:0.04em;'>Mood</div>", unsafe_allow_html=True)
                            local_mood = st.selectbox("Mood", mood_options, index=mood_options.index(st.session_state["global_mood"]), key=f"mood_{comment_id}", label_visibility="collapsed")
                        with ca_len:
                            st.markdown("<div style='font-size:11px; font-weight:600; color:#888; text-transform:uppercase; margin-bottom:4px; letter-spacing:0.04em;'>Length</div>", unsafe_allow_html=True)
                            local_length = st.selectbox("Length", length_options, index=length_options.index(st.session_state["global_length"]), key=f"len_{comment_id}", label_visibility="collapsed")
                    
                    with st.container(border=True):
                        st.markdown("<div style='font-size:11px; font-weight:600; color:#888; text-transform:uppercase; margin-bottom:8px; letter-spacing:0.04em;'>Manual Override</div>", unsafe_allow_html=True)
                        
                        st.text_area(
                            "Manual Reply", 
                            placeholder="Write a personal response...", 
                            height=60, 
                            label_visibility="collapsed",
                            key=f"text_{comment_id}"
                        )
                        
                        cm1, cm2 = st.columns([6, 1])
                        with cm2:
                            if st.button("Send ➤", key=f"manual_{comment_id}", use_container_width=True):
                                manual_text = st.session_state[f"text_{comment_id}"]
                                if manual_text.strip():
                                    try:
                                        youtube.comments().insert(
                                            part="snippet",
                                            body={"snippet": {"parentId": comment_id, "textOriginal": manual_text}}
                                        ).execute()
                                        
                                        st.session_state["replied_comments"].add(comment_id)
                                        st.session_state["sent_replies_log"][comment_id] = manual_text
                                        st.rerun()
                                    except Exception:
                                        st.error("Network communication failed.")
                                else:
                                    st.warning("Reply cannot be empty.")
                            
        if len(display_comments) == 0:
            st.markdown("""
            <div class="empty-state">
                <div class="empty-title">No comments found.</div>
                <div class="empty-sub">There are no comments matching your current filter selection.</div>
            </div>
            """, unsafe_allow_html=True)

        if st.session_state.get("autopilot_active") and not st.session_state.get("auto_reply_queue") and not st.session_state.get("auto_reply_paused"):
            next_run = st.session_state.get("autopilot_next_run", 0)
            
            if time.time() >= next_run:
                if st.session_state.get("autopilot_force_fetch"):
                    st.session_state["autopilot_force_fetch"] = False
                    
                    pending_auto = [c for c in display_comments if c["id"] not in handled_set]
                    if pending_auto:
                        limit = len(pending_auto) if reply_limit_str == "All" else int(reply_limit_str)
                        st.session_state["auto_reply_queue"] = pending_auto[:limit]
                        st.session_state["auto_reply_total"] = len(st.session_state["auto_reply_queue"])
                        st.session_state["auto_reply_success"] = 0
                        st.toast("✈️ Autopilot found new comments! Starting replies...")
                        st.rerun()
                    else:
                        st.toast("✈️ Autopilot scan clear. No new comments.")
                        interval = st.session_state.get("autopilot_interval", 5)
                        st.session_state["autopilot_next_run"] = time.time() + (interval * 60)
                        st.rerun()
                else:
                    st.session_state["autopilot_force_fetch"] = True
                    st.session_state.pop("master_comments_cache", None)
                    st.session_state.pop("cached_live_comments", None)
                    st.session_state.pop("channel_comments", None)
                    st.rerun()
            else:
                time.sleep(1)
                st.rerun()

elif st.session_state.get("youtube_creds") is None:
    
    auth_url = "#"
    if CLIENT_ID and CLIENT_SECRET:
        try:
            client_config = {
                "web": {
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
            flow = Flow.from_client_config(
                client_config,
                scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
                redirect_uri=REDIRECT_URI
            )
            auth_url, _ = flow.authorization_url(prompt='consent', include_granted_scopes='true')
            st.session_state["saved_code_verifier"] = flow.code_verifier
            with open(".verifier", "w") as f:
                f.write(flow.code_verifier)
        except Exception:
            pass

    st.markdown("""
    <div class="system-header">
        <h1 class="main-title">Cruise Comment</h1>
        <p class="sub-title">Your audience engagement, on cruise control.</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("""
        <div class="hero-gallery">
            <div class="hero-item hero-outer left">
                <img src="https://images.unsplash.com/photo-1516251193007-45ef944ab0c6?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80" alt="Creator Studio">
            </div>
            <div class="hero-item hero-far left">
                <img src="https://images.unsplash.com/photo-1611262588024-d12430b98920?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80" alt="Instagram Interface">
            </div>
            <div class="hero-item hero-side left">
                <img src="https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80" alt="Influencer Girl">
            </div>
            <div class="hero-item hero-main">
                <img src="https://images.unsplash.com/photo-1522071820081-009f0129c71c?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80" alt="Social Media Manager">
            </div>
            <div class="hero-item hero-side right">
                <img src="https://images.unsplash.com/photo-1551836022-d5d88e9218df?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80" alt="Influencer Guy">
            </div>
            <div class="hero-item hero-far right">
                <img src="https://images.unsplash.com/photo-1611162616475-46b635cb6868?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80" alt="YouTube Interface">
            </div>
            <div class="hero-item hero-outer right">
                <img src="https://images.unsplash.com/photo-1511367461989-f85a21fda167?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80" alt="Working from phone">
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3, gap="medium")

    with c1:
        with st.container(border=True):
            st.markdown('<div class="pricing-card-marker"></div>', unsafe_allow_html=True)
            
            with st.container(): 
                st.markdown('<div class="section-title">Free Tier</div>', unsafe_allow_html=True)
                st.markdown("""
                <div class="tier-feature"><span>✓</span> Requires your own Gemini API key</div>
                <div class="tier-feature"><span>✓</span> Full control over usage and limits</div>
                <div class="tier-feature"><span>✓</span> Standard comment automation</div>
                <div class="tier-feature"><span>✓</span> Single creator account</div>
                """, unsafe_allow_html=True)
                
                details_guide = """
                <details class="api-guide">
                    <summary>📖 How to get your Google API key</summary>
                    <ol>
                        <li>Go to <strong>Google AI Studio</strong> (aistudio.google.com) or Google Cloud Console.</li>
                        <li>Sign in with your Google account and click <strong>Get API key</strong>.</li>
                        <li>Create a key in a new or existing project and copy it.</li>
                        <li>Paste your key in the box below and click <strong>Test AI Connection</strong>.</li>
                        <li>Once verified, click <strong>Connect YouTube</strong> to start!</li>
                    </ol>
                </details>
                """
                st.markdown(details_guide, unsafe_allow_html=True)

                user_api_key = st.text_input("API Key", type="password", placeholder="Paste Gemini API Key here...", label_visibility="collapsed")
                
                if st.button("🤖 Test AI Connection", use_container_width=True, key="free_btn"):
                    if not user_api_key or not user_api_key.strip():
                        st.markdown("""
                        <div style="background-color: #FFF8E6; border: 1px solid #FFCC00; color: #995B00; padding: 12px; border-radius: 6px; font-size: 13px; font-weight: 500; margin-bottom: 12px;">
                            ⚠️ Please paste your Gemini API key first.
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        with st.spinner("Connecting to Gemini..."):
                            try:
                                client = genai.Client(api_key=user_api_key.strip())
                                response = client.models.generate_content(
                                    model="gemini-3.5-flash-lite", 
                                    contents="Say hello in 3 words."
                                )
                                st.markdown("""
                                <div style="background-color: #F2FDF5; border: 1px solid #34C759; color: #248A3D; padding: 12px; border-radius: 6px; font-size: 13px; font-weight: 500; margin-bottom: 12px;">
                                    ✓ Connection established! Click on Connect YouTube below.
                                </div>
                                """, unsafe_allow_html=True)
                            except Exception:
                                st.markdown("""
                                <div style="background-color: #FFF0F0; border: 1px solid #FF3B30; color: #D70015; padding: 12px; border-radius: 6px; font-size: 13px; font-weight: 500; margin-bottom: 12px;">
                                    🛑 Invalid API key. Please check your key and try again.
                                </div>
                                """, unsafe_allow_html=True)
            
            st.markdown(f'''
            <div class="pricing-bottom-zone">
                <div class="bottom-action-group">
                    <a href="{auth_url}" target="_top" class="auth-btn"><span style="color: #34C759; margin-right: 6px; font-size: 16px;">●</span>Connect YouTube</a>
                    <a href="#" target="_top" class="auth-btn disabled-btn"><span style="color: #888888; margin-right: 6px; font-size: 16px;">●</span>Connect Instagram <span class="beta-tag">BETA</span></a>
                </div>
            </div>
            ''', unsafe_allow_html=True)

    with c2:
        with st.container(border=True):
            st.markdown('<div class="pricing-card-marker"></div>', unsafe_allow_html=True)
            
            with st.container(): 
                st.markdown('<div class="section-title">Pro Tier</div>', unsafe_allow_html=True)
                st.markdown("""
                <div class="tier-feature"><span>✓</span> No API key required</div>
                <div class="tier-feature"><span>✓</span> Powered by Master AI engine</div>
                <div class="tier-feature"><span>✓</span> 100% free during the Beta</div>
                <div class="tier-feature"><span>✓</span> Single creator account</div>
                """, unsafe_allow_html=True)
                
                if st.button("🤖 Test AI Connection", type="primary", use_container_width=True, key="pro_btn"):
                    if MASTER_API_KEY:
                        with st.spinner("Connecting to Master Engine..."):
                            try:
                                client = genai.Client(api_key=MASTER_API_KEY)
                                response = client.models.generate_content(
                                    model="gemini-3.5-flash-lite", 
                                    contents="Say hello in 3 words."
                                )
                                st.markdown("""
                                <div style="background-color: #F2FDF5; border: 1px solid #34C759; color: #248A3D; padding: 12px; border-radius: 6px; font-size: 13px; font-weight: 500; margin-bottom: 12px;">
                                    ✓ Master AI active! Click on Connect YouTube below.
                                </div>
                                """, unsafe_allow_html=True)
                            except Exception:
                                st.markdown("""
                                <div style="background-color: #FFF0F0; border: 1px solid #FF3B30; color: #D70015; padding: 12px; border-radius: 6px; font-size: 13px; font-weight: 500; margin-bottom: 12px;">
                                    🛑 Master system error. Please check backend configuration.
                                </div>
                                """, unsafe_allow_html=True)
                    else:
                        st.markdown("""
                        <div style="background-color: #FFF0F0; border: 1px solid #FF3B30; color: #D70015; padding: 12px; border-radius: 6px; font-size: 13px; font-weight: 500; margin-bottom: 12px;">
                            🛑 Configuration missing.
                        </div>
                        """, unsafe_allow_html=True)
            
            st.markdown(f'''
            <div class="pricing-bottom-zone">
                <div class="bottom-action-group">
                    <a href="{auth_url}" target="_top" class="auth-btn"><span style="color: #34C759; margin-right: 6px; font-size: 16px;">●</span>Connect YouTube <span class="beta-tag">BETA</span></a>
                    <a href="#" target="_top" class="auth-btn disabled-btn"><span style="color: #888888; margin-right: 6px; font-size: 16px;">●</span>Connect Instagram <span class="beta-tag">BETA</span></a>
                </div>
            </div>
            ''', unsafe_allow_html=True)
                    
    with c3:
        with st.container(border=True):
            st.markdown('<div class="pricing-card-marker"></div>', unsafe_allow_html=True)
            
            with st.container(): 
                st.markdown('<div class="section-title">Talent Manager</div>', unsafe_allow_html=True)
                st.markdown("""
                <div class="tier-feature"><span>✓</span> Connect multiple creator accounts</div>
                <div class="tier-feature"><span>✓</span> Centralized engagement dashboard</div>
                <div class="tier-feature"><span>✓</span> Handle cross-platform DMs & mentions</div>
                <div class="tier-feature"><span>✓</span> Advanced analytics & team permissions</div>
                """, unsafe_allow_html=True)
            
            st.markdown(f'''
            <div class="pricing-bottom-zone">
                <div class="bottom-action-group">
                    <a href="#" target="_top" class="auth-btn disabled-btn">Initialize Agency Engine <span class="beta-tag">BETA</span></a>
                </div>
            </div>
            ''', unsafe_allow_html=True)
