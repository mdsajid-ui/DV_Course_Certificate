"""
Automated Certificate Generation and Email Sending System
DV Analytics

Run with:  streamlit run app.py
"""

import os
import io
import zipfile

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from certificate_generator import (
    load_template_as_image,
    generate_certificate,
    render_certificate_image,
    suggest_text_style,
    suggest_name_position,
)
from email_sender import EmailSender, SMTPConfig, is_valid_email
from utils import (
    validate_excel_columns,
    normalize_records,
    build_report_dataframe,
    log_event,
    now_str,
    LOG_PATH,
)

load_dotenv()

OUTPUT_DIR = "output"
CERT_DIR = os.path.join(OUTPUT_DIR, "certificates")
REPORT_PATH = os.path.join(OUTPUT_DIR, "Email_Sending_Report.xlsx")
ERROR_REPORT_PATH = os.path.join(OUTPUT_DIR, "Error_Report.xlsx")

os.makedirs(CERT_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Page config & modern theme
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="DV Analytics â€” Certificate & Email Suite",
    page_icon="ðŸŽ“",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Login gate â€” must run before any other UI renders
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
        .lamp-glow { position:absolute; width:390px; height:390px; left:50%; top:77px; transform:translateX(-50%); background:radial-gradient(ellipse at 50% 15%,rgba(255,225,92,.42),rgba(255,212,55,.12) 43%,transparent 70%); filter:blur(5px); animation:breathe 3s ease-in-out infinite; }
        .light-cone { position:absolute; left:50%; top:126px; transform:translateX(-50%); width:330px; height:285px; background:linear-gradient(100deg,transparent 3%,rgba(255,226,116,.30) 48%,rgba(255,240,162,.17) 75%,transparent 97%); clip-path:polygon(39% 0,61% 0,100% 100%,0 100%); filter:blur(2px); }
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
        .stTextInput [data-baseweb="input"] { background:#151513 !important; border:1px solid #292925 !important; border-radius:10px !important; min-height:49px; }
        .stTextInput [data-baseweb="input"]:focus-within { border-color:#ffe000 !important; box-shadow:0 0 0 2px rgba(255,224,0,.12) !important; }
        .stTextInput input { color:#f7f7f3 !important; -webkit-text-fill-color:#f7f7f3 !important; }
        .stTextInput input::placeholder { color:#565650 !important; }
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
        <div class="lamp-heading"><h1>Lamp Login <span>V2</span></h1><p>DV Analytics Â· Certificate Automation</p></div>
        """,
        unsafe_allow_html=True,
    )

    lamp_col, form_col = st.columns([1.12, 1], gap="large")
    with lamp_col:
        st.markdown('''<div class="lamp-stage"><div class="lamp-glow"></div><div class="light-cone"></div><div class="shade"></div><div class="stem"></div><div class="base"></div><div class="cord"></div><i class="fly f1"></i><i class="fly f2"></i><i class="fly f3"></i><i class="fly f4"></i><i class="fly f5"></i></div>''', unsafe_allow_html=True)

    with form_col:
        with st.form("login_form", clear_on_submit=False):
            st.markdown('<div class="card-head"><h2>Welcome Back</h2><p>Enter your details to access your account</p></div>', unsafe_allow_html=True)
            username = st.text_input("USERNAME", placeholder="Enter your username", key="login_username")
            password = st.text_input("PASSWORD", type="password", placeholder="Enter your password", key="login_password")
            st.markdown('<div class="login-actions"><span>âœ“ &nbsp;Secure session</span><span>Authorized access only</span></div>', unsafe_allow_html=True)
            submitted = st.form_submit_button("Sign In", use_container_width=True)
            st.markdown('<div class="secure-note">ðŸ”’ Your connection is protected</div>', unsafe_allow_html=True)

    if submitted:
        # Credentials come from Streamlit secrets / environment variables only â€”
        # never hardcoded in source, since this repo is public on GitHub.
        valid_username = os.environ.get("APP_USERNAME", "")
        valid_password = os.environ.get("APP_PASSWORD", "")

        if not valid_username or not valid_password:
            st.error("âš ï¸ Login is not configured. Set APP_USERNAME and APP_PASSWORD in secrets.")
        elif username == valid_username and password == valid_password:
            st.session_state["logged_in"] = True
            st.rerun()
        else:
            st.error("âŒ Invalid username or password")

    st.markdown('<div class="login-footer">Â© 2026 DV Analytics Â· Certificate &amp; Email Automation Suite</div>', unsafe_allow_html=True)

    return st.session_state.get("logged_in", False)


if not st.session_state.get("logged_in", False):
    login()
    st.stop()


NAVY = "#0B1B4D"
NAVY_DEEP = "#060F30"
RED = "#EF233C"
ACCENT = "#5B6CF7"
ACCENT_2 = "#8A5CFF"
GOLD = "#D4AF37"
BG = "#F4F5FB"
CARD = "#FFFFFF"
BORDER = "#E7E9F6"
MUTED = "#6B7188"

st.markdown(
    f"""
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
        .stApp {{
            background:
                radial-gradient(1000px 500px at 100% -5%, {ACCENT}14, transparent 55%),
                radial-gradient(800px 500px at -5% 10%, {GOLD}10, transparent 50%),
                {BG};
        }}
        #MainMenu, footer, header[data-testid="stHeader"] {{ visibility: hidden; }}

        /* ---------- Hero ---------- */
        .dv-hero {{
            position: relative; overflow: hidden;
            background: radial-gradient(130% 180% at 0% 0%, {ACCENT_2}3d 0%, transparent 45%),
                        radial-gradient(120% 160% at 100% 100%, {RED}26 0%, transparent 40%),
                        linear-gradient(120deg, {NAVY} 0%, {NAVY_DEEP} 100%);
            padding: 32px 36px; border-radius: 22px; margin-bottom: 28px;
            display: flex; align-items: center; justify-content: space-between; gap: 18px;
            box-shadow: 0 20px 45px -18px rgba(11,27,77,0.55);
            border: 1px solid rgba(255,255,255,.08);
        }}
        .dv-hero-left {{ display: flex; align-items: center; gap: 18px; }}
        .dv-hero .mark {{
            width: 54px; height: 54px; border-radius: 15px; flex-shrink: 0;
            background: linear-gradient(135deg, {RED}, #ff7a7a);
            display: flex; align-items: center; justify-content: center;
            color: white; font-weight: 800; font-size: 20px; letter-spacing: -1px;
            font-family: 'Poppins', sans-serif;
            box-shadow: 0 8px 20px -4px {RED}aa, inset 0 1px 0 rgba(255,255,255,.25);
        }}
        .dv-hero h1 {{
            color: white; font-size: 24px; margin: 0; font-family: 'Poppins', sans-serif; font-weight: 700;
            letter-spacing: -.3px;
        }}
        .dv-hero p {{ color: #B7BEEF; font-size: 13px; margin: 4px 0 0; }}
        .dv-hero-pill {{
            display: flex; align-items: center; gap: 8px; color: #EAF0FF; font-size: 12.5px;
            font-weight: 600; padding: 8px 14px; border-radius: 999px;
            background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.14);
            backdrop-filter: blur(8px); white-space: nowrap;
        }}
        .dv-hero-pill .dot {{
            width: 7px; height: 7px; border-radius: 50%; background: #34d399;
            box-shadow: 0 0 0 3px rgba(52,211,153,.25);
        }}

        /* ---------- Glass cards ---------- */
        .dv-card {{
            background: linear-gradient(180deg, rgba(255,255,255,.9), rgba(255,255,255,.72));
            border: 1px solid {BORDER}; border-radius: 18px;
            padding: 24px 26px; margin-bottom: 20px;
            box-shadow: 0 8px 24px -14px rgba(11,27,77,0.14);
            backdrop-filter: blur(10px);
            transition: box-shadow .2s ease;
        }}
        .dv-card:hover {{ box-shadow: 0 14px 34px -16px rgba(11,27,77,0.20); }}
        .dv-section-title {{
            font-family: 'Poppins', sans-serif; font-weight: 700; font-size: 17.5px;
            color: {NAVY}; margin-bottom: 2px; display: flex; align-items: center; gap: 8px;
        }}
        .dv-section-title:before {{
            content: ""; display: inline-block; width: 6px; height: 18px; border-radius: 4px;
            background: linear-gradient(180deg, {ACCENT}, {RED});
        }}
        .dv-section-sub {{ color: {MUTED}; font-size: 13px; margin: 4px 0 16px 14px; }}

        /* ---------- Tabs as pill nav ---------- */
        div[data-testid="stTabs"] div[data-baseweb="tab-list"] {{
            gap: 6px; background: rgba(11,27,77,.05); padding: 6px; border-radius: 14px;
            border: 1px solid {BORDER};
        }}
        div[data-testid="stTabs"] button[data-baseweb="tab"] {{
            font-family: 'Poppins', sans-serif; font-weight: 600; font-size: 13.5px;
            color: {MUTED}; padding: 10px 18px; border-radius: 10px; transition: all .15s ease;
        }}
        div[data-testid="stTabs"] button[aria-selected="true"] {{
            color: white !important;
            background: linear-gradient(135deg, {NAVY}, {ACCENT});
            box-shadow: 0 6px 16px -6px {NAVY}99;
        }}
        div[data-testid="stTabs"] button[aria-selected="true"] p {{ color: white !important; }}
        div[data-testid="stTabs"] div[data-baseweb="tab-highlight"] {{ display: none; }}
        div[data-testid="stTabs"] div[data-baseweb="tab-border"] {{ display: none; }}

        /* ---------- Metrics ---------- */
        div[data-testid="stMetric"] {{
            background: linear-gradient(180deg, #ffffff, #fbfbff);
            border: 1px solid {BORDER}; border-radius: 16px;
            padding: 16px 18px; box-shadow: 0 6px 18px -12px rgba(11,27,77,0.18);
            border-top: 3px solid {ACCENT};
        }}
        div[data-testid="stMetricLabel"] {{ color: {MUTED}; font-weight: 600; font-size: 12.5px; text-transform: uppercase; letter-spacing: .3px; }}
        div[data-testid="stMetricValue"] {{ color: {NAVY}; font-family: 'Poppins', sans-serif; font-weight: 700; }}

        /* ---------- Advanced buttons ---------- */
        .stButton>button {{
            position: relative; overflow: hidden;
            background: linear-gradient(135deg, {NAVY} 0%, {ACCENT} 55%, {ACCENT_2} 130%);
            background-size: 200% auto;
            color: white; border-radius: 12px; font-weight: 700; border: none;
            padding: 0.68em 1.5em; font-family: 'Poppins', sans-serif; font-size: 14.5px;
            box-shadow: 0 10px 24px -8px {NAVY}77, inset 0 1px 0 rgba(255,255,255,.18);
            transition: all .22s ease; letter-spacing: .1px;
        }}
        .stButton>button:hover {{
            transform: translateY(-2px); background-position: right center;
            box-shadow: 0 16px 32px -10px {NAVY}99, inset 0 1px 0 rgba(255,255,255,.25); color: white;
        }}
        .stButton>button:active {{ transform: translateY(0px) scale(.99); }}
        .stButton>button:disabled {{
            background: #DEE0EE; color: #9296AC; box-shadow: none; transform: none;
        }}
        .stDownloadButton>button {{
            background: white; color: {NAVY}; border: 1.5px solid {NAVY}2e; border-radius: 12px;
            font-weight: 700; font-family: 'Poppins', sans-serif; font-size: 13.5px;
            transition: all .18s ease; padding: 0.6em 1.2em;
        }}
        .stDownloadButton>button:hover {{
            border-color: {ACCENT}; color: {ACCENT}; transform: translateY(-1px);
            box-shadow: 0 8px 18px -10px {ACCENT}aa;
        }}

        /* Primary CTA buttons (generate / send) get an extra glow */
        div[data-testid="stTabs"] .stButton>button[kind="secondary"],
        button[kind="primary"] {{
            background: linear-gradient(135deg, {RED} 0%, {ACCENT_2} 100%) !important;
        }}

        .dv-badge {{
            display: inline-block; padding: 4px 13px; border-radius: 999px;
            font-size: 12px; font-weight: 700; font-family: 'Poppins', sans-serif;
            letter-spacing: .2px;
        }}
        .dv-badge-ok {{ background: #E4F7EC; color: #128A44; }}
        .dv-badge-warn {{ background: #FDECEC; color: {RED}; }}

        div[data-testid="stProgress"] > div > div {{
            background: linear-gradient(90deg, {ACCENT}, {RED}); border-radius: 999px;
        }}

        /* ---------- File uploader ---------- */
        [data-testid="stFileUploaderDropzone"] {{
            background: linear-gradient(180deg, #fbfbff, #f4f5fc) !important;
            border: 1.5px dashed {ACCENT}55 !important; border-radius: 14px !important;
        }}

        /* ---------- Sidebar ---------- */
        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, {NAVY_DEEP}, {NAVY}) !important;
        }}
        section[data-testid="stSidebar"] * {{ color: #EAF0FF !important; }}
        section[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,.12) !important; }}
    </style>

    <div class="dv-hero">
        <div class="dv-hero-left">
            <div class="mark">DV</div>
            <div>
                <h1>Certificate &amp; Email Suite</h1>
                <p>Automated certificate generation and personalized email delivery</p>
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
# Session state
# ---------------------------------------------------------------------------
defaults = {
    "records": [],
    "column_map": {},
    "template_path": None,
    "template_fingerprint": None,
    "cert_paths": {},
    "results": [],
    "font_size": 60,
    "y_pos_pct": 50,
    "text_color_hex": "#0B1B4D",
    "confirmed_params": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------------------------
# Sidebar â€” SMTP status
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("#### âœ‰ï¸ SMTP status")
    cfg = SMTPConfig()
    if cfg.is_configured():
        st.markdown('<span class="dv-badge dv-badge-ok">â— Connected</span>', unsafe_allow_html=True)
        st.caption(f"{cfg.username}\nvia {cfg.host}:{cfg.port}")
    else:
        st.markdown('<span class="dv-badge dv-badge-warn">â— Not configured</span>', unsafe_allow_html=True)
        st.caption(
            "Set **SMTP_EMAIL** and **SMTP_PASSWORD** as environment variables / "
            "Streamlit secrets. Gmail requires an **App Password**, not your normal login."
        )
    st.divider()
    st.caption("DV Analytics Â· Certificate & Email Suite")

tab1, tab2, tab3, tab4 = st.tabs(
    ["â‘   Upload", "â‘¡  Generate", "â‘¢  Send", "â‘£  Dashboard"]
)

# ---------------------------------------------------------------------------
# TAB 1 â€” Upload
# ---------------------------------------------------------------------------
with tab1:
    card_start("Participant list", "Required fields: Name, Mobile Number, Email ID â€” headers are matched flexibly.")
    excel_file = st.file_uploader("Excel file (.xlsx)", type=["xlsx"], label_visibility="collapsed")

    if excel_file:
        try:
            df = pd.read_excel(excel_file)
            is_valid, column_map, missing = validate_excel_columns(df)
            if not is_valid:
                st.error(f"Missing required column(s): {', '.join(missing)}")
            else:
                records = normalize_records(df, column_map)
                st.session_state.records = records
                st.session_state.column_map = column_map
                mapping_str = " Â· ".join(f"{k} â†’ `{v}`" for k, v in column_map.items())
                st.markdown(f'<span class="dv-badge dv-badge-ok">âœ“ {len(records)} records validated</span>', unsafe_allow_html=True)
                st.caption(mapping_str)
                st.dataframe(pd.DataFrame(records), use_container_width=True, height=220)
        except Exception as e:
            st.error(f"Could not read Excel file: {e}")
    card_end()

    card_start("Certificate template", "PNG, JPG, or PDF â€” the name is drawn centered on top of this image.")
    template_file = st.file_uploader("Certificate template", type=["png", "jpg", "jpeg", "pdf"], label_visibility="collapsed")

    if template_file:
        template_path = os.path.join(OUTPUT_DIR, f"template{os.path.splitext(template_file.name)[1]}")
        with open(template_path, "wb") as f:
            f.write(template_file.getbuffer())
        st.session_state.template_path = template_path

        fingerprint = (template_file.name, template_file.size)
        is_new_template = fingerprint != st.session_state.template_fingerprint

        template_img = load_template_as_image(template_path)

        if is_new_template:
            st.session_state.template_fingerprint = fingerprint
            # Auto-detect a blank band on the template first (fixes the name
            # landing on top of printed text like "has successfully
            # participated in..."), then tune font size/color for that spot.
            suggested_y = suggest_name_position(template_img)
            suggested_size, suggested_color = suggest_text_style(template_img, suggested_y)
            st.session_state.y_pos_pct = int(round(suggested_y * 100))
            st.session_state.font_size = suggested_size
            st.session_state.text_color_hex = "#%02x%02x%02x" % suggested_color
            st.session_state.confirmed_params = None
            st.markdown('<span class="dv-badge dv-badge-ok">âœ“ Template uploaded â€” name placement auto-detected</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="dv-badge dv-badge-ok">âœ“ Template uploaded</span>', unsafe_allow_html=True)

        with st.expander("ðŸŽ¨ Customize name placement, size & color", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                font_size = st.slider("Font size (px)", 20, 300, key="font_size")
                y_pos = st.slider("Vertical position (% down)", 0, 100, key="y_pos_pct") / 100.0
            with c2:
                color_hex = st.color_picker("Text color", key="text_color_hex")
                if st.button("â†º Auto-fit to this template"):
                    s_y = suggest_name_position(template_img)
                    s_size, s_color = suggest_text_style(template_img, s_y)
                    st.session_state.y_pos_pct = int(round(s_y * 100))
                    st.session_state.font_size = s_size
                    st.session_state.text_color_hex = "#%02x%02x%02x" % s_color
                    st.session_state.confirmed_params = None
                    st.rerun()

        font_size = st.session_state.font_size
        y_pos = st.session_state.y_pos_pct / 100.0
        color_hex = st.session_state.text_color_hex
        text_color = tuple(int(color_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))

        if st.session_state.records:
            sample_name = st.session_state.records[0]["Name"]
            preview_img = render_certificate_image(
                template_img, sample_name, None, font_size, text_color, y_pos
            )
            st.image(preview_img, caption=f"Live preview â€” {sample_name}", use_container_width=True)

            current_params = (fingerprint, font_size, round(y_pos, 3), color_hex)
            confirmed = st.checkbox(
                "âœ… I can clearly see the name above on the certificate",
                value=(st.session_state.confirmed_params == current_params),
            )
            if confirmed:
                st.session_state.confirmed_params = current_params
            elif st.session_state.confirmed_params == current_params:
                st.session_state.confirmed_params = None
        else:
            st.info("Upload the participant list above to preview a sample name on this template.")
    card_end()

# ---------------------------------------------------------------------------
# TAB 2 â€” Generate Certificates
# ---------------------------------------------------------------------------
with tab2:
    card_start("Generate certificates")

    records = st.session_state.records
    template_path = st.session_state.template_path

    c1, c2, c3 = st.columns(3)
    c1.metric("Total records", len(records))
    c2.metric("Template ready", "Yes" if template_path else "No")
    c3.metric("Certificates generated", len(st.session_state.cert_paths))

    fingerprint = st.session_state.template_fingerprint
    font_size = st.session_state.font_size
    y_pos = st.session_state.y_pos_pct / 100.0
    color_hex = st.session_state.text_color_hex
    text_color = tuple(int(color_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    current_params = (fingerprint, font_size, round(y_pos, 3), color_hex)
    preview_confirmed = st.session_state.confirmed_params == current_params and fingerprint is not None

    disabled = not (records and template_path)
    if disabled:
        st.info("Upload both the participant list and the certificate template in Step â‘  first.")
    elif not preview_confirmed:
        st.warning("Go back to Step â‘  and confirm the name preview looks correct before generating in bulk.")

    if st.button("ðŸŽ“  Generate Certificates", disabled=disabled or not preview_confirmed, key="btn_generate"):
        template_img = load_template_as_image(template_path)
        progress = st.progress(0, text="Starting...")
        used_names = {}
        cert_paths = {}
        for i, rec in enumerate(records):
            name = rec["Name"]
            try:
                path = generate_certificate(
                    template_img, name, CERT_DIR,
                    font_path=None, font_size=font_size,
                    text_color=text_color, y_position_pct=y_pos,
                    used_names=used_names,
                )
                cert_paths[name] = path
            except Exception as e:
                cert_paths[name] = None
                log_event(rec.get("Email ID", ""), "CERT_GENERATION_FAILED", str(e))
            progress.progress((i + 1) / len(records), text=f"Generating {i+1} of {len(records)} â€” {name}")
        st.session_state.cert_paths = cert_paths
        progress.empty()
        ok_count = sum(1 for v in cert_paths.values() if v)
        st.success(f"Done â€” {ok_count} of {len(records)} certificates generated.")

    if st.session_state.cert_paths:
        st.markdown("**Review**")
        review_df = pd.DataFrame(
            [{"Name": n, "Certificate Generated": "Yes" if p else "No"}
             for n, p in st.session_state.cert_paths.items()]
        )
        st.dataframe(review_df, use_container_width=True, height=220)

        sample_paths = [p for p in st.session_state.cert_paths.values() if p]
        if sample_paths:
            with st.expander("ðŸ” Preview a generated certificate"):
                st.image(load_template_as_image(sample_paths[0]), use_container_width=True)
    card_end()

# ---------------------------------------------------------------------------
# TAB 3 â€” Send Certificates
# ---------------------------------------------------------------------------
with tab3:
    card_start("Compose email")

    subject = st.text_input("Subject", "Congratulations! Your Certificate is Ready")
    body_template = st.text_area(
        "Body (use {{Name}} to insert the participant's name)",
        value=(
            "Dear {{Name}},\n\n"
            "Thank you for participating in our program.\n"
            "Please find your certificate attached to this email.\n\n"
            "We appreciate your participation and wish you all the best for your "
            "future endeavors.\n\n"
            "Regards,\nDV Analytics Team"
        ),
        height=200,
    )
    card_end()

    card_start("Send")
    records = st.session_state.records
    cert_paths = st.session_state.cert_paths

    total = len(records)
    sent_count = sum(1 for r in st.session_state.results if r.get("Email Sent") == "Yes")
    failed_count = sum(1 for r in st.session_state.results if r.get("Email Sent") == "No")
    pending_count = total - sent_count - failed_count

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Records", total)
    m2.metric("Sent Successfully", sent_count)
    m3.metric("Failed", failed_count)
    m4.metric("Pending", max(pending_count, 0))

    can_send = bool(records) and bool(cert_paths) and SMTPConfig().is_configured()
    if not records or not cert_paths:
        st.info("Generate certificates in Step â‘¡ before sending.")
    elif not SMTPConfig().is_configured():
        st.warning("SMTP is not configured â€” see the sidebar.")

    if st.button("âœ‰ï¸  Send Certificates", disabled=not can_send, key="btn_send"):
        progress = st.progress(0, text="Starting...")
        results = []
        sender = EmailSender()
        try:
            sender.connect()
        except Exception as e:
            st.error(f"Could not connect to SMTP server: {e}")
            sender = None

        for i, rec in enumerate(records):
            name = rec["Name"]
            mobile = rec.get("Mobile Number", "")
            email = rec.get("Email ID", "")
            cert_path = cert_paths.get(name)
            row = {
                "Name": name,
                "Mobile Number": mobile,
                "Email ID": email,
                "Certificate Generated": "Yes" if cert_path else "No",
                "Email Sent": "No",
                "Sent Date & Time": "",
                "Error Message": "",
            }

            progress.progress((i + 1) / total, text=f"Sending {i+1} of {total} â€” {name}")

            if not cert_path:
                row["Error Message"] = "Certificate not generated"
                log_event(email, "SKIPPED", "Certificate not generated")
                results.append(row)
                continue
            if not is_valid_email(email):
                row["Error Message"] = "Invalid email address"
                log_event(email, "FAILED", "Invalid email address")
                results.append(row)
                continue
            if sender is None:
                row["Error Message"] = "SMTP connection unavailable"
                results.append(row)
                continue

            personalized_body = body_template.replace("{{Name}}", name)
            try:
                sender.send(email, subject, personalized_body, cert_path)
                row["Email Sent"] = "Yes"
                row["Sent Date & Time"] = now_str()
                log_event(email, "SENT")
            except Exception as e:
                row["Error Message"] = str(e)
                log_event(email, "FAILED", str(e))

            results.append(row)

        if sender is not None:
            sender.close()

        st.session_state.results = results
        progress.empty()

        report_df = build_report_dataframe(results)
        report_df.to_excel(REPORT_PATH, index=False)
        errors_df = report_df[report_df["Error Message"] != ""]
        errors_df.to_excel(ERROR_REPORT_PATH, index=False)

        n_sent = sum(1 for r in results if r["Email Sent"] == "Yes")
        st.success(f"Done â€” {n_sent} of {total} emails sent successfully.")
        st.rerun()
    card_end()

# ---------------------------------------------------------------------------
# TAB 4 â€” Report & Dashboard
# ---------------------------------------------------------------------------
with tab4:
    card_start("Dashboard")

    records = st.session_state.records
    cert_paths = st.session_state.cert_paths
    results = st.session_state.results

    total = len(records)
    certs_generated = sum(1 for v in cert_paths.values() if v)
    emails_sent = sum(1 for r in results if r.get("Email Sent") == "Yes")
    emails_failed = sum(1 for r in results if r.get("Email Sent") == "No")
    success_rate = f"{(emails_sent / total * 100):.1f}%" if total else "0.0%"

    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("Total Participants", total)
    d2.metric("Certificates Generated", certs_generated)
    d3.metric("Emails Sent", emails_sent)
    d4.metric("Failed Emails", emails_failed)
    d5.metric("Success Rate", success_rate)
    card_end()

    card_start("Downloads")
    dl1, dl2, dl3, dl4 = st.columns(4)

    with dl1:
        if cert_paths and any(cert_paths.values()):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, path in cert_paths.items():
                    if path and os.path.exists(path):
                        zf.write(path, arcname=os.path.basename(path))
            st.download_button("â¬‡ï¸ Certificates (.zip)", buf.getvalue(), file_name="Certificates.zip", mime="application/zip")
        else:
            st.button("â¬‡ï¸ Certificates (.zip)", disabled=True)

    with dl2:
        if os.path.exists(REPORT_PATH):
            with open(REPORT_PATH, "rb") as f:
                st.download_button("â¬‡ï¸ Email Report", f.read(), file_name="Email_Sending_Report.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.button("â¬‡ï¸ Email Report", disabled=True)

    with dl3:
        if os.path.exists(ERROR_REPORT_PATH):
            with open(ERROR_REPORT_PATH, "rb") as f:
                st.download_button("â¬‡ï¸ Error Report", f.read(), file_name="Error_Report.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.button("â¬‡ï¸ Error Report", disabled=True)

    with dl4:
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, "rb") as f:
                st.download_button("â¬‡ï¸ Log File", f.read(), file_name="email_log.txt")
        else:
            st.button("â¬‡ï¸ Log File", disabled=True)
    card_end()

    if results:
        card_start("Full report")
        st.dataframe(build_report_dataframe(results), use_container_width=True, height=320)
        card_end()
