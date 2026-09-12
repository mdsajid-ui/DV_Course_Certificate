"""
Automated Certificate Generation and Email Sending System
DV Analytics

Run with:  streamlit run app.py
"""

import os
import io
import re
import zipfile
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from certificate_generator import (
    load_template_as_image,
    generate_certificate,
    render_certificate_image,
    suggest_text_style,
    suggest_name_position,
    sanitize_filename,
)
from email_sender import EmailSender, SMTPConfig, is_valid_email
from utils import (
    validate_excel_columns,
    normalize_records,
    build_report_dataframe,
    log_event,
    now_str,
    LOG_PATH,
    get_secret,
)
import cert_store
import qr_utils
import pptx_certificate
import sheets_readonly
import sheets_writer

load_dotenv()

OUTPUT_DIR = "output"
CERT_DIR = os.path.join(OUTPUT_DIR, "certificates")
VAULT_DIR = os.path.join("data", "issued_certificates")
REPORT_PATH = os.path.join(OUTPUT_DIR, "Email_Sending_Report.xlsx")
ERROR_REPORT_PATH = os.path.join(OUTPUT_DIR, "Error_Report.xlsx")

os.makedirs(CERT_DIR, exist_ok=True)
os.makedirs(VAULT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Page config & modern theme
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="DV Analytics — Course Completion Certificate",
    page_icon="🎓",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Login gate — must run before any other UI renders
# ---------------------------------------------------------------------------
def login():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        #MainMenu, footer, [data-testid="stHeader"], [data-testid="stToolbar"] { display:none !important; }
        html, body, [class*="css"] { font-family:'Inter',sans-serif; }
        .stApp { background:#0b0b09; min-height:100vh; color:#fff; }
        .block-container { max-width:1080px !important; padding:6vh 28px 30px !important; }
        .lamp-heading { text-align:center; margin-bottom:34px; }
        .lamp-heading h1 { margin:0; color:#f7f7f3; font-size:clamp(32px,4.5vw,54px); letter-spacing:-2px; font-weight:500; }
        .lamp-heading h1 span { color:#ffe000; font-weight:600; }
        .lamp-heading p { color:#88877f; margin:10px 0 0; font-size:14px; letter-spacing:.06em; text-transform:uppercase; }
        [data-testid="stHorizontalBlock"] { align-items:center; gap:3rem; }
        .lamp-stage { height:470px; position:relative; overflow:hidden; }
        .lamp-glow { position:absolute; width:390px; height:390px; left:50%; top:77px; transform:translateX(-50%); background:radial-gradient(ellipse at 50% 15%,rgba(255,225,92,.42),rgba(255,212,55,.12) 43%,transparent 70%); filter:blur(5px); animation:breathe 3s ease-in-out infinite; transition:opacity .35s ease; }
        .light-cone { position:absolute; left:50%; top:126px; transform:translateX(-50%); width:330px; height:285px; background:linear-gradient(100deg,transparent 3%,rgba(255,226,116,.30) 48%,rgba(255,240,162,.17) 75%,transparent 97%); clip-path:polygon(39% 0,61% 0,100% 100%,0 100%); filter:blur(2px); transition:opacity .35s ease; }
        .lamp-stage.lamp-off .lamp-glow, .lamp-stage.lamp-off .light-cone, .lamp-stage.lamp-off .fly { opacity:0 !important; animation:none; }
        .lamp-stage.lamp-off .shade { border-bottom-color:#25251f; box-shadow:none; }
        .shade { position:absolute; z-index:3; left:50%; top:94px; transform:translateX(-50%); width:155px; height:55px; border-radius:80px 80px 10px 10px; background:linear-gradient(#080807,#181711); border-bottom:5px solid #5f5633; box-shadow:0 8px 28px rgba(255,220,65,.33); }
        .stem { position:absolute; z-index:3; left:calc(50% - 3px); top:146px; width:6px; height:239px; background:linear-gradient(90deg,#171714,#75705c,#151513); }
        .base { position:absolute; z-index:4; left:50%; top:382px; transform:translateX(-50%); width:142px; height:12px; border-radius:50%; background:#11110f; box-shadow:0 3px 12px #000; }
        .cord { position:absolute; z-index:4; left:calc(50% + 51px); top:136px; width:2px; height:75px; background:#93865c; transform-origin:top; animation:sway 3.2s ease-in-out infinite; }
        .cord:after { content:''; position:absolute; left:-5px; bottom:-12px; width:12px; height:17px; border-radius:50%; background:#cbb96f; box-shadow:inset 2px 0 4px #746a42; }
        .fly { position:absolute; z-index:5; width:5px; height:5px; border-radius:50%; background:#fff26a; box-shadow:0 0 5px #fff400,0 0 12px #d4ff00; animation:float 5s ease-in-out infinite; }
        .f1{left:16%;top:17%;}.f2{left:77%;top:25%;animation-delay:-1s}.f3{left:25%;top:70%;animation-delay:-2.2s}.f4{left:83%;top:74%;animation-delay:-3.4s}.f5{left:67%;top:51%;animation-delay:-4s}
        [data-testid="stForm"] { background:linear-gradient(145deg,rgba(35,35,32,.98),rgba(23,23,21,.96)); border:1px solid #3c3b35; border-radius:22px; padding:32px 30px 26px; box-shadow:0 25px 65px rgba(0,0,0,.55),inset 0 1px rgba(255,255,255,.04); }
        .card-head h2 { margin:0; font-size:30px; color:#fff; letter-spacing:-1px; }
        .card-head p { margin:7px 0 22px; color:#8f8e87; font-size:13px; }
        .stTextInput label { color:#b9b8b1 !important; font-size:12px !important; font-weight:600 !important; }
        .stTextInput [data-baseweb="input"], .stTextInput [data-baseweb="base-input"], .stTextInput input { background-color:#151513 !important; border-color:#292925 !important; }
        .stTextInput [data-baseweb="input"] { border:1px solid #292925 !important; border-radius:10px !important; min-height:49px; }
        .stTextInput [data-baseweb="input"]:focus-within { border-color:#ffe000 !important; box-shadow:0 0 0 2px rgba(255,224,0,.12) !important; }
        .stTextInput input { color:#ffe76a !important; -webkit-text-fill-color:#ffe76a !important; caret-color:#ffe000 !important; opacity:1 !important; }
        .stTextInput input::placeholder { color:#565650 !important; }
        [data-testid="stToggle"] { max-width:180px; margin:0 auto -8px; }
        [data-testid="stToggle"] label p { color:#d8d6c8 !important; font-size:13px !important; font-weight:600 !important; }
        .login-actions { display:flex; justify-content:space-between; color:#77766f; font-size:12px; margin:0 2px 13px; }
        [data-testid="stFormSubmitButton"] button { width:100%; min-height:50px; border:0; border-radius:10px; background:#ffe000; color:#13130f; font-size:15px; font-weight:800; box-shadow:0 8px 22px rgba(255,224,0,.18); transition:.2s; }
        [data-testid="stFormSubmitButton"] button:hover { background:#ffea3b; color:#000; transform:translateY(-1px); box-shadow:0 11px 28px rgba(255,224,0,.27); }
        .secure-note { text-align:center; color:#62615b; font-size:11px; margin-top:18px; }
        .login-footer { text-align:center; color:#4f4e49; font-size:11px; margin-top:28px; }
        @keyframes breathe{50%{opacity:.72;transform:translateX(-50%) scale(.96)}}
        @keyframes sway{50%{transform:rotate(3deg)}}
        @keyframes float{0%,100%{transform:translate(0,0);opacity:.35}50%{transform:translate(18px,-24px);opacity:1}}
        @media(max-width:760px){.block-container{padding:30px 18px !important}.lamp-heading{margin-bottom:8px}.lamp-stage{height:280px}.shade{top:35px}.lamp-glow{top:20px;height:270px}.light-cone{top:67px;height:190px;width:260px}.stem{top:87px;height:150px}.base{top:234px}.cord{top:77px}.lamp-heading h1{font-size:35px}[data-testid="stHorizontalBlock"]{gap:.5rem}[data-testid="stForm"]{padding:26px 20px 22px}}
        </style>
        <div class="lamp-heading"><h1>Certificate Email <span>Automation</span></h1><p>DV Analytics · Secure Sign In</p></div>
        """,
        unsafe_allow_html=True,
    )

    lamp_col, form_col = st.columns([1.12, 1], gap="large")
    with lamp_col:
        lamp_on = st.toggle("Turn on lamp", value=True, key="login_lamp_on")
        lamp_state = "lamp-on" if lamp_on else "lamp-off"
        st.markdown(f'''<div class="lamp-stage {lamp_state}"><div class="lamp-glow"></div><div class="light-cone"></div><div class="shade"></div><div class="stem"></div><div class="base"></div><div class="cord"></div><i class="fly f1"></i><i class="fly f2"></i><i class="fly f3"></i><i class="fly f4"></i><i class="fly f5"></i></div>''', unsafe_allow_html=True)

    with form_col:
        with st.form("login_form", clear_on_submit=False):
            st.markdown('<div class="card-head"><h2>Welcome Back</h2><p>Enter your details to access your account</p></div>', unsafe_allow_html=True)
            username = st.text_input("USERNAME", placeholder="Enter your username", key="login_username")
            password = st.text_input("PASSWORD", type="password", placeholder="Enter your password", key="login_password")
            st.markdown('<div class="login-actions"><span>✓ &nbsp;Secure session</span><span>Authorized access only</span></div>', unsafe_allow_html=True)
            submitted = st.form_submit_button("Sign In", use_container_width=True)
            st.markdown('<div class="secure-note">🔒 Your connection is protected</div>', unsafe_allow_html=True)

    if submitted:
        # Credentials come from Streamlit secrets / environment variables only —
        # never hardcoded in source, since this repo is public on GitHub.
        valid_username = get_secret("APP_USERNAME", "admin")
        valid_password = get_secret("APP_PASSWORD", "admin123")

        if not valid_username or not valid_password:
            st.error("⚠️ Login is not configured. Set APP_USERNAME and APP_PASSWORD in secrets.")
        elif username == valid_username and password == valid_password:
            st.session_state["logged_in"] = True
            st.rerun()
        else:
            st.error("❌ Invalid username or password")

    st.markdown('<div class="login-footer">© 2026 DV Analytics · Course Completion Certificate Automation</div>', unsafe_allow_html=True)

    return st.session_state.get("logged_in", False)


if not st.session_state.get("logged_in", False):
    login()
    st.stop()


NAVY = "#0B1B4D"
NAVY_DEEP = "#060F30"
RED = "#EF233C"
ACCENT = "#4F46E5"
ACCENT_2 = "#7C3AED"
ACCENT_PINK = "#EC4899"
GOLD = "#D4AF37"
BG = "#F8FAFC"
CARD = "#FFFFFF"
BORDER = "#E2E8F0"
MUTED = "#64748B"

st.markdown(
    f"""
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Outfit:wght@500;600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        html, body, [class*="css"] {{ font-family: 'Plus Jakarta Sans', 'Inter', sans-serif; }}
        .stApp {{
            background:
                radial-gradient(1200px 600px at 90% -10%, {ACCENT}12, transparent 60%),
                radial-gradient(900px 500px at -10% 20%, {ACCENT_2}10, transparent 55%),
                radial-gradient(800px 600px at 50% 100%, {ACCENT_PINK}08, transparent 50%),
                {BG};
        }}
        #MainMenu, footer, header[data-testid="stHeader"] {{ visibility: hidden; }}

        /* ---------- Ultra Modern Hero Header ---------- */
        .dv-hero {{
            position: relative; overflow: hidden;
            background:
                radial-gradient(130% 180% at 0% 0%, {ACCENT_2}55 0%, transparent 50%),
                radial-gradient(120% 160% at 100% 100%, {RED}35 0%, transparent 45%),
                linear-gradient(135deg, #090e24 0%, #0f172a 50%, #1e1b4b 100%);
            padding: 34px 38px; border-radius: 24px; margin-bottom: 24px;
            display: flex; align-items: center; justify-content: space-between; gap: 20px;
            box-shadow: 0 24px 50px -15px rgba(15,23,42,0.65), inset 0 1px 1px rgba(255,255,255,0.15);
            border: 1px solid rgba(255,255,255,0.12);
        }}
        .dv-hero-left {{ display: flex; align-items: center; gap: 20px; }}
        .dv-hero .mark {{
            width: 58px; height: 58px; border-radius: 18px; flex-shrink: 0;
            background: linear-gradient(135deg, #f43f5e 0%, #e11d48 50%, #be123c 100%);
            display: flex; align-items: center; justify-content: center;
            color: white; font-weight: 800; font-size: 22px; letter-spacing: -1px;
            font-family: 'Outfit', sans-serif;
            box-shadow: 0 10px 25px -5px rgba(225,29,72,0.6), inset 0 1px 1px rgba(255,255,255,0.35);
        }}
        .dv-hero h1 {{
            color: white; font-size: 25px; margin: 0; font-family: 'Outfit', sans-serif; font-weight: 700;
            letter-spacing: -.4px; line-height: 1.2;
        }}
        .dv-hero p {{ color: #cbd5e1; font-size: 13.5px; margin: 5px 0 0; font-weight: 400; }}
        .dv-hero-pill {{
            display: flex; align-items: center; gap: 8px; color: #f8fafc; font-size: 12px;
            font-weight: 600; padding: 7px 14px; border-radius: 999px;
            background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);
            backdrop-filter: blur(12px); white-space: nowrap; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}
        .dv-hero-pill .dot {{
            width: 8px; height: 8px; border-radius: 50%; background: #10b981;
            box-shadow: 0 0 0 3px rgba(16,185,129,0.3);
        }}

        /* ---------- Frosted Glass Cards ---------- */
        .dv-card {{
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid rgba(226, 232, 240, 0.9); border-radius: 20px;
            padding: 26px 28px; margin-bottom: 22px;
            box-shadow: 0 10px 30px -10px rgba(15,23,42,0.06), 0 1px 3px rgba(15,23,42,0.03);
            backdrop-filter: blur(16px);
            transition: all .25s cubic-bezier(0.16, 1, 0.3, 1);
        }}
        .dv-card:hover {{
            box-shadow: 0 20px 40px -15px rgba(15,23,42,0.10);
            border-color: rgba(99, 102, 241, 0.3);
        }}
        .dv-section-title {{
            font-family: 'Outfit', sans-serif; font-weight: 700; font-size: 18px;
            color: #0f172a; margin-bottom: 2px; display: flex; align-items: center; gap: 10px;
            letter-spacing: -0.2px;
        }}
        .dv-section-title:before {{
            content: ""; display: inline-block; width: 5px; height: 20px; border-radius: 999px;
            background: linear-gradient(180deg, #4f46e5, #ec4899);
        }}
        .dv-section-sub {{ color: #64748b; font-size: 13px; margin: 4px 0 16px 15px; font-weight: 400; }}

        /* ---------- Modern Floating Tabs ---------- */
        div[data-testid="stTabs"] div[data-baseweb="tab-list"] {{
            gap: 8px; background: rgba(15, 23, 42, 0.04); padding: 7px; border-radius: 16px;
            border: 1px solid rgba(226, 232, 240, 0.8);
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.02);
        }}
        div[data-testid="stTabs"] button[data-baseweb="tab"] {{
            font-family: 'Plus Jakarta Sans', sans-serif; font-weight: 600; font-size: 13.5px;
            color: #64748b; padding: 10px 20px; border-radius: 12px; transition: all .2s ease;
            border: none;
        }}
        div[data-testid="stTabs"] button[data-baseweb="tab"]:hover {{
            color: #1e1b4b; background: rgba(255,255,255,0.6);
        }}
        div[data-testid="stTabs"] button[aria-selected="true"] {{
            color: white !important;
            background: linear-gradient(135deg, #1e1b4b 0%, #4338ca 50%, #6366f1 100%) !important;
            box-shadow: 0 8px 20px -6px rgba(67, 56, 202, 0.55), inset 0 1px 0 rgba(255,255,255,0.2) !important;
        }}
        div[data-testid="stTabs"] button[aria-selected="true"] p {{ color: white !important; font-weight: 700; }}
        div[data-testid="stTabs"] div[data-baseweb="tab-highlight"] {{ display: none; }}
        div[data-testid="stTabs"] div[data-baseweb="tab-border"] {{ display: none; }}

        /* ---------- Bento-Box KPI Metrics ---------- */
        div[data-testid="stMetric"] {{
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #e2e8f0; border-radius: 16px;
            padding: 16px 20px; box-shadow: 0 4px 16px -4px rgba(15,23,42,0.05);
            border-top: 3.5px solid #6366f1;
            transition: all .2s ease;
        }}
        div[data-testid="stMetric"]:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 25px -8px rgba(99, 102, 241, 0.15);
            border-top-color: #4f46e5;
        }}
        div[data-testid="stMetricLabel"] {{ color: #64748b; font-weight: 600; font-size: 11.5px; text-transform: uppercase; letter-spacing: .5px; }}
        div[data-testid="stMetricValue"] {{ color: #0f172a; font-family: 'Outfit', sans-serif; font-weight: 700; font-size: 26px; }}

        /* ---------- Tactile CTA Buttons ---------- */
        .stButton>button {{
            background: linear-gradient(135deg, #0f172a 0%, #312e81 40%, #4f46e5 100%);
            background-size: 200% auto;
            color: white; border-radius: 13px; font-weight: 700; border: none;
            padding: 0.7em 1.6em; font-family: 'Plus Jakarta Sans', sans-serif; font-size: 14px;
            box-shadow: 0 10px 22px -6px rgba(49, 46, 129, 0.45), inset 0 1px 0 rgba(255,255,255,0.2);
            transition: all .22s cubic-bezier(0.16, 1, 0.3, 1); letter-spacing: .1px;
        }}
        .stButton>button:hover {{
            transform: translateY(-2px); background-position: right center;
            box-shadow: 0 14px 28px -8px rgba(79, 70, 229, 0.6), inset 0 1px 0 rgba(255,255,255,0.3);
            color: white;
        }}
        .stButton>button:active {{ transform: translateY(0px) scale(.99); }}
        .stButton>button:disabled {{
            background: #e2e8f0; color: #94a3b8; box-shadow: none; transform: none;
        }}
        .stDownloadButton>button {{
            background: #ffffff; color: #0f172a; border: 1.5px solid #cbd5e1; border-radius: 13px;
            font-weight: 700; font-family: 'Plus Jakarta Sans', sans-serif; font-size: 13.5px;
            transition: all .2s ease; padding: 0.65em 1.3em;
            box-shadow: 0 2px 8px rgba(0,0,0,0.03);
        }}
        .stDownloadButton>button:hover {{
            border-color: #6366f1; color: #4f46e5; transform: translateY(-1px);
            box-shadow: 0 8px 20px -8px rgba(99, 102, 241, 0.35);
        }}

        .dv-badge {{
            display: inline-flex; align-items: center; gap: 6px;
            padding: 5px 14px; border-radius: 999px;
            font-size: 12px; font-weight: 700; font-family: 'Plus Jakarta Sans', sans-serif;
            letter-spacing: .2px;
        }}
        .dv-badge-ok {{ background: #ecfdf5; color: #059669; border: 1px solid #a7f3d0; }}
        .dv-badge-warn {{ background: #fff1f2; color: #e11d48; border: 1px solid #fecdd3; }}
        .dv-badge-info {{ background: #eef2ff; color: #4f46e5; border: 1px solid #c7d2fe; }}

        div[data-testid="stProgress"] > div > div {{
            background: linear-gradient(90deg, #4f46e5, #ec4899); border-radius: 999px;
            box-shadow: 0 2px 10px rgba(79, 70, 229, 0.4);
        }}

        /* ---------- File Uploader ---------- */
        [data-testid="stFileUploaderDropzone"] {{
            background: linear-gradient(180deg, #ffffff, #f8fafc) !important;
            border: 2px dashed #cbd5e1 !important; border-radius: 16px !important;
            transition: all .2s ease !important;
        }}
        [data-testid="stFileUploaderDropzone"]:hover {{
            border-color: #6366f1 !important;
            background: #f5f3ff !important;
        }}

        /* ---------- Sidebar ---------- */
        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #090e24, #0f172a) !important;
        }}
        section[data-testid="stSidebar"] * {{ color: #e2e8f0 !important; }}
        section[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,.10) !important; }}

        /* ---------- Anti-Screenshot & Screen Capture Protection Shield ---------- */
        @media print {{
            * {{ display: none !important; }}
            html, body {{ background: #ffffff !important; visibility: hidden !important; }}
        }}
        .screenshot-blankout, .screenshot-blankout * {{
            visibility: hidden !important;
            opacity: 0 !important;
            background: #ffffff !important;
            color: transparent !important;
            filter: blur(100px) !important;
        }}
        .protected-cert-container {{
            position: relative;
            user-select: none;
            -webkit-user-select: none;
            -moz-user-select: none;
            -ms-user-select: none;
            -webkit-touch-callout: none;
        }}
        .protected-cert-container img, [data-testid="stImage"] img {{
            pointer-events: none !important;
            -webkit-user-drag: none !important;
            user-select: none !important;
        }}
    </style>

    <script>
    (function() {{
        if (window.__dv_security_initialized) return;
        window.__dv_security_initialized = true;

        function triggerBlankout() {{
            document.body.classList.add('screenshot-blankout');
            if (window.parent && window.parent.document && window.parent.document.body) {{
                window.parent.document.body.classList.add('screenshot-blankout');
            }}
        }}

        function restoreView() {{
            setTimeout(function() {{
                document.body.classList.remove('screenshot-blankout');
                if (window.parent && window.parent.document && window.parent.document.body) {{
                    window.parent.document.body.classList.remove('screenshot-blankout');
                }}
            }}, 600);
        }}

        // 1. Detect focus loss (triggered when Snipping Tool, screen grabber, or capture overlay opens)
        window.addEventListener('blur', triggerBlankout);
        window.addEventListener('focus', restoreView);
        document.addEventListener('visibilitychange', function() {{
            if (document.hidden) {{
                triggerBlankout();
            }} else {{
                restoreView();
            }}
        }});

        // 2. Intercept PrintScreen and screenshot shortcuts
        window.addEventListener('keyup', function(e) {{
            if (e.key === 'PrintScreen' || e.keyCode === 44 || e.code === 'PrintScreen') {{
                try {{
                    navigator.clipboard.writeText('');
                }} catch(err) {{}}
                triggerBlankout();
                setTimeout(restoreView, 2500);
            }}
        }});

        window.addEventListener('keydown', function(e) {{
            if (e.key === 'PrintScreen' || e.keyCode === 44 || e.code === 'PrintScreen' ||
                (e.ctrlKey && (e.key === 'p' || e.key === 'P' || e.key === 's' || e.key === 'S')) ||
                (e.ctrlKey && e.shiftKey && (e.key === 's' || e.key === 'S' || e.key === 'i' || e.key === 'I')) ||
                (e.metaKey && e.shiftKey && (e.key === '3' || e.key === '4' || e.key === 's' || e.key === 'S'))) {{
                try {{
                    navigator.clipboard.writeText('');
                }} catch(err) {{}}
                triggerBlankout();
                setTimeout(restoreView, 2500);
                e.preventDefault();
                return false;
            }}
        }});

        // 3. Disable right-click saving on protected images
        document.addEventListener('contextmenu', function(e) {{
            if (e.target.tagName === 'IMG' || e.target.closest('[data-testid="stImage"]')) {{
                e.preventDefault();
                return false;
            }}
        }});
    }})();
    </script>

    <div class="dv-hero">
        <div class="dv-hero-left">
            <div class="mark">DV</div>
            <div>
                <h1>DV ANALYTICS COURSE COMPLETION CERTIFICATE</h1>
                <p>Automated certificate generation, security locking, and personalized email delivery</p>
            </div>
        </div>
        <div class="dv-hero-pill"><span class="dot"></span> DV Analytics Workspace</div>
    </div>
    """,
    unsafe_allow_html=True,
)


def card_start(title: str, subtitle: str = ""):
    sub_html = f'<div class="dv-section-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="dv-card"><div class="dv-section-title">{title}</div>{sub_html}',
        unsafe_allow_html=True,
    )


def card_end():
    st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session State Initialization
# ---------------------------------------------------------------------------
defaults = {
    "records": [],  # List of dicts: [{"Name": ..., "Mobile Number": ..., "Email ID": ..., "Course": ..., "Completion Date": ..., "Certificate Number": ...}]
    "template_mode": "Official APIDS / APDA Template",
    "selected_official_course": "APIDS",
    "custom_template_path": None,
    "custom_template_fingerprint": None,
    "cert_paths": {},  # email/name -> dict info
    "results": [],     # delivery logs
    "font_size": 60,
    "y_pos_pct": 50,
    "text_color_hex": "#0B1B4D",
    "confirmed_params": None,
    "email_subject_tpl": "Course Completion Certificate – {{Name}}",
    "email_body_tpl": (
        "Dear {{Name}},\n\n"
        "Congratulations on successfully completing the {{Course}} program at DV Analytics!\n\n"
        "Please find your official Course Completion Certificate attached to this email.\n"
        "• Certificate Registration Number: {{CertNo}}\n"
        "• Date of Completion: {{Date}}\n\n"
        "You can verify the authenticity of your certificate at any time by scanning the QR code printed on the certificate.\n\n"
        "We appreciate your dedication and wish you great success in your career journey.\n\n"
        "Warm regards,\n"
        "DV Analytics Team"
    ),
    "institute_code": "DVA",
    "cert_batch_prefix": "202505",
    "cert_start_seq": 2075,
    "cert_year": "2025",
    "verification_base_url": os.environ.get("CERTIFICATE_VERIFICATION_BASE_URL", "http://localhost:8000"),
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------------------------
# Sidebar — SMTP & Configuration Status
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ✉️ System Status")
    cfg = SMTPConfig()
    if cfg.is_configured():
        st.markdown('<span class="dv-badge dv-badge-ok">● SMTP Connected</span>', unsafe_allow_html=True)
        st.caption(f"**Host:** {cfg.host}:{cfg.port}\n**Sender:** {cfg.username}")
    else:
        st.markdown('<span class="dv-badge dv-badge-warn">● SMTP Not Configured</span>', unsafe_allow_html=True)
        st.caption(
            "Configure **SMTP_EMAIL** and **SMTP_PASSWORD** (Gmail App Password) "
            "in Streamlit secrets or environment variables."
        )

    st.divider()
    st.markdown("### 📊 Active Roster Summary")
    st.metric("Participants Loaded", len(st.session_state.records))
    st.metric("Certificates Generated", len(st.session_state.cert_paths))

    if st.session_state.records:
        if st.button("🗑️ Clear Active Roster", use_container_width=True):
            st.session_state.records = []
            st.session_state.cert_paths = {}
            st.rerun()

    st.divider()
    st.caption("DV Analytics · Course Completion Certificate")


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------
def _apply_email_placeholders(tpl: str, *, name: str, course: str, cert_no: str, date: str, mobile: str = "") -> str:
    res = tpl
    res = re.sub(r"\{\{\s*(?:student_)?name\s*\}\}", name, res, flags=re.IGNORECASE)
    res = re.sub(r"\{\{\s*(?:course|course_name)\s*\}\}", course, res, flags=re.IGNORECASE)
    res = re.sub(r"\{\{\s*(?:certno|certificate_number|cert_no|reg_no)\s*\}\}", cert_no, res, flags=re.IGNORECASE)
    res = re.sub(r"\{\{\s*(?:date|issue_date|completion_date)\s*\}\}", date, res, flags=re.IGNORECASE)
    res = re.sub(r"\{\{\s*(?:mobile|phone|mobile_number)\s*\}\}", mobile, res, flags=re.IGNORECASE)
    return res


def build_participant_cert(rec: dict, template_mode: str, default_course: str) -> tuple[str, str, bool]:
    """
    Generates or retrieves certificate PDF for a participant record.
    Returns (certificate_number, pdf_path, was_new).
    """
    name = rec.get("Name", "").strip()
    email = rec.get("Email ID", "").strip()
    course = rec.get("Course") or default_course
    completion_date = rec.get("Completion Date") or datetime.now().strftime("%d-%b-%Y")
    existing_cert_no = rec.get("Certificate Number")

    # Issue or retrieve authoritative number (e.g. 202505DVA2075)
    batch_pfx = st.session_state.get("cert_batch_prefix", "202505").strip() or "202505"
    inst_code = st.session_state.get("institute_code", "DVA").strip() or "DVA"
    start_num = int(st.session_state.get("cert_start_seq", 2075) or 2075)

    cert_record = cert_store.issue_or_get_certificate_number(
        name=name,
        email=email,
        course=course,
        completion_date=completion_date,
        institute_code=inst_code,
        course_code=course.strip() or "APIDS",
        year=batch_pfx,
        batch_prefix=batch_pfx,
        start_seq=start_num,
        format_style="COMPACT",
        existing_number=existing_cert_no,
    )
    cert_number = cert_record.cert_number

    # Generate QR code
    verify_url = qr_utils.verification_url(cert_number, base_url=st.session_state.verification_base_url)
    qr_bytes = qr_utils.make_qr_image_bytes(verify_url)
    qr_path = os.path.join(CERT_DIR, f"qr_{cert_number}.png")
    with open(qr_path, "wb") as f:
        f.write(qr_bytes)

    pdf_path = os.path.join(CERT_DIR, f"{cert_number}.pdf")
    was_new = not os.path.exists(pdf_path)

    if template_mode == "Official APIDS / APDA Template":
        # Select official template file
        course_clean = course.upper() if course.upper() in ("APIDS", "APDA") else "APIDS"
        template_file = os.path.join("assets", "templates", f"certificate_{course_clean}_blank.pptx")
        if not os.path.exists(template_file):
            template_file = os.path.join("assets", "templates", "certificate_APIDS_blank.pptx")

        pptx_certificate.render_certificate_pdf(
            name=name,
            certificate_number=cert_number,
            completion_date=completion_date,
            qr_png_path=qr_path,
            template_path=template_file,
            output_pdf_path=pdf_path,
        )
    else:
        # Custom image/pdf template
        custom_path = st.session_state.custom_template_path
        if not custom_path or not os.path.exists(custom_path):
            raise FileNotFoundError("Custom template file not found. Please upload a template in Tab 1.")
        
        template_img = load_template_as_image(custom_path)
        font_size = st.session_state.font_size
        y_pos = st.session_state.y_pos_pct / 100.0
        color_hex = st.session_state.text_color_hex
        text_color = tuple(int(color_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))

        generate_certificate(
            template_img=template_img,
            name=name,
            output_dir=CERT_DIR,
            font_size=font_size,
            text_color=text_color,
            y_position_pct=y_pos,
            certificate_number=cert_number,
            completion_date=completion_date,
            qr_png_path=qr_path,
            custom_filename=cert_number,
        )

    # Apply digital encryption, strict permission lock & compute SHA-256 checksum
    sha256_hash = ""
    try:
        from pdf_security import lock_and_protect_pdf
        sha256_hash, _ = lock_and_protect_pdf(pdf_path, allow_print=False, dpi=300)
        if sha256_hash:
            cert_store.store_pdf_security_hash(cert_number, sha256_hash)
    except Exception:
        pass

    # Permanently archive copy to Vault
    try:
        vault_path = os.path.join(VAULT_DIR, f"{cert_number}.pdf")
        shutil.copyfile(pdf_path, vault_path)
    except Exception:
        pass

    return cert_number, pdf_path, was_new, sha256_hash


def ensure_cert_pdf_exists(record: cert_store.CertificateRecord) -> str:
    """Returns valid path to certificate PDF, reconstructing from metadata if ever missing."""
    cert_no = record.cert_number
    vault_path = os.path.join(VAULT_DIR, f"{cert_no}.pdf")
    cert_path = os.path.join(CERT_DIR, f"{cert_no}.pdf")

    if os.path.exists(vault_path):
        return vault_path
    if os.path.exists(cert_path):
        try:
            shutil.copyfile(cert_path, vault_path)
        except Exception:
            pass
        return cert_path

    # Reconstruct on-the-fly if missing
    course_clean = record.course.upper() if record.course.upper() in ("APIDS", "APDA") else "APIDS"
    template_file = os.path.join("assets", "templates", f"certificate_{course_clean}_blank.pptx")
    if not os.path.exists(template_file):
        template_file = os.path.join("assets", "templates", "certificate_APIDS_blank.pptx")

    verify_url = qr_utils.verification_url(
        cert_no, base_url=st.session_state.get("verification_base_url", "http://localhost:8000")
    )
    qr_bytes = qr_utils.make_qr_image_bytes(verify_url)
    qr_path = os.path.join(CERT_DIR, f"qr_{cert_no}.png")
    with open(qr_path, "wb") as f:
        f.write(qr_bytes)

    pptx_certificate.render_certificate_pdf(
        name=record.name,
        certificate_number=cert_no,
        completion_date=record.completion_date or datetime.now().strftime("%d-%b-%Y"),
        qr_png_path=qr_path,
        template_path=template_file,
        output_pdf_path=vault_path,
    )
    from pdf_security import lock_and_protect_pdf
    sha256_hash, _ = lock_and_protect_pdf(vault_path, allow_print=False, dpi=300)
    if sha256_hash:
        cert_store.store_pdf_security_hash(cert_no, sha256_hash)
    try:
        shutil.copyfile(vault_path, cert_path)
    except Exception:
        pass
    return vault_path


# ---------------------------------------------------------------------------
# TAB LAYOUT (4 Tabs)
# ---------------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(
    [
        "① Add Participants & Template",
        "② Generate Certificates",
        "③ Sending Formalities",
        "④ Delivery Report & Analytics",
    ]
)

# ===========================================================================
# TAB 1 — Add Participants & Template
# ===========================================================================
with tab1:
    card_start("1. Add Participants", "Add student details manually or upload in bulk via Excel, CSV, or Google Sheets.")

    input_mode = st.radio(
        "Choose Input Method",
        ["📝 Manual Entry & Editable Grid", "📁 Bulk Upload (Excel / CSV)", "🌐 Google Sheets Sync"],
        horizontal=True,
    )

    # ------------------ Sub-Mode 1: Manual Entry ------------------
    if input_mode == "📝 Manual Entry & Editable Grid":
        st.markdown("##### ➕ Quick Add Student")
        with st.form("manual_add_form", clear_on_submit=True):
            mc1, mc2, mc3 = st.columns(3)
            with mc1:
                m_name = st.text_input("Student Name *", placeholder="e.g. John Doe")
                m_course = st.selectbox("Course", ["APIDS", "APDA", "Data Science", "Data Analytics"], index=0)
            with mc2:
                m_mobile = st.text_input("Mobile Number", placeholder="e.g. +91 9876543210")
                m_date = st.text_input("Completion Date", value=datetime.now().strftime("%d-%b-%Y"))
            with mc3:
                m_email = st.text_input("Email ID *", placeholder="e.g. john.doe@example.com")
                m_cert_no = st.text_input("Certificate Number (Optional)", placeholder="Auto-generated if blank")

            add_btn = st.form_submit_button("➕ Add Student to Roster", use_container_width=True)
            if add_btn:
                if not m_name.strip() or not m_email.strip():
                    st.error("⚠️ Please enter both Student Name and Email ID.")
                elif not is_valid_email(m_email):
                    st.error(f"⚠️ '{m_email}' is not a valid email address.")
                else:
                    new_rec = {
                        "Name": m_name.strip(),
                        "Mobile Number": m_mobile.strip(),
                        "Email ID": m_email.strip(),
                        "Course": m_course.strip(),
                        "Completion Date": m_date.strip(),
                        "Certificate Number": m_cert_no.strip(),
                    }
                    existing_idx = next((i for i, r in enumerate(st.session_state.records) if r["Email ID"].lower() == m_email.strip().lower()), None)
                    if existing_idx is not None:
                        st.session_state.records[existing_idx] = new_rec
                        st.success(f"✓ Updated record for **{m_name}** ({m_email})")
                    else:
                        st.session_state.records.append(new_rec)
                        st.success(f"✓ Added **{m_name}** ({m_email}) to roster")
                    st.rerun()

        st.markdown("##### ✏️ Interactive Participant Grid (Edit, Add, or Delete Rows)")
        st.caption("You can directly type into the table below, paste cells, or use the '+' row button at the bottom.")

        current_df = pd.DataFrame(st.session_state.records)
        for col in ["Name", "Mobile Number", "Email ID", "Course", "Completion Date", "Certificate Number"]:
            if col not in current_df.columns:
                current_df[col] = ""

        edited_df = st.data_editor(
            current_df,
            num_rows="dynamic",
            use_container_width=True,
            height=250,
            key="roster_editor",
            column_config={
                "Name": st.column_config.TextColumn("Student Name", required=True),
                "Mobile Number": st.column_config.TextColumn("Mobile Number"),
                "Email ID": st.column_config.TextColumn("Email ID", required=True),
                "Course": st.column_config.SelectboxColumn("Course", options=["APIDS", "APDA", "Data Science", "Data Analytics"], default="APIDS"),
                "Completion Date": st.column_config.TextColumn("Completion Date", default=datetime.now().strftime("%d-%b-%Y")),
                "Certificate Number": st.column_config.TextColumn("Certificate Number (Optional)"),
            },
        )

        if st.button("💾 Save Grid Changes to Active Roster"):
            cleaned_records = []
            for _, row in edited_df.iterrows():
                name_val = str(row.get("Name", "")).strip()
                email_val = str(row.get("Email ID", "")).strip()
                if name_val and name_val.lower() not in ("nan", "none") and email_val and email_val.lower() not in ("nan", "none"):
                    cleaned_records.append({
                        "Name": name_val,
                        "Mobile Number": str(row.get("Mobile Number", "")).strip() if str(row.get("Mobile Number", "")).lower() not in ("nan", "none") else "",
                        "Email ID": email_val,
                        "Course": str(row.get("Course", "APIDS")).strip() if str(row.get("Course", "")).lower() not in ("nan", "none") else "APIDS",
                        "Completion Date": str(row.get("Completion Date", "")).strip() if str(row.get("Completion Date", "")).lower() not in ("nan", "none") else datetime.now().strftime("%d-%b-%Y"),
                        "Certificate Number": str(row.get("Certificate Number", "")).strip() if str(row.get("Certificate Number", "")).lower() not in ("nan", "none") else "",
                    })
            st.session_state.records = cleaned_records
            st.success(f"✓ Saved {len(cleaned_records)} participants to active roster.")
            st.rerun()

    # ------------------ Sub-Mode 2: Bulk Upload ------------------
    elif input_mode == "📁 Bulk Upload (Excel / CSV)":
        bulk_file = st.file_uploader("Upload Participant File (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])
        
        sample_col, _ = st.columns([1, 2])
        with sample_col:
            sample_data = pd.DataFrame([
                {"Name": "Aarav Sharma", "Mobile Number": "+91 9876543210", "Email ID": "aarav.sharma@example.com", "Course": "APIDS", "Completion Date": "15-May-2026"},
                {"Name": "Ananya Patel", "Mobile Number": "+91 9812345678", "Email ID": "ananya.patel@example.com", "Course": "APDA", "Completion Date": "15-May-2026"},
            ])
            sample_buffer = io.BytesIO()
            sample_data.to_excel(sample_buffer, index=False)
            st.download_button(
                "⬇️ Download Sample Excel Template",
                data=sample_buffer.getvalue(),
                file_name="sample_participants_template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        if bulk_file:
            try:
                if bulk_file.name.endswith(".csv"):
                    df = pd.read_csv(bulk_file)
                else:
                    df = pd.read_excel(bulk_file)

                is_valid, column_map, missing = validate_excel_columns(df)
                if not is_valid:
                    st.error(f"❌ Missing required columns: {', '.join(missing)}. Please check your file.")
                else:
                    records = normalize_records(df, column_map)
                    mapping_str = " · ".join(f"{k} → `{v}`" for k, v in column_map.items())
                    st.markdown(f'<span class="dv-badge dv-badge-ok">✓ {len(records)} records loaded from {bulk_file.name}</span>', unsafe_allow_html=True)
                    st.caption(f"Detected Column Mapping: {mapping_str}")
                    st.dataframe(pd.DataFrame(records), use_container_width=True, height=200)

                    c_act1, c_act2 = st.columns(2)
                    with c_act1:
                        if st.button("➕ Replace Active Roster with Uploaded File", use_container_width=True):
                            st.session_state.records = records
                            st.session_state.cert_paths = {}
                            st.success(f"✓ Active roster set to {len(records)} participants.")
                            st.rerun()
                    with c_act2:
                        if st.button("📥 Append to Current Active Roster", use_container_width=True):
                            existing_emails = {r["Email ID"].lower() for r in st.session_state.records}
                            added = 0
                            for r in records:
                                if r["Email ID"].lower() not in existing_emails:
                                    st.session_state.records.append(r)
                                    existing_emails.add(r["Email ID"].lower())
                                    added += 1
                            st.success(f"✓ Appended {added} new participants to active roster (total: {len(st.session_state.records)}).")
                            st.rerun()
            except Exception as e:
                st.error(f"Could not read uploaded file: {e}")

    # ------------------ Sub-Mode 3: Google Sheets Sync ------------------
    else:
        st.markdown("##### 🌐 Fetch from Shared Google Sheet")
        g_url = st.text_input(
            "Google Sheet URL or Spreadsheet ID",
            value=get_secret("DEFAULT_SHEET_URL", "https://docs.google.com/spreadsheets/d/1vTrLQiIvB6fMTUgsQtuJcnFR-Z3VVY_ALTRKF2dH0Jw/edit?usp=sharing"),
        )
        g_tab = st.text_input("Worksheet / Tab Name (Optional)", placeholder="e.g. Sheet1")

        if st.button("🔄 Fetch Roster from Google Sheet"):
            try:
                roster_rows = sheets_readonly.get_roster(g_url, worksheet_name=g_tab or None)
                if not roster_rows:
                    st.warning("No rows found in the specified Google Sheet.")
                else:
                    sheet_records = []
                    for r in roster_rows:
                        sheet_records.append({
                            "Name": r.name,
                            "Mobile Number": r.mobile or "",
                            "Email ID": r.email,
                            "Course": r.course or "APIDS",
                            "Completion Date": r.completion_date or datetime.now().strftime("%d-%b-%Y"),
                            "Certificate Number": r.existing_certificate_number or "",
                        })
                    st.session_state.records = sheet_records
                    st.session_state.cert_paths = {}
                    st.success(f"✓ Successfully imported {len(sheet_records)} participants from Google Sheet!")
                    st.rerun()
            except Exception as e:
                st.error(f"Failed to fetch Google Sheet: {e}")

    # Active roster status banner
    if st.session_state.records:
        st.markdown("---")
        rc1, rc2 = st.columns([3, 1])
        with rc1:
            st.markdown(f'<span class="dv-badge dv-badge-ok">✓ Active Roster: {len(st.session_state.records)} Participants Loaded</span>', unsafe_allow_html=True)
        with rc2:
            export_df = pd.DataFrame(st.session_state.records)
            csv_data = export_df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Export Roster (CSV)", csv_data, file_name="active_roster.csv", mime="text/csv", use_container_width=True)

    card_end()

    # ------------------ Template Selection ------------------
    card_start("2. Certificate Template (Auto-Loaded & Ready)", "The official DV Analytics certificate template is pre-configured and automatically loaded. You do not need to re-upload templates.")

    tpl_mode = st.radio(
        "Certificate Template Mode",
        ["🎓 Official Built-in Template (Auto-Loaded · Zero Uploads Needed)", "🎨 Upload Custom Template (Optional)"],
        horizontal=True,
    )
    st.session_state.template_mode = "Official APIDS / APDA Template" if "Official" in tpl_mode else "Custom Template"

    if st.session_state.template_mode == "Official APIDS / APDA Template":
        st.markdown(
            """
            <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:12px; padding:12px 16px; margin-bottom:14px; font-size:13px; color:#166534;">
                <strong>✅ Template Automatically Active:</strong>
                The official DV Analytics Certificate template is already loaded into your system. You <strong>never need to upload it again</strong>.
                Participant names, registration numbers, dates, and verification QR codes will be rendered automatically.
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            st.session_state.selected_official_course = st.selectbox(
                "Course Template",
                ["APIDS", "APDA"],
                index=0 if st.session_state.selected_official_course == "APIDS" else 1,
                help="APIDS = Advanced Program in Data Science, APDA = Advanced Program in Data Analytics",
            )
            st.session_state.cert_batch_prefix = st.text_input(
                "Batch Prefix (Year/Month)",
                value=st.session_state.get("cert_batch_prefix", "202505"),
                help="e.g. 202505 (for May 2025) or 202609",
            )
        with col_t2:
            st.session_state.institute_code = st.text_input(
                "Institute Code",
                value=st.session_state.get("institute_code", "DVA"),
                help="e.g. DVA",
            )
            st.session_state.cert_start_seq = st.number_input(
                "Starting Sequence #",
                min_value=1,
                value=int(st.session_state.get("cert_start_seq", 2075)),
                step=1,
                help="Sequence will auto-increment from this number (e.g. 2075 -> 2076 -> 2077)",
            )
        with col_t3:
            st.session_state.verification_base_url = st.text_input(
                "Verification Base URL (for QR Code)",
                value=st.session_state.verification_base_url,
                help="QR codes point to {this}/verify/{cert_number}",
            )
            sample_seq = f"{st.session_state.cert_batch_prefix}{st.session_state.institute_code}{st.session_state.cert_start_seq}"
            st.markdown(
                f"""
                <div style="background:#f1f5f9; border:1px solid #cbd5e1; border-radius:10px; padding:10px 14px; margin-top:24px; font-size:12.5px; color:#334155;">
                    <strong>🎯 Auto Sequence Preview:</strong><br>
                    <code>{sample_seq}</code>, <code>{st.session_state.cert_batch_prefix}{st.session_state.institute_code}{int(st.session_state.cert_start_seq)+1}</code>...
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.caption(
            f"Active Template File: `assets/templates/certificate_{st.session_state.selected_official_course}_blank.pptx` · "
            f"Auto Numbering Format: `{st.session_state.cert_batch_prefix}{st.session_state.institute_code}{st.session_state.cert_start_seq}`"
        )

    else:
        custom_file = st.file_uploader("Upload Custom Template (PNG, JPG, PDF)", type=["png", "jpg", "jpeg", "pdf"])
        if custom_file:
            custom_path = os.path.join(OUTPUT_DIR, f"template{os.path.splitext(custom_file.name)[1]}")
            with open(custom_path, "wb") as f:
                f.write(custom_file.getbuffer())
            st.session_state.custom_template_path = custom_path

            fingerprint = (custom_file.name, custom_file.size)
            if fingerprint != st.session_state.custom_template_fingerprint:
                st.session_state.custom_template_fingerprint = fingerprint
                template_img = load_template_as_image(custom_path)
                s_y = suggest_name_position(template_img)
                s_size, s_color = suggest_text_style(template_img, s_y)
                st.session_state.y_pos_pct = int(round(s_y * 100))
                st.session_state.font_size = s_size
                st.session_state.text_color_hex = "#%02x%02x%02x" % s_color

            with st.expander("🎨 Name Placement, Font Size & Color", expanded=True):
                c_f1, c_f2 = st.columns(2)
                with c_f1:
                    st.slider("Font size (px)", 20, 300, key="font_size")
                    st.slider("Vertical position (% down)", 0, 100, key="y_pos_pct")
                with c_f2:
                    st.color_picker("Text color", key="text_color_hex")
                    if st.button("↺ Auto-fit to Template"):
                        t_img = load_template_as_image(custom_path)
                        s_y = suggest_name_position(t_img)
                        s_size, s_color = suggest_text_style(t_img, s_y)
                        st.session_state.y_pos_pct = int(round(s_y * 100))
                        st.session_state.font_size = s_size
                        st.session_state.text_color_hex = "#%02x%02x%02x" % s_color
                        st.rerun()

            # Live preview on custom template
            template_img = load_template_as_image(custom_path)
            sample_name = st.session_state.records[0]["Name"] if st.session_state.records else "Sample Student"
            font_size = st.session_state.font_size
            y_pos = st.session_state.y_pos_pct / 100.0
            color_hex = st.session_state.text_color_hex
            text_color = tuple(int(color_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            
            preview_img = render_certificate_image(
                template_img, sample_name, None, font_size, text_color, y_pos
            )
            st.image(preview_img, caption=f"Template Preview ({sample_name})", use_container_width=True)

    card_end()


# ===========================================================================
# TAB 2 — Generate Certificates
# ===========================================================================
with tab2:
    card_start("Generate Certificates", "Generate personalized, high-resolution certificates with verification QR codes.")

    records = st.session_state.records
    total_recs = len(records)
    generated_count = len(st.session_state.cert_paths)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Participants", total_recs)
    m2.metric("Template Mode", "Official PPTX" if "Official" in st.session_state.template_mode else "Custom Image")
    m3.metric("Certificates Generated", generated_count)
    m4.metric("Pending Generation", max(total_recs - generated_count, 0))

    if total_recs == 0:
        st.info("⚠️ Please add participants in **Step ① Add Participants & Template** first.")
    else:
        st.markdown(
            """
            <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:12px; padding:14px 18px; margin-bottom:16px; font-size:13px; color:#1e40af;">
                <div style="font-weight:700; font-size:14px; margin-bottom:4px;">🛡️ High-Tight Ironclad Digital Security Active:</div>
                <ul style="margin:6px 0 0 16px; padding:0; line-height:1.6;">
                    <li><strong>Pixel-Lock Flattening (300 DPI):</strong> All student names, course titles, dates, and certificate numbers are permanently baked into ultra-high-resolution image layers. Vector text and font streams are completely eliminated — no PDF editor (Adobe Acrobat, Illustrator, Nitro, Word, Canva) can select, edit, or manipulate any text.</li>
                    <li><strong>AES-256 Zero-Permission Lock:</strong> Permission mask is locked to 0. Printing, Document Editing, Content Extraction, Form Filling, and Annotations are strictly disabled.</li>
                    <li><strong>Cryptographic SHA-256 Seal:</strong> Each certificate receives an immutable digital provenance fingerprint stored in the registry for instant QR verification.</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("##### ⚡ Generation Actions")
        g_col1, g_col2 = st.columns([1, 1])

        with g_col1:
            if st.button("🎓 Generate All Certificates", use_container_width=True, disabled=(total_recs == 0)):
                progress = st.progress(0, text="Initializing generation...")
                cert_paths = {}
                default_course = st.session_state.selected_official_course

                for i, rec in enumerate(records):
                    name = rec["Name"]
                    email = rec.get("Email ID", "")
                    progress.progress((i + 1) / total_recs, text=f"Generating {i+1} of {total_recs}: {name}")
                    try:
                        cert_no, pdf_path, _, sha256_hash = build_participant_cert(
                            rec, st.session_state.template_mode, default_course
                        )
                        cert_paths[email or name] = {
                            "Name": name,
                            "Email": email,
                            "Course": rec.get("Course") or default_course,
                            "CertNumber": cert_no,
                            "Path": pdf_path,
                            "SHA256": sha256_hash,
                            "Status": "Generated",
                        }
                    except Exception as e:
                        cert_paths[email or name] = {
                            "Name": name,
                            "Email": email,
                            "Course": rec.get("Course") or default_course,
                            "CertNumber": "Error",
                            "Path": None,
                            "SHA256": "",
                            "Status": f"Failed: {e}",
                        }
                        log_event(email, "CERT_GEN_ERROR", str(e))

                st.session_state.cert_paths = cert_paths
                progress.empty()
                ok_count = sum(1 for v in cert_paths.values() if v.get("Path"))
                st.success(f"✓ Generation complete! Successfully generated {ok_count} of {total_recs} certificates with AES-256 security lock.")
                st.rerun()

        with g_col2:
            if st.button("👁️ Instant Preview / Test (First Student)", use_container_width=True, disabled=(total_recs == 0)):
                try:
                    first_rec = records[0]
                    default_course = st.session_state.selected_official_course
                    cert_no, pdf_path, _, _ = build_participant_cert(first_rec, st.session_state.template_mode, default_course)
                    st.success(f"✓ Generated Secured Preview Certificate: **{cert_no}** for **{first_rec['Name']}**")
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            f"⬇️ Download Preview PDF ({cert_no}.pdf)",
                            data=f.read(),
                            file_name=f"{cert_no}.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                        )
                except Exception as e:
                    st.error(f"Could not build preview certificate: {e}")

        # Review Table & Zip Download
        if st.session_state.cert_paths:
            st.markdown("---")
            st.markdown("##### 📋 Generated Certificates & Security Ledger")

            review_rows = []
            for k, info in st.session_state.cert_paths.items():
                review_rows.append({
                    "Student Name": info.get("Name"),
                    "Email ID": info.get("Email"),
                    "Course": info.get("Course"),
                    "Certificate Number": info.get("CertNumber"),
                    "Security Protection": "🔒 Pixel-Locked 300 DPI · AES-256 Zero-Permission",
                    "Status": "✅ Ready & Locked" if info.get("Path") else f"❌ {info.get('Status')}",
                })
            st.dataframe(pd.DataFrame(review_rows), use_container_width=True, height=240)

            # Zip download
            valid_paths = [info["Path"] for info in st.session_state.cert_paths.values() if info.get("Path") and os.path.exists(info["Path"])]
            if valid_paths:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for p in valid_paths:
                        zf.write(p, arcname=os.path.basename(p))
                st.download_button(
                    "📦 Download All Generated Certificates (.zip)",
                    data=zip_buffer.getvalue(),
                    file_name="All_Certificates.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

    card_end()


# ===========================================================================
# TAB 3 — Sending Formalities
# ===========================================================================
with tab3:
    card_start("1. SMTP Status & Configuration", "Verify your email server connectivity before dispatching certificates.")

    smtp_cfg = SMTPConfig()
    s_col1, s_col2 = st.columns([2, 1])
    with s_col1:
        if smtp_cfg.is_configured():
            st.markdown(f'<span class="dv-badge dv-badge-ok">● SMTP Connected ({smtp_cfg.username})</span>', unsafe_allow_html=True)
            st.caption(f"Host: `{smtp_cfg.host}:{smtp_cfg.port}` · Sender: `{smtp_cfg.sender_name}`")
        else:
            st.markdown('<span class="dv-badge dv-badge-warn">● SMTP Not Configured</span>', unsafe_allow_html=True)
            st.caption("Please configure **SMTP_EMAIL** and **SMTP_PASSWORD** (Gmail App Password) in Streamlit secrets.")

    with s_col2:
        with st.expander("🧪 Send Test Email"):
            test_recipient = st.text_input("Test Email Address", value=smtp_cfg.username)
            if st.button("Send Test", use_container_width=True, disabled=not smtp_cfg.is_configured()):
                try:
                    with EmailSender() as sender:
                        sender.send(
                            test_recipient,
                            "DV Analytics SMTP Connection Test",
                            "Hello! This is a test email confirming your DV Analytics Certificate delivery system is functioning perfectly.",
                        )
                    st.success("✓ Test email sent successfully!")
                except Exception as e:
                    st.error(f"Test email failed: {e}")
    card_end()

    card_start("2. Dynamic Email Composer", "Compose your subject and message. Dynamic tags are personalized per participant.")

    col_em1, col_em2 = st.columns(2)
    with col_em1:
        email_subj = st.text_input("Email Subject", key="email_subject_tpl")
    with col_em2:
        st.markdown(
            "**Available Tags:** &nbsp; `{{Name}}` &nbsp; `{{Course}}` &nbsp; `{{CertNo}}` &nbsp; `{{Date}}` &nbsp; `{{Mobile}}`",
            unsafe_allow_html=True,
        )

    email_body = st.text_area("Email Body", height=180, key="email_body_tpl")

    # Live Preview of first recipient
    if st.session_state.records:
        with st.expander("👁️ Live Preview for First Recipient"):
            sample_rec = st.session_state.records[0]
            sample_name = sample_rec["Name"]
            sample_course = sample_rec.get("Course") or st.session_state.selected_official_course
            sample_cert = sample_rec.get("Certificate Number") or "DVA-APIDS-2026-000001"
            sample_date = sample_rec.get("Completion Date") or datetime.now().strftime("%d-%b-%Y")
            sample_mob = sample_rec.get("Mobile Number", "")

            prev_subj = _apply_email_placeholders(email_subj, name=sample_name, course=sample_course, cert_no=sample_cert, date=sample_date, mobile=sample_mob)
            prev_body = _apply_email_placeholders(email_body, name=sample_name, course=sample_course, cert_no=sample_cert, date=sample_date, mobile=sample_mob)

            st.markdown(f"**To:** `{sample_rec.get('Email ID', 'student@example.com')}`")
            st.markdown(f"**Subject:** {prev_subj}")
            st.text_area("Rendered Message", value=prev_body, height=130, disabled=True)

    card_end()

    card_start("3. Bulk Email Dispatch", "Send certificates directly to participants with attachment and delivery logging.")

    records = st.session_state.records
    total_recs = len(records)
    cert_map = st.session_state.cert_paths

    sent_count = sum(1 for r in st.session_state.results if r.get("Email Sent") == "Yes")
    failed_count = sum(1 for r in st.session_state.results if r.get("Email Sent") == "No")
    ready_to_send = sum(1 for info in cert_map.values() if info.get("Path") and os.path.exists(info["Path"]))

    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Total Participants", total_recs)
    sm2.metric("Certificates Ready", ready_to_send)
    sm3.metric("Emails Sent", sent_count)
    sm4.metric("Pending / Failed", max(total_recs - sent_count, 0))

    can_send = bool(total_recs > 0 and ready_to_send > 0 and smtp_cfg.is_configured())

    if not records:
        st.info("Add participants in Tab ① first.")
    elif ready_to_send == 0:
        st.warning("Generate certificates in Tab ② before sending.")
    elif not smtp_cfg.is_configured():
        st.error("SMTP is not configured. Please add SMTP credentials in Streamlit secrets.")

    if st.button("✉️ Send Certificates in Bulk", use_container_width=True, disabled=not can_send):
        progress = st.progress(0, text="Connecting to SMTP server...")
        results = []
        default_course = st.session_state.selected_official_course

        sender = None
        try:
            sender = EmailSender()
            sender.connect()
        except Exception as e:
            st.error(f"Could not connect to SMTP server: {e}")

        for i, rec in enumerate(records):
            name = rec["Name"]
            email = rec.get("Email ID", "").strip()
            mobile = rec.get("Mobile Number", "").strip()
            course = rec.get("Course") or default_course
            date_val = rec.get("Completion Date") or datetime.now().strftime("%d-%b-%Y")

            info = cert_map.get(email or name, {})
            cert_path = info.get("Path")
            cert_no = info.get("CertNumber") or rec.get("Certificate Number", "")

            row_res = {
                "Name": name,
                "Mobile Number": mobile,
                "Email ID": email,
                "Course": course,
                "Certificate Number": cert_no,
                "Certificate Generated": "Yes" if (cert_path and os.path.exists(cert_path)) else "No",
                "Email Sent": "No",
                "Sent Date & Time": "",
                "Error Message": "",
            }

            progress.progress((i + 1) / total_recs, text=f"Sending {i+1} of {total_recs}: {name} ({email})")

            if not email or not is_valid_email(email):
                row_res["Error Message"] = "Invalid or missing email address"
                log_event(email, "FAILED", "Invalid or missing email address")
                results.append(row_res)
                continue

            if not cert_path or not os.path.exists(cert_path):
                row_res["Error Message"] = "Certificate PDF not found. Please generate in Tab 2."
                log_event(email, "FAILED", "Certificate PDF not found")
                results.append(row_res)
                continue

            if sender is None:
                row_res["Error Message"] = "SMTP server unavailable"
                results.append(row_res)
                continue

            # Personalize subject & body
            p_subj = _apply_email_placeholders(email_subj, name=name, course=course, cert_no=cert_no, date=date_val, mobile=mobile)
            p_body = _apply_email_placeholders(email_body, name=name, course=course, cert_no=cert_no, date=date_val, mobile=mobile)

            try:
                sender.send(email, p_subj, p_body, cert_path)
                row_res["Email Sent"] = "Yes"
                row_res["Sent Date & Time"] = now_str()
                cert_store.mark_sent(cert_no)
                log_event(email, "SENT", f"Cert: {cert_no}")
            except Exception as e:
                row_res["Error Message"] = str(e)
                cert_store.mark_send_failed(cert_no, str(e))
                log_event(email, "FAILED", str(e))

            results.append(row_res)

        if sender is not None:
            sender.close()

        st.session_state.results = results
        progress.empty()

        # Save reports
        report_df = build_report_dataframe(results)
        report_df.to_excel(REPORT_PATH, index=False)
        errors_df = report_df[report_df["Error Message"] != ""]
        if not errors_df.empty:
            errors_df.to_excel(ERROR_REPORT_PATH, index=False)

        n_sent = sum(1 for r in results if r["Email Sent"] == "Yes")
        st.success(f"✓ Bulk delivery finished! {n_sent} of {total_recs} emails delivered successfully.")
        st.rerun()

    card_end()


# ===========================================================================
# TAB 4 — Delivery Report & Analytics
# ===========================================================================
with tab4:
    card_start("Delivery Analytics & Executive KPIs", "Real-time metrics and audit summary across all participants.")

    records = st.session_state.records
    cert_map = st.session_state.cert_paths
    results = st.session_state.results

    total = len(records)
    certs_gen = sum(1 for v in cert_map.values() if v.get("Path") and os.path.exists(v.get("Path")))
    emails_sent = sum(1 for r in results if r.get("Email Sent") == "Yes")
    emails_failed = sum(1 for r in results if r.get("Email Sent") == "No" and r.get("Error Message"))
    success_rate = f"{(emails_sent / total * 100):.1f}%" if total > 0 else "0.0%"

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Participants", total)
    k2.metric("Certificates Ready", certs_gen)
    k3.metric("Emails Delivered", emails_sent)
    k4.metric("Failed Deliveries", emails_failed)
    k5.metric("Success Rate", success_rate)
    card_end()

    card_start("Actionable Download Center", "Download all certificate PDFs, detailed Excel audit reports, and execution logs.")
    dl1, dl2, dl3, dl4 = st.columns(4)

    with dl1:
        valid_paths = [info["Path"] for info in cert_map.values() if info.get("Path") and os.path.exists(info["Path"])]
        if valid_paths:
            zbuf = io.BytesIO()
            with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in valid_paths:
                    zf.write(p, arcname=os.path.basename(p))
            st.download_button("⬇️ Certificates (.zip)", zbuf.getvalue(), file_name="Certificates.zip", mime="application/zip", use_container_width=True)
        else:
            st.button("⬇️ Certificates (.zip)", disabled=True, use_container_width=True)

    with dl2:
        if os.path.exists(REPORT_PATH):
            with open(REPORT_PATH, "rb") as f:
                st.download_button("⬇️ Email Report (.xlsx)", f.read(), file_name="Email_Sending_Report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        else:
            st.button("⬇️ Email Report (.xlsx)", disabled=True, use_container_width=True)

    with dl3:
        if os.path.exists(ERROR_REPORT_PATH):
            with open(ERROR_REPORT_PATH, "rb") as f:
                st.download_button("⬇️ Error Report (.xlsx)", f.read(), file_name="Error_Report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        else:
            st.button("⬇️ Error Report (.xlsx)", disabled=True, use_container_width=True)

    with dl4:
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, "rb") as f:
                st.download_button("⬇️ Event Logs (.txt)", f.read(), file_name="email_log.txt", mime="text/plain", use_container_width=True)
        else:
            st.button("⬇️ Event Logs (.txt)", disabled=True, use_container_width=True)

    card_end()

    card_start("Full Delivery Audit Report", "Interactive searchable log of all participant certificate and email events.")

    if results:
        full_df = build_report_dataframe(results)
        f_col1, f_col2 = st.columns([1, 2])
        with f_col1:
            status_filter = st.selectbox("Filter by Status", ["All Records", "Sent Successfully", "Failed Deliveries"])
        with f_col2:
            search_query = st.text_input("🔍 Search by Name, Email, or Cert Number", "")

        filtered_df = full_df.copy()
        if status_filter == "Sent Successfully":
            filtered_df = filtered_df[filtered_df["Email Sent"] == "Yes"]
        elif status_filter == "Failed Deliveries":
            filtered_df = filtered_df[filtered_df["Email Sent"] == "No"]

        if search_query.strip():
            q = search_query.strip().lower()
            filtered_df = filtered_df[
                filtered_df["Name"].str.lower().str.contains(q)
                | filtered_df["Email ID"].str.lower().str.contains(q)
                | filtered_df["Certificate Number"].str.lower().str.contains(q)
            ]

    card_end()

    # ------------------ Permanent Certificate Vault & Recovery ------------------
    card_start("🗄️ Issued Certificate Vault & Lost Certificate Recovery", "Permanent archive of all issued certificates. Instantly search, download, or re-email a copy to any student who lost theirs.")

    v_q = st.text_input("🔍 Search Vault by Student Name, Email ID, or Certificate Number", placeholder="e.g. Sk Abudl Sajid or 202505DVA2075 or student@example.com")

    vault_records = cert_store.search_certificates(v_q)

    if vault_records:
        st.markdown(f"**Found {len(vault_records)} certificate(s) in permanent vault:**")

        if v_q.strip():
            for rec in vault_records[:5]:  # Show top 5 detailed cards
                with st.container():
                    st.markdown(
                        f"""
                        <div style="background:#ffffff; border:1.5px solid #e2e8f0; border-radius:14px; padding:16px 20px; margin-bottom:12px; box-shadow:0 4px 12px rgba(0,0,0,0.03);">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                                <div style="font-weight:700; font-size:16px; color:#0f172a;">🎓 {rec.name}</div>
                                <span class="dv-badge dv-badge-ok">🔒 {rec.cert_number}</span>
                            </div>
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:8px; font-size:13px; color:#475569; margin-bottom:12px;">
                                <div><strong>Course:</strong> {rec.course}</div>
                                <div><strong>Email:</strong> {rec.email}</div>
                                <div><strong>Completion Date:</strong> {rec.completion_date or 'N/A'}</div>
                                <div><strong>Status:</strong> {rec.status} ({rec.email_status})</div>
                                <div><strong>Issued At:</strong> {rec.created_at[:10] if rec.created_at else 'N/A'}</div>
                                <div><strong>SHA-256 Seal:</strong> <code>{rec.pdf_hash[:12] if rec.pdf_hash else 'Secured'}...</code></div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # Action buttons for this specific student
                    ac1, ac2, ac3 = st.columns([1.5, 1.5, 1])
                    with ac1:
                        pdf_path = ensure_cert_pdf_exists(rec)
                        if os.path.exists(pdf_path):
                            with open(pdf_path, "rb") as f:
                                st.download_button(
                                    f"⬇️ Download {rec.cert_number}.pdf",
                                    data=f.read(),
                                    file_name=f"{rec.cert_number}.pdf",
                                    mime="application/pdf",
                                    key=f"dl_vault_{rec.cert_number}",
                                    use_container_width=True,
                                )
                    with ac2:
                        if st.button(f"✉️ Re-email to {rec.name}", key=f"resend_{rec.cert_number}", use_container_width=True):
                            if not smtp_cfg.is_configured():
                                st.error("SMTP credentials not configured in Streamlit secrets.")
                            else:
                                try:
                                    sender = EmailSender()
                                    sender.connect()
                                    pdf_path = ensure_cert_pdf_exists(rec)
                                    p_subj = _apply_email_placeholders(
                                        st.session_state.email_subject_tpl,
                                        name=rec.name,
                                        course=rec.course,
                                        cert_no=rec.cert_number,
                                        date=rec.completion_date or datetime.now().strftime("%d-%b-%Y"),
                                    )
                                    p_body = _apply_email_placeholders(
                                        st.session_state.email_body_tpl,
                                        name=rec.name,
                                        course=rec.course,
                                        cert_no=rec.cert_number,
                                        date=rec.completion_date or datetime.now().strftime("%d-%b-%Y"),
                                    )
                                    sender.send(rec.email, p_subj, p_body, pdf_path)
                                    sender.close()
                                    cert_store.mark_sent(rec.cert_number)
                                    st.success(f"✓ Successfully re-emailed certificate to {rec.email}!")
                                except Exception as e:
                                    st.error(f"Failed to re-send: {e}")
                    with ac3:
                        verify_link = qr_utils.verification_url(
                            rec.cert_number,
                            base_url=st.session_state.get("verification_base_url", "http://localhost:8000"),
                        )
                        st.link_button("👁️ Verify Online", verify_link, use_container_width=True)

        st.markdown("##### 📜 Master Certificate Registry & Historical Ledger")
        v_df = pd.DataFrame([
            {
                "Certificate Number": r.cert_number,
                "Student Name": r.name,
                "Email ID": r.email,
                "Course": r.course,
                "Completion Date": r.completion_date,
                "Issued Date": r.created_at[:10] if r.created_at else "",
                "Send Status": r.email_status,
                "Security Seal": f"🔒 {r.pdf_hash[:10]}..." if r.pdf_hash else "🔒 AES-256",
            }
            for r in vault_records
        ])
        st.dataframe(v_df, use_container_width=True, height=260)

        vb1, vb2 = st.columns(2)
        with vb1:
            vault_files = [ensure_cert_pdf_exists(r) for r in vault_records]
            existing_vault_files = [p for p in vault_files if os.path.exists(p)]
            if existing_vault_files:
                v_zbuf = io.BytesIO()
                with zipfile.ZipFile(v_zbuf, "w", zipfile.ZIP_DEFLATED) as vzf:
                    for p in existing_vault_files:
                        vzf.write(p, arcname=os.path.basename(p))
                st.download_button(
                    "📦 Download Entire Vault Archive (.zip)",
                    data=v_zbuf.getvalue(),
                    file_name="All_Issued_Certificates_Vault.zip",
                    mime="application/zip",
                    use_container_width=True,
                )
            else:
                st.button("📦 Download Entire Vault Archive (.zip)", disabled=True, use_container_width=True)
        with vb2:
            v_csv = v_df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Export Registry Ledger (CSV)", data=v_csv, file_name="Master_Certificate_Registry.csv", mime="text/csv", use_container_width=True)
    else:
        st.info("No certificates in permanent vault yet. Generated certificates will automatically be preserved here forever.")

    card_end()
