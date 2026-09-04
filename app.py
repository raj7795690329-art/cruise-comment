import streamlit as st
import os
import json
import base64
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from dotenv import load_dotenv
from google import genai
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import time
from datetime import datetime, timezone
import streamlit.components.v1 as components

# --- Open the secure vault & Bridge Streamlit Cloud Secrets ---
load_dotenv()

def get_secret(key, default=None):
    val = None
    if key in os.environ and os.environ[key]:
        val = os.environ[key]
    try:
        if key in st.secrets and st.secrets[key]:
            val = st.secrets[key]
    except Exception:
        pass
    if val and "your_actual" in str(val).lower():
        return default
    return val or default

# Master keys are used for the Pro Tier
MASTER_API_KEY = get_secret("GEMINI_API_KEY")
MASTER_CLIENT_ID = get_secret("GOOGLE_CLIENT_ID")
MASTER_CLIENT_SECRET = get_secret("GOOGLE_CLIENT_SECRET")

# Hardcoded Live App URL for YouTube OAuth
APP_URL = "https://cruise-comment-ai.streamlit.app"

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# --- Page Config ---
st.set_page_config(
    layout="wide", 
    page_title="Cruise Comment", 
    page_icon="🤖",
    initial_sidebar_state="expanded"
)

# --- Persistent Local Storage for Keys, Tokens & Context ---
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

# --- Initialize Session States ---
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
    "active_ai_model": "gemini-3.6-flash", 
    "video_title_cache": {},
    "video_desc_cache": {},
    "selected_video_filter": "[0] All Videos",
    "video_mapping_cache": {},
    "channel_comments": [],
    "auto_reply_queue": [],   
    "auto_reply_total": 0,    
    "auto_reply_success": 0,
    "auto_reply_paused": False,
    "last_scrolled_id": None,
    "autopilot_active": False,
    "autopilot_interval": 5,
    "force_fetch": True,
    "session_visible_handled": set(),
    "queue_warning": None
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

# Minimal layout styling & Animation Keyframes
st.markdown("""
    <style>
        .block-container { padding-top: 2rem !important; padding-bottom: 2rem !important; max-width: 1100px !important; }
        header[data-testid="stHeader"] { display: none; }
        
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        
        .hero-gallery {
            display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important;
            justify-content: center !important; align-items: center !important;
            margin: 24px auto 48px auto !important; width: 100% !important; min-height: 300px !important;
        }
        .hero-item {
            position: relative !important; flex: 0 0 auto !important; border-radius: 18px !important; 
            overflow: hidden !important; box-shadow: 0 8px 24px rgba(0,0,0,0.08) !important;
            margin: 0 -12px !important; 
        }
        .hero-item img { display: block !important; object-fit: cover !important; width: 100% !important; height: 100% !important; }
        .hero-main  { width: 240px !important; height: 280px !important; z-index: 4 !important; }
        .hero-side  { width: 190px !important; height: 230px !important; z-index: 3 !important; }
        .hero-far   { width: 140px !important; height: 180px !important; z-index: 2 !important; }
        .hero-outer { width: 100px !important; height: 130px !important; z-index: 1 !important; }
        .hero-outer.left { top: 24px !important; } .hero-far.left { top: -16px !important; } .hero-side.left { top: 12px !important; }
        .hero-main { top: 0px !important; } .hero-side.right { top: -12px !important; } .hero-far.right { top: 16px !important; } .hero-outer.right{ top: -24px !important; }
        
        .auth-btn { display: inline-block; background-color: #3A3A3C !important; color: #FFFFFF !important; border-radius: 6px !important; font-weight: 500 !important; font-size: 13px !important; text-align: center !important; width: 100% !important; padding: 10px 12px !important; text-decoration: none !important; box-sizing: border-box; height: 38px; line-height: 18px; }
        .auth-btn:hover { background-color: #2C2C2E !important; color: #FFFFFF !important; }
        .disabled-btn { background-color: #F0F0F2 !important; color: #888888 !important; border: 1px solid #E5E5EA !important; pointer-events: none !important; }
    </style>
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
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px;">
                <img src="{channel_logo}" style="width: 36px; height: 36px; border-radius: 50%; border: 1px solid #4CAF50;">
                <div style="font-weight: 500; font-size: 14px; line-height: 1.2;">Connected as:<br><span style="color: #4CAF50; font-weight: 600;">{channel_name}</span></div>
            </div>
        """, unsafe_allow_html=True)
        
        c1, c2 = st.columns([7, 3])
        if c1.button("⏻ Disconnect", use_container_width=True):
            st.session_state["youtube_creds"] = None
            st.session_state["session_visible_handled"] = set()
            if os.path.exists(TOKENS_FILE):
                os.remove(TOKENS_FILE)
            st.rerun()
        if c2.button("🔄", help="Refresh latest comments", on_click=force_refresh_comments, use_container_width=True):
            pass
            
        if st.session_state.get("auto_reply_total") > 0:
            st.divider()
            st.subheader("🚀 Cruising Progress")
            
            if st.session_state.get("queue_warning"):
                st.error(st.session_state["queue_warning"])

            total = st.session_state["auto_reply_total"]
            left = len(st.session_state["auto_reply_queue"])
            processed = total - left
            success = st.session_state.get("auto_reply_success", 0)
            failed = processed - success
            
            prog_pct = int((processed / total) * 100) if total > 0 else 0
            sent_pct = int((success / total) * 100) if total > 0 else 0
            fail_pct = int((failed / total) * 100) if total > 0 else 0
            
            st.progress(processed / total if total > 0 else 0.0)
            st.write(f"**Processed: {processed}/{total} ({prog_pct}%)**")
            st.write(f"✅ Sent: {success} ({sent_pct}%) | ⚠️ Errors: {failed} ({fail_pct}%)")
            
            if left > 0:
                if not st.session_state.get("auto_reply_paused"):
                    st.button("🛑 Pause", on_click=pause_auto_reply, use_container_width=True)
                else:
                    c3, c4 = st.columns(2)
                    with c3: st.button("▶ Resume", on_click=resume_auto_reply, use_container_width=True)
                    with c4: 
                        def cancel_queue():
                            st.session_state["auto_reply_queue"] = []
                            st.session_state["auto_reply_total"] = 0
                            st.session_state["auto_reply_paused"] = False
                            st.session_state.pop("queue_warning", None)
                        st.button("❌ Cancel", type="primary", on_click=cancel_queue, use_container_width=True)
            else:
                c3, c4 = st.columns([7, 3])
                c3.button("✅ Completed", disabled=True, use_container_width=True)
                def clear_completed():
                    st.session_state["auto_reply_queue"] = []
                    st.session_state["auto_reply_total"] = 0
                    st.session_state["auto_reply_paused"] = False
                    st.session_state.pop("queue_warning", None)
                c4.button("❌ Close", type="primary", on_click=clear_completed, help="Close Queue Widget", use_container_width=True)

        st.divider()
        st.title("Instagram")
        st.button("Connect Instagram (BETA)", disabled=True, use_container_width=True)
        st.divider()

        st.title("Cruise Autopilot ✈️")
        st.caption("Run Cruise in the background to automatically scan for and reply to new comments.")
        
        autopilot_on = st.toggle("Enable Autopilot", value=st.session_state.get("autopilot_active", False))
        
        if autopilot_on:
            autopilot_interval = st.number_input("Scan Interval (Minutes)", min_value=1, max_value=1440, value=st.session_state.get("autopilot_interval", 5))
            st.session_state["autopilot_interval"] = autopilot_interval
            
        if autopilot_on != st.session_state.get("autopilot_active", False):
            st.session_state["autopilot_active"] = autopilot_on
            if autopilot_on:
                st.session_state["autopilot_next_run"] = time.time() 
            else:
                st.session_state.pop("autopilot_next_run", None)
                st.session_state["force_fetch"] = False
            st.rerun()
            
        st.divider()
        st.title("Today's Stats")
        st.metric("Total Fetched Comments", total_fetched)
        st.metric("Replies Handled", handled_count)
        st.metric("Need Attention", pending_count)

    def set_video_filter(target_option):
        st.session_state["selected_video_filter"] = target_option

    # --- Dashboard View ---
    if channel_id is not None:
        
        st.title("Cruise Comment")
        st.caption("Your audience engagement, on cruise control. ✅ Active")

        col1, col2, col3 = st.columns(3)
        with col1: st.metric("Recent Comments", total_fetched)
        with col2: st.metric("Replies Handled", f"{handled_count} ({handled_pct}%)")
        with col3: st.metric("Need Attention", f"{pending_count} ({pending_pct}%)")

        st.subheader("Reply Style Instructions")
        
        with st.container(border=True):
            if not st.session_state.get("context_locked"):
                current_niche_input = st.text_area(
                    "Channel Niche & Vibe", 
                    value=st.session_state.get("saved_channel_context", ""),
                    placeholder="e.g., We review mid-range motorcycles. Be objective but friendly. End with a question.",
                    height=60,
                    label_visibility="collapsed"
                )
                col1, col2 = st.columns([5, 1])
                with col2:
                    if st.button("💾 Save Settings", use_container_width=True):
                        st.session_state["saved_channel_context"] = current_niche_input
                        st.session_state["context_locked"] = True
                        with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
                            f.write(current_niche_input.strip())
                        st.rerun()
            else:
                c1, c2 = st.columns([5, 1], vertical_alignment="center")
                display_text = st.session_state.get('saved_channel_context', 'No custom style provided.')
                c1.info(f"**Current Style:** {display_text}")
                if c2.button("✎ Edit", use_container_width=True):
                    st.session_state["context_locked"] = False
                    st.rerun()

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

        active_vids = [v for v in unique_video_ids if video_unresponded_counts[v] > 0]
        sorted_vids = sorted(active_vids, key=lambda v: video_unresponded_counts[v], reverse=True)
        
        total_pending_all = len([c for c in all_comments_for_dropdown if c["id"] not in handled_set])
        all_videos_label = f"[{total_pending_all}] All Videos"
        video_options = [all_videos_label]
        video_mapping[all_videos_label] = None

        for vid in sorted_vids:
            base_title = st.session_state["video_title_cache"].get(vid, f"Video {vid}")
            count = video_unresponded_counts[vid]
            short_title = base_title[:19].strip() + "..." if len(base_title) > 22 else base_title
            
            display_title = f"[{count}] {short_title}"
            if display_title in video_mapping: display_title = f"[{count}] {short_title} (2)"
            video_options.append(display_title)
            video_mapping[display_title] = vid

        st.session_state["video_mapping_cache"] = video_mapping
        current_selection = st.session_state.get("selected_video_filter", all_videos_label)
        
        current_base = current_selection.split("] ")[1] if "] " in current_selection else current_selection
        matched_opt = all_videos_label
        for opt in video_options:
            opt_base = opt.split("] ")[1] if "] " in opt else opt
            if current_base == opt_base:
                matched_opt = opt
                break
                
        current_selection = matched_opt
        st.session_state["selected_video_filter"] = current_selection

        st.markdown("<hr/>", unsafe_allow_html=True)
        
        col_v, col_f, col_s, col_m, col_len, col_mod, col_l, col_b = st.columns([1.8, 1.1, 1.5, 1.1, 1.1, 1.4, 0.9, 1.6], vertical_alignment="bottom")
        
        with col_v:
            selected_video_title = st.selectbox("Video Filter", video_options, index=video_options.index(current_selection))
            st.session_state["selected_video_filter"] = selected_video_title
        with col_f:
            filter_view = st.selectbox("View", ["Unresponded", "All Comments", "Handled"])
        with col_s:
            sort_order = st.selectbox("Sort", ["Newest to Oldest", "Oldest to Newest", "Video Name (A-Z)"])
        with col_m:
            global_mood = st.selectbox("Mood", ["Friendly", "Professional", "Funny", "Sassy"], index=["Friendly", "Professional", "Funny", "Sassy"].index(st.session_state["global_mood"]))
            st.session_state["global_mood"] = global_mood
        with col_len:
            global_length = st.selectbox("Length", ["Small", "Medium", "Long"], index=["Small", "Medium", "Long"].index(st.session_state["global_length"]))
            st.session_state["global_length"] = global_length
        with col_mod:
            is_enhanced = st.session_state.get("global_ai_mode") == "Deep Context"
            btn_label = "🟢 Enhanced Reply ON" if is_enhanced else "⚪ Enhanced Reply OFF"
            if st.button(btn_label, use_container_width=True, help="Analyzes surrounding comments for context."):
                st.session_state["global_ai_mode"] = "Standard" if is_enhanced else "Deep Context"
                st.rerun()
        with col_l:
            reply_limit_str = st.selectbox("Limit", ["5", "10", "20", "50", "100", "All"], index=5)

        display_comments = live_comments
        active_filter = st.session_state["selected_video_filter"]
        target_vid = video_mapping.get(active_filter)

        if target_vid is not None:
            display_comments = [c for c in display_comments if c["snippet"]["topLevelComment"]["snippet"].get("videoId") == target_vid]

        if filter_view == "Unresponded": 
            display_comments = [c for c in display_comments if c["id"] not in handled_set or c["id"] in st.session_state.get("session_visible_handled", set())]
        elif filter_view == "Handled": 
            display_comments = [c for c in display_comments if c["id"] in handled_set]

        if sort_order == "Newest to Oldest": display_comments = sorted(display_comments, key=lambda x: x["snippet"]["topLevelComment"]["snippet"]["publishedAt"], reverse=True)
        elif sort_order == "Oldest to Newest": display_comments = sorted(display_comments, key=lambda x: x["snippet"]["topLevelComment"]["snippet"]["publishedAt"], reverse=False)
        else: display_comments = sorted(display_comments, key=lambda x: st.session_state["video_title_cache"].get(x["snippet"]["topLevelComment"]["snippet"].get("videoId", ""), "").lower())

        with col_b:
            is_replying_btn = bool(st.session_state.get("auto_reply_queue"))
            btn_text = "🤖 Auto-Replying..." if is_replying_btn else "🤖 Reply All with AI"
            if st.button(btn_text, disabled=is_replying_btn, use_container_width=True):
                active_key = MASTER_API_KEY or saved_keys.get("api_key") or st.session_state.get("user_gemini_api_key")
                if active_key:
                    pending_in_view = [c for c in display_comments if c["id"] not in st.session_state["replied_comments"]]
                    if not pending_in_view:
                        st.toast("No pending comments in the current view to reply to!")
                    else:
                        limit = len(pending_in_view) if reply_limit_str == "All" else int(reply_limit_str)
                        st.session_state["auto_reply_queue"] = pending_in_view[:limit]
                        for c_item in st.session_state["auto_reply_queue"]:
                            c_item["retry_count"] = 0
                        st.session_state["auto_reply_total"] = limit
                        st.session_state["auto_reply_success"] = 0
                        st.session_state["auto_reply_paused"] = False 
                        st.rerun() 
                else:
                    st.error("API Key missing. Please provide an API key in Setup.")

        is_replying_active = bool(st.session_state.get("auto_reply_queue"))
        processing_id = None
        if is_replying_active and not st.session_state.get("auto_reply_paused"):
            processing_id = st.session_state["auto_reply_queue"][0]["id"]

        is_all_videos = "All Videos" in current_selection

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
                vid_title = st.session_state["video_title_cache"].get(video_id, "Unknown Video")
                
                if comment_id == processing_id:
                    with st.container(border=True):
                        st.markdown(f'<div id="processing-card-{comment_id}"></div>', unsafe_allow_html=True)
                        
                        st.markdown("""
                            <div style='display: flex; align-items: center; color: #FF9500; font-weight: 700; margin-bottom: 12px; font-size: 14px;'>
                                <div style='border: 3px solid rgba(255,149,0,0.3); border-top: 3px solid #FF9500; border-radius: 50%; width: 16px; height: 16px; animation: spin 1s linear infinite; margin-right: 10px;'></div>
                                CRUISING... DRAFTING REPLY
                            </div>
                        """, unsafe_allow_html=True)
                        
                        st.markdown(f"**{author}** • {formatted_date}")
                        st.markdown(f"> {text}")
                        
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

                if comment_id in handled_set and comment_id not in st.session_state.get("ai_errors", {}):
                    sent_text = st.session_state.get("sent_replies_log", {}).get(comment_id, "Previously replied on YouTube.")
                    
                    with st.container(border=True):
                        cols = st.columns([6, 1])
                        with cols[0]:
                            if is_all_videos: st.markdown(f"📺 **{vid_title}**")
                            st.markdown(f"**{author}** • {formatted_date} ({relative_time})")
                            st.markdown(f"> {text}")
                            st.success(f"✓ Handled: {sent_text}")
                        with cols[1]:
                            if video_id: st.image(f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg", use_container_width=True)
                    continue
                
                with st.container(border=True):
                    
                    if is_all_videos:
                        v_col1, v_col2 = st.columns([5, 2], vertical_alignment="center")
                        v_col1.markdown(f"📺 **{vid_title}**")
                        v_col2.button("▶ Filter to this Video", key=f"vt_pending_{comment_id}", on_click=set_video_filter, args=(target_option,))
                    
                    st.markdown(f"**{author}** • {formatted_date} ({relative_time})")
                    
                    txt_col, thumb_col = st.columns([6, 1], gap="medium")
                    txt_col.markdown(f"> {text}")
                    if video_id: thumb_col.image(f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg", use_container_width=True)
                    
                    if comment_id in st.session_state.get("ai_drafts", {}):
                        st.caption("🤖 AI Draft Verification")
                        edited_draft = st.text_area("AI Draft", value=st.session_state["ai_drafts"][comment_id], height=68, label_visibility="collapsed", key=f"edit_ai_{comment_id}")
                        
                        ca1, ca2 = st.columns([6, 1])
                        if ca2.button("Send ➤", key=f"send_ai_{comment_id}", use_container_width=True):
                            final_reply = st.session_state[f"edit_ai_{comment_id}"]
                            if final_reply.strip():
                                try:
                                    youtube.comments().insert(
                                        part="snippet",
                                        body={"snippet": {"parentId": comment_id, "textOriginal": final_reply}}
                                    ).execute()
                                    
                                    st.session_state["replied_comments"].add(comment_id)
                                    st.session_state["sent_replies_log"][comment_id] = final_reply
                                    st.session_state["session_visible_handled"].add(comment_id)
                                    st.rerun() 
                                except Exception:
                                    st.error("Network communication failed.")
                            else:
                                st.warning("Reply cannot be empty.")
                    else:
                        ca_btn, ca_mood, ca_len = st.columns([2, 2, 2], vertical_alignment="bottom")
                        if ca_btn.button("🤖 Draft AI Reply", key=f"ai_{comment_id}", use_container_width=True):
                            active_key = MASTER_API_KEY or saved_keys.get("api_key") or st.session_state.get("user_gemini_api_key")
                            if active_key:
                                with st.spinner("Drafting..."):
                                    try:
                                        client = genai.Client(api_key=active_key)
                                        active_context = st.session_state.get("saved_channel_context", "General vlogging") 
                                        chosen_mood = st.session_state.get(f"mood_{comment_id}", st.session_state["global_mood"])
                                        chosen_length = st.session_state.get(f"len_{comment_id}", st.session_state["global_length"])
                                        
                                        single_vid_desc = st.session_state["video_desc_cache"].get(video_id, "No description provided.")[:800]
                                        ambient_prompt_section = ""
                                        ambient_rule = ""
                                        if st.session_state.get("global_ai_mode") == "Deep Context":
                                            ambient_comments = [c["snippet"]["topLevelComment"]["snippet"]["textDisplay"] for c in live_comments if c["snippet"]["topLevelComment"]["snippet"].get("videoId") == video_id]
                                            ambient_text = "\n- ".join(ambient_comments[:50]) if ambient_comments else "No other comments available."
                                            ambient_prompt_section = f"\nAudience Sentiment:\n{ambient_text}\n"
                                            ambient_rule = "7. Keep audience sentiment in mind, but ONLY reply to the TARGET COMMENT."

                                        length_instruction = "Provide a standard response."
                                        if chosen_length == "Small": length_instruction = "Keep it to a VERY short, single sentence or emojis."
                                        elif chosen_length == "Long": length_instruction = "Provide a longer, detailed response."

                                        prompt = f"""You are a professional YouTube creator responding to viewer comments.
Your channel's specific niche and style: {active_context}

Context about the video they commented on:
- Video Title: {vid_title}
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
                                        
                                        active_model = st.session_state.get("active_ai_model", "gemini-3.6-flash")
                                        try:
                                            response = client.models.generate_content(
                                                model=active_model, 
                                                contents=prompt
                                            )
                                        except Exception as inner_e:
                                            err_str = str(inner_e)
                                            if ("503" in err_str or "429" in err_str) and active_model == "gemini-3.6-flash":
                                                st.session_state["active_ai_model"] = "gemini-3.5-flash"
                                                st.toast("Capacity/Quota limit reached. Switching AI engine to 3.5-flash.")
                                                time.sleep(2)
                                                response = client.models.generate_content(
                                                    model="gemini-3.5-flash", 
                                                    contents=prompt
                                                )
                                            else:
                                                raise inner_e

                                        st.session_state["ai_drafts"][comment_id] = response.text.strip()
                                        st.rerun()
                                    except Exception as e:
                                        st.session_state["ai_errors"][comment_id] = str(e)
                                        st.error(f"Service unavailable: {e}")
                            else:
                                st.error("API Key missing. Please provide an API key in Setup.")
                                
                        ca_mood.selectbox("Mood", ["Friendly", "Professional", "Funny", "Sassy"], index=["Friendly", "Professional", "Funny", "Sassy"].index(st.session_state["global_mood"]), key=f"mood_{comment_id}", label_visibility="collapsed")
                        ca_len.selectbox("Length", ["Small", "Medium", "Long"], index=["Small", "Medium", "Long"].index(st.session_state["global_length"]), key=f"len_{comment_id}", label_visibility="collapsed")
                    
                    if comment_id in st.session_state.get("ai_errors", {}):
                        st.error(f"🛑 **Queue Halted / AI Error:** {st.session_state['ai_errors'][comment_id]}")
                    else:
                        st.caption("✎ Custom Manual Reply")
                        
                    st.text_area("Manual Reply", placeholder="Write a personal response...", height=60, label_visibility="collapsed", key=f"text_{comment_id}")
                    cm1, cm2 = st.columns([6, 1])
                    if cm2.button("Send ➤", key=f"manual_{comment_id}", use_container_width=True):
                        manual_text = st.session_state[f"text_{comment_id}"]
                        if manual_text.strip():
                            try:
                                youtube.comments().insert(
                                    part="snippet",
                                    body={"snippet": {"parentId": comment_id, "textOriginal": manual_text}}
                                ).execute()
                                
                                st.session_state["replied_comments"].add(comment_id)
                                st.session_state["sent_replies_log"][comment_id] = manual_text
                                st.session_state["session_visible_handled"].add(comment_id)
                                if comment_id in st.session_state.get("ai_errors", {}):
                                    del st.session_state["ai_errors"][comment_id]
                                st.rerun()
                            except Exception:
                                st.error("Network communication failed.")
                        else:
                            st.warning("Reply cannot be empty.")
                            
        if len(display_comments) == 0:
            st.info("No comments found matching your current filter selection.")

        # --- PROCESS THE AUTO-REPLY QUEUE ---
        if is_replying_active and not st.session_state.get("auto_reply_paused"):
            current_item = st.session_state["auto_reply_queue"][0]
            comment_id = current_item["id"]
            video_id = current_item["snippet"]["topLevelComment"]["snippet"].get("videoId", "")
            text = current_item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            
            try:
                active_key = MASTER_API_KEY or saved_keys.get("api_key") or st.session_state.get("user_gemini_api_key")
                client = genai.Client(api_key=active_key)
                active_context = st.session_state.get("saved_channel_context", "General vlogging") 
                chosen_mood = st.session_state["global_mood"]
                chosen_length = st.session_state["global_length"]
                
                single_vid_title = st.session_state["video_title_cache"].get(video_id, "Unknown Title")
                single_vid_desc = st.session_state["video_desc_cache"].get(video_id, "No description provided.")[:800]

                ambient_prompt_section = ""
                ambient_rule = ""
                if st.session_state.get("global_ai_mode") == "Deep Context":
                    ambient_comments = [c["snippet"]["topLevelComment"]["snippet"]["textDisplay"] for c in live_comments if c["snippet"]["topLevelComment"]["snippet"].get("videoId") == video_id]
                    ambient_text = "\n- ".join(ambient_comments[:50]) if ambient_comments else "No other comments."
                    ambient_prompt_section = f"\nAudience Sentiment:\n{ambient_text}\n"
                    ambient_rule = "7. Keep audience sentiment in mind, but ONLY reply to the TARGET COMMENT."

                length_instruction = "Provide a standard response."
                if chosen_length == "Small": length_instruction = "Keep it to a VERY short, single sentence or emojis."
                elif chosen_length == "Long": length_instruction = "Provide a longer, detailed response."

                prompt = f"""You are a professional YouTube creator responding to viewer comments.
Your channel's specific niche and style: {active_context}

Context about the video:
- Title: {single_vid_title}
- Description: {single_vid_desc}
{ambient_prompt_section}
TARGET COMMENT TO REPLY TO: "{text}"

Criteria:
1. Tone: {chosen_mood.upper()}. Authentic.
2. Length: {length_instruction}
3. Do not ask questions automatically.
4. NEVER use the dash/hyphen symbol (-).
{ambient_rule}

Output ONLY the reply text."""

                active_model = st.session_state.get("active_ai_model", "gemini-3.6-flash")
                try:
                    response = client.models.generate_content(
                        model=active_model, 
                        contents=prompt
                    )
                except Exception as inner_e:
                    err_str = str(inner_e)
                    if ("503" in err_str or "429" in err_str) and active_model == "gemini-3.6-flash":
                        st.session_state["active_ai_model"] = "gemini-3.5-flash"
                        st.toast("Capacity/Quota limit reached. Switching AI engine to 3.5-flash.")
                        time.sleep(2)
                        response = client.models.generate_content(
                            model="gemini-3.5-flash", 
                            contents=prompt
                        )
                    else:
                        raise inner_e

                final_reply = response.text.strip()
                
                youtube.comments().insert(
                    part="snippet",
                    body={"snippet": {"parentId": comment_id, "textOriginal": final_reply}}
                ).execute()
                
                st.session_state["replied_comments"].add(comment_id)
                st.session_state["sent_replies_log"][comment_id] = final_reply
                st.session_state["session_visible_handled"].add(comment_id)
                st.session_state["auto_reply_success"] += 1
                
                st.session_state["auto_reply_queue"].pop(0)
                time.sleep(4)
                st.rerun()

            except Exception as e:
                err_str = str(e)
                retry_count = current_item.get("retry_count", 0)
                
                if "429" in err_str and retry_count < 2 and "GenerateRequestsPerDay" not in err_str:
                    st.session_state["auto_reply_queue"][0]["retry_count"] = retry_count + 1
                    st.session_state["queue_warning"] = "⏳ Google API speed limit hit! Auto-pausing queue for 30 seconds..."
                    time.sleep(30)
                    st.rerun() 
                else:
                    error_msg = "429 Quota Exhausted: Daily API limit completely drained." if "429" in err_str else err_str
                    st.session_state["ai_errors"][comment_id] = error_msg
                    st.session_state["auto_reply_paused"] = True
                    st.session_state["queue_warning"] = f"🛑 Queue halted: {error_msg}"
                    st.rerun()

        # --- AUTOPILOT ---
        if st.session_state.get("autopilot_active") and not st.session_state.get("auto_reply_queue") and not st.session_state.get("auto_reply_paused"):
            next_run = st.session_state.get("autopilot_next_run", 0)
            
            if time.time() >= next_run:
                if st.session_state.get("autopilot_force_fetch"):
                    st.session_state["force_fetch"] = True
                    st.session_state.pop("channel_comments", None)
                    
                    pending_auto = [c for c in display_comments if c["id"] not in handled_set]
                    if pending_auto:
                        limit = len(pending_auto) if reply_limit_str == "All" else int(reply_limit_str)
                        st.session_state["auto_reply_queue"] = pending_auto[:limit]
                        for c_item in st.session_state["auto_reply_queue"]:
                            c_item["retry_count"] = 0
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
                    st.session_state["force_fetch"] = True
                    st.session_state.pop("channel_comments", None)
                    st.rerun()
            else:
                time.sleep(1)
                st.rerun()

elif st.session_state.get("youtube_creds") is None:
    
    st.title("Cruise Comment")
    st.caption("Your audience engagement, on cruise control.")
    
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
            st.subheader("Free Tier")
            st.markdown("""
            * ✓ Requires your own Gemini API key
            * ✓ Full control over usage and limits
            * ✓ Standard comment automation
            * ✓ Single creator account
            """)
            
            details_guide = """
            <details style="margin-bottom: 12px; font-size: 13px;">
                <summary>📖 How to get your Google API key (AI Studio)</summary>
                <ol style="margin-top: 8px;">
                    <li>Open <a href="https://aistudio.google.com/app/apikey" target="_blank">Google AI Studio</a> and sign in.</li>
                    <li>Click <strong>Create API key</strong> and select <strong>Default Gemini Project</strong>.</li>
                    <li>Copy your key and paste it below.</li>
                </ol>
            </details>
            """
            st.markdown(details_guide, unsafe_allow_html=True)

            user_api_key = st.text_input(
                "Gemini API Key", 
                value=saved_keys.get("api_key", st.session_state.get("user_gemini_api_key", "")), 
                type="password", 
                placeholder="Paste Gemini API Key here...", 
                key="free_tier_api_key_input"
            )
            if user_api_key != st.session_state.get("user_gemini_api_key", ""):
                st.session_state["user_gemini_api_key"] = user_api_key
                update_persisted_keys(api_key=user_api_key)
            
            if st.button("🤖 Test AI Connection", use_container_width=True, key="free_btn"):
                if not user_api_key or not user_api_key.strip():
                    st.warning("Please paste your Gemini API key first.")
                else:
                    with st.spinner("Connecting to Gemini..."):
                        try:
                            client = genai.Client(api_key=user_api_key.strip())
                            response = client.models.generate_content(
                                model="gemini-3.5-flash", 
                                contents="Say hello in 3 words."
                            )
                            st.session_state["user_gemini_api_key"] = user_api_key.strip()
                            update_persisted_keys(api_key=user_api_key.strip())
                            st.success("✓ Connection established! Proceed to YouTube Connection.")
                        except Exception as e:
                            st.error(f"Google SDK Error: {str(e)}")
                            
            details_oauth_guide = f"""
            <details style="margin-top: 14px; margin-bottom: 12px; font-size: 13px;">
                <summary>🎥 How to setup YouTube Connection</summary>
                <ol style="margin-top: 8px;">
                    <li>Go to <strong>Google Cloud Console</strong> > APIs & Services > OAuth consent screen.</li>
                    <li>Set User Type to External and click <strong>Publish App</strong>.</li>
                    <li>Go to <strong>Credentials</strong> > <strong>+ Create Credentials</strong> > <strong>OAuth client ID</strong> (Web application).</li>
                    <li>Under <strong>Authorized redirect URIs</strong>, copy and paste this exact link:<br>
                        <code>{APP_URL}</code>
                    </li>
                    <li>Copy the generated <strong>Client ID</strong> and <strong>Client Secret</strong> into the boxes below.</li>
                </ol>
            </details>
            """
            st.markdown(details_oauth_guide, unsafe_allow_html=True)

            ui_cid = st.text_input(
                "Google Client ID", 
                value=saved_keys.get("client_id", st.session_state.get("user_client_id", "")), 
                placeholder="Client ID (ends in .apps.googleusercontent.com)", 
                key="ui_cid_input"
            )
            ui_sec = st.text_input(
                "Google Client Secret", 
                value=saved_keys.get("client_secret", st.session_state.get("user_client_secret", "")), 
                type="password", 
                placeholder="Client Secret", 
                key="ui_sec_input"
            )
            
            if ui_cid != st.session_state.get("user_client_id", "") or ui_sec != st.session_state.get("user_client_secret", ""):
                st.session_state["user_client_id"] = ui_cid
                st.session_state["user_client_secret"] = ui_sec
                update_persisted_keys(client_id=ui_cid, client_secret=ui_sec)
        
            free_auth_url = None
            free_oauth_error = ""
            cid = ui_cid.strip()
            csec = ui_sec.strip()
            
            if cid and csec:
                try:
                    client_config = {
                        "web": {
                            "client_id": cid,
                            "client_secret": csec,
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        }
                    }
                    flow = Flow.from_client_config(
                        client_config, 
                        scopes=["https://www.googleapis.com/auth/youtube.force-ssl"], 
                        redirect_uri=APP_URL
                    )
                    
                    free_auth_url, state_token = flow.authorization_url(
                        prompt='consent', 
                        access_type='offline',
                        include_granted_scopes='true'
                    )
                    
                    save_verifier(state_token, flow.code_verifier)
                    
                except Exception as e:
                    free_oauth_error = str(e)

            if free_auth_url:
                auth_link_html = f'<a href="{free_auth_url}" target="_blank" class="auth-btn"><span style="color: #34C759; margin-right: 6px; font-size: 16px;">●</span>Connect YouTube</a>'
            else:
                msg = free_oauth_error if free_oauth_error else "Enter your Client ID and Client Secret above to enable connection."
                auth_link_html = f'<div style="font-size: 12px; color: #888888; text-align: center; padding: 10px; background: #F0F0F2; border-radius: 6px; border: 1px solid #E5E5EA;">{msg}</div>'

            st.markdown(f'''
            <div style="margin-top: 16px; display: flex; flex-direction: column; gap: 8px;">
                {auth_link_html}
                <a href="#" target="_blank" class="auth-btn disabled-btn"><span style="color: #888888; margin-right: 6px; font-size: 16px;">●</span>Connect Instagram <span style="font-size: 10px; background: #E5E5EA; padding: 2px 4px; border-radius: 4px;">BETA</span></a>
            </div>
            ''', unsafe_allow_html=True)

    with c2:
        with st.container(border=True):
            st.subheader("Pro Tier")
            st.markdown("""
            * ✓ No API key required
            * ✓ Powered by Master AI engine
            * ✓ 100% free during the Beta
            * ✓ Single creator account
            """)
            
            if st.button("🤖 Test AI Connection", use_container_width=True, key="pro_btn"):
                if MASTER_API_KEY:
                    with st.spinner("Connecting to Master Engine..."):
                        try:
                            client = genai.Client(api_key=MASTER_API_KEY)
                            response = client.models.generate_content(
                                model="gemini-3.5-flash", 
                                contents="Say hello in 3 words."
                            )
                            st.success("✓ Master AI active! Click on Connect YouTube below.")
                        except Exception as e:
                            st.error(f"Master system error: {str(e)}")
                else:
                    st.error("Master API key missing in environment/secrets.")
        
            pro_auth_url = None
            if MASTER_CLIENT_ID and MASTER_CLIENT_SECRET:
                try:
                    client_config = {
                        "web": {
                            "client_id": MASTER_CLIENT_ID,
                            "client_secret": MASTER_CLIENT_SECRET,
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        }
                    }
                    flow = Flow.from_client_config(
                        client_config,
                        scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
                        redirect_uri=APP_URL
                    )
                    
                    pro_auth_url, state_token = flow.authorization_url(
                        prompt='consent', 
                        access_type='offline',
                        include_granted_scopes='true'
                    )
                    
                    save_verifier(state_token, flow.code_verifier)
                    
                except Exception:
                    pass

            if pro_auth_url:
                pro_auth_link = f'<a href="{pro_auth_url}" target="_blank" class="auth-btn"><span style="color: #34C759; margin-right: 6px; font-size: 16px;">●</span>Connect YouTube <span style="font-size: 10px; background: #E5E5EA; padding: 2px 4px; border-radius: 4px;">BETA</span></a>'
            else:
                pro_auth_link = f'<a href="#" target="_blank" class="auth-btn disabled-btn"><span style="color: #888888; margin-right: 6px; font-size: 16px;">●</span>Connect YouTube <span style="font-size: 10px; background: #E5E5EA; padding: 2px 4px; border-radius: 4px;">BETA</span></a>'

            st.markdown(f'''
            <div style="margin-top: 16px; display: flex; flex-direction: column; gap: 8px;">
                {pro_auth_link}
                <a href="#" target="_blank" class="auth-btn disabled-btn"><span style="color: #888888; margin-right: 6px; font-size: 16px;">●</span>Connect YouTube <span style="font-size: 10px; background: #E5E5EA; padding: 2px 4px; border-radius: 4px;">BETA</span></a>
            </div>
            ''', unsafe_allow_html=True)
                    
    with c3:
        with st.container(border=True):
            st.subheader("Talent Manager")
            st.markdown("""
            * ✓ Connect multiple creator accounts
            * ✓ Centralized engagement dashboard
            * ✓ Handle cross-platform DMs & mentions
            * ✓ Advanced analytics & team permissions
            """)
            
            st.markdown('''
            <div style="margin-top: 16px;">
                <a href="#" target="_blank" class="auth-btn disabled-btn">Initialize Agency Engine <span style="font-size: 10px; background: #E5E5EA; padding: 2px 4px; border-radius: 4px;">BETA</span></a>
            </div>
            ''', unsafe_allow_html=True)
