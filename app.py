import streamlit as st
import pandas as pd
import base64
import re
from io import BytesIO
from datetime import date
from typing import Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError

# PDF (ReportLab)
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# -----------------------------
# CONFIG
# -----------------------------
st.set_page_config(page_title="DFU-VA | Payslip Analysis", layout="wide")

# Login (requested)
APP_USERNAME = "admin"
APP_PASSWORD = "Dfu-va@admin"

# Default Google Sheets (your links)
DEFAULT_LEADS_URL = "https://docs.google.com/spreadsheets/d/1KLWWiqYsOv0O7DVxfS0XOoFoe8xr-4NT-ZQYSKGz2bk/edit?usp=sharing"
DEFAULT_HOURS_URL = "https://docs.google.com/spreadsheets/d/1MTYPVo02kTc2fLsBpkt1ZAXBjLjAnOUIPn05aEigIiU/edit?usp=sharing"

# Branding
DFU_RED = "#E30613"
BG_APP = "#FAFAFB"
BG_LOGIN = "#FDECEF"   # pinkish (for logo visibility)
TEXT = "#111827"
MUTED = "#6B7280"
BORDER = "rgba(17,24,39,0.08)"
CARD_BG = "#FFFFFF"

# -----------------------------
# Helpers
# -----------------------------
def img_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def safe_lower(x) -> str:
    return str(x).strip().lower()

def format_num(x, decimals=2):
    try:
        return f"{float(x):.{decimals}f}"
    except Exception:
        return str(x)

def parse_duration_to_hours(val) -> float:
    """
    Converts strings like:
      "42 hours 35 min.", "9 min. 44 s.", "34 s.", "1 hour 2 min."
    into hours (float).
    """
    if pd.isna(val):
        return 0.0
    s = str(val).strip().lower()
    if s in ("-", "na", "n/a", ""):
        return 0.0

    hours = mins = secs = 0
    h = re.search(r"(\d+)\s*hour", s)
    m = re.search(r"(\d+)\s*min", s)
    sec = re.search(r"(\d+)\s*s", s)

    if h:
        hours = int(h.group(1))
    if m:
        mins = int(m.group(1))
    if sec:
        secs = int(sec.group(1))

    return float(hours + mins / 60.0 + secs / 3600.0)

def pick_sheet(xlsx_bytes: bytes, preferred_name: str):
    try:
        xl = pd.ExcelFile(BytesIO(xlsx_bytes))
        return preferred_name if preferred_name in xl.sheet_names else xl.sheet_names[0]
    except Exception:
        return 0

def extract_google_sheet_id(url: str) -> Optional[str]:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    return m.group(1) if m else None

def download_google_sheet_xlsx(sheet_url: str) -> bytes:
    """
    Downloads a public Google Sheet as XLSX bytes.
    The sheet must be shared/accessible.
    """
    sheet_id = extract_google_sheet_id(sheet_url)
    if not sheet_id:
        raise ValueError("Invalid Google Sheets URL.")

    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    req = Request(export_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req) as resp:
            return resp.read()
    except URLError as e:
        raise RuntimeError("Could not download sheet. Check sharing permissions.") from e

# -----------------------------
# PDF Builder
# -----------------------------
def build_pdf_report(
    logo_path: Optional[str],
    agent_name: str,
    agent_id: str,
    login_id: str,
    start_date,
    end_date,
    cutoff_hour: int,
    lead_summary_df: pd.DataFrame,
    snapshot_df: pd.DataFrame
) -> bytes:
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.4 * cm,
        rightMargin=1.4 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm
    )

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=colors.HexColor(TEXT),
        spaceAfter=4,
    )
    subtitle = ParagraphStyle(
        "subtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor(MUTED),
        spaceAfter=10,
        leading=14,
    )
    h2 = ParagraphStyle(
        "h2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=colors.HexColor(DFU_RED),
        spaceAfter=6,
    )
    small = ParagraphStyle(
        "small",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor(MUTED),
        spaceAfter=6,
    )

    def draw_bg(canv: canvas.Canvas, _doc):
        canv.saveState()
        canv.setFillColor(colors.HexColor("#FDECEF"))  # light pink background
        w, h = A4
        canv.rect(0, 0, w, h, fill=1, stroke=0)
        canv.restoreState()

    elements = []

    # Logo (safe size + keep aspect ratio)
    logo_cell = ""
    if logo_path:
        try:
            ir = ImageReader(logo_path)
            iw, ih = ir.getSize()
            target_w = 4.0 * cm
            target_h = (ih / float(iw)) * target_w
            max_h = 1.6 * cm
            if target_h > max_h:
                target_h = max_h
                target_w = (iw / float(ih)) * target_h
            logo_cell = Image(logo_path, width=target_w, height=target_h)
        except Exception:
            logo_cell = ""

    header_right = [
        Paragraph("Payslip Analysis Report", title),
        Paragraph(
            f"Agent: <b>{agent_name}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Date Range: <b>{start_date}</b> → <b>{end_date}</b><br/>"
            f"Agent ID: <b>{agent_id or '-'}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Login ID: <b>{login_id or '-'}</b> &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Cutoff: <b>{cutoff_hour}:00</b> (before cutoff counts as previous day)",
            subtitle
        )
    ]

    header_table = Table([[logo_cell, header_right]], colWidths=[4.4 * cm, 13.6 * cm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(header_table)

    divider = Table([[""]], colWidths=[18 * cm])
    divider.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 2, colors.HexColor(DFU_RED)),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    elements.append(divider)

    # Lead Summary
    elements.append(Paragraph("Lead Summary", h2))
    lead_data = [list(lead_summary_df.columns)] + lead_summary_df.astype(str).values.tolist()
    lead_tbl = Table(lead_data, colWidths=[10.5 * cm, 7.5 * cm])
    lead_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(DFU_RED)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF7F8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(lead_tbl)
    elements.append(Spacer(1, 10))

    # Snapshot
    elements.append(Paragraph("Payroll Snapshot", h2))
    snap_data = [list(snapshot_df.columns)] + snapshot_df.astype(str).values.tolist()
    snap_tbl = Table(snap_data, colWidths=[7.5 * cm, 10.5 * cm])
    snap_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(TEXT)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF7F8")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(snap_tbl)

    elements.append(Spacer(1, 10))
    elements.append(Paragraph("DFU-VA Payslip Analysis", small))

    doc.build(elements, onFirstPage=draw_bg, onLaterPages=draw_bg)
    buffer.seek(0)
    return buffer.read()

# -----------------------------
# Data loading (cached) + refresh
# -----------------------------
@st.cache_data(ttl=300, show_spinner=False)
def load_data_from_google_sheets(
    leads_url: str,
    hours_url: str,
    cutoff_hour: int
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    leads_xlsx = download_google_sheet_xlsx(leads_url)
    hours_xlsx = download_google_sheet_xlsx(hours_url)

    payslip_sheet = pick_sheet(hours_xlsx, "Trial 1")
    leads_sheet = pick_sheet(leads_xlsx, "Leads Bank")

    pay = pd.read_excel(BytesIO(hours_xlsx), sheet_name=payslip_sheet)
    leads = pd.read_excel(BytesIO(leads_xlsx), sheet_name=leads_sheet)

    if "Name" not in pay.columns or "Day/date" not in pay.columns:
        raise ValueError("Hours sheet must contain columns: Name, Day/date")

    required_leads_cols = ["Timestamp", "Agent Name", "Lead Result", "Lead Status"]
    missing = [c for c in required_leads_cols if c not in leads.columns]
    if missing:
        raise ValueError(f"Leads sheet is missing: {', '.join(missing)}")

    pay_daily = pay[pay["Day/date"] != "-"].copy()
    pay_daily["work_date"] = pd.to_datetime(pay_daily["Day/date"], errors="coerce").dt.date
    pay_daily = pay_daily[pay_daily["work_date"].notna()].copy()

    leads2 = leads.copy()
    leads2["Timestamp"] = pd.to_datetime(leads2["Timestamp"], errors="coerce")
    leads2 = leads2[leads2["Timestamp"].notna()].copy()
    leads2["work_date"] = (leads2["Timestamp"] - pd.Timedelta(hours=int(cutoff_hour))).dt.date

    return pay_daily, leads2, pay, leads

def hard_refresh():
    st.cache_data.clear()
    st.rerun()

# -----------------------------
# Assets
# -----------------------------
try:
    LOGO_B64 = img_to_base64("logo.png")
    LOGO_EXISTS = True
except Exception:
    LOGO_B64 = None
    LOGO_EXISTS = False

# -----------------------------
# CSS
# -----------------------------
def apply_css(is_login: bool):
    bg = BG_LOGIN if is_login else BG_APP

    # For login: center everything on screen (no blank scroll)
    login_block = """
    .block-container{
      max-width: 1100px !important;
      padding-top: 0.0rem !important;
      padding-bottom: 0.0rem !important;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    """ if is_login else """
    .block-container{
      padding-top: 0.8rem;
      max-width: 1180px;
      margin-left: auto;
      margin-right: auto;
    }
    """

    st.markdown(f"""
    <style>
      .stApp {{
        background: {bg};
      }}
      header[data-testid="stHeader"] {{
        background: transparent;
      }}

      {login_block}

      /* Inputs look */
      div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {{
        border-radius: 14px !important;
      }}

      /* Buttons */
      .stButton button, .stDownloadButton button {{
        border-radius: 14px !important;
        padding: 0.70rem 1.0rem !important;
        font-weight: 900 !important;
        border: 1px solid {BORDER} !important;
      }}
      .stDownloadButton button {{
        background: {DFU_RED} !important;
        color: white !important;
        border: none !important;
      }}
      .stDownloadButton button:hover {{
        filter: brightness(0.96);
      }}

      /* Cards */
      .card {{
        background: {CARD_BG};
        border: 1px solid {BORDER};
        border-radius: 20px;
        padding: 16px 16px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.05);
      }}
      .card-title {{
        font-size: 14px;
        font-weight: 950;
        color: {TEXT};
        margin: 0 0 10px 0;
      }}

      /* Top bar */
      .topbar {{
        background: linear-gradient(90deg, rgba(227,6,19,0.10), rgba(227,6,19,0.03));
        border: 1px solid {BORDER};
        border-radius: 22px;
        padding: 16px 18px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 14px;
      }}
      .brand {{
        display:flex;
        align-items:center;
        gap: 12px;
      }}
      .brand h1 {{
        font-size: 22px;
        margin: 0;
        color: {TEXT};
        font-weight: 950;
      }}
      .brand p {{
        margin: 0;
        color: {MUTED};
        font-size: 12px;
      }}

      /* LOGIN: style the form as a real card */
     div[data-testid="stForm"] {{
  width: min(980px, 96vw);
  background: linear-gradient(180deg, rgba(255,230,234,0.95) 0%, rgba(255,243,245,0.95) 100%);
  border: 1px solid rgba(227,6,19,0.18);
  border-radius: 26px;
  padding: 22px 22px;
  box-shadow: 0 18px 48px rgba(0,0,0,0.08);
}}


      .login-head {{
        display:flex;
        align-items:center;
        gap: 14px;
        margin-bottom: 12px;
      }}
      .login-title {{
        margin: 0;
        font-size: 20px;
        font-weight: 950;
        color: {TEXT};
      }}
      .login-sub {{
        margin: 3px 0 0 0;
        font-size: 12px;
        color: {MUTED};
      }}

      hr {{
        border: none;
        border-top: 1px solid {BORDER};
        margin: 14px 0;
      }}
    </style>
    """, unsafe_allow_html=True)

# -----------------------------
# Auth
# -----------------------------
if "authed" not in st.session_state:
    st.session_state.authed = False

def login_screen():
    apply_css(is_login=True)

    logo_html = (
        f'<img src="data:image/png;base64,{LOGO_B64}" style="height:52px;width:auto;" />'
        if LOGO_B64 else ""
    )

    # Everything inside ONE form => one centered card => no blank page / no scrolling to find inputs
    with st.form("login_form", clear_on_submit=False):
        st.markdown(f"""
        <div class="login-head">
          {logo_html}
          <div>
            <p class="login-title">Secure Login</p>
            <p class="login-sub">DFU-VA Payslip Analysis Portal</p>
          </div>
        </div>
        <hr/>
        """, unsafe_allow_html=True)

        c1, c2 = st.columns([1, 1])
        with c1:
            u = st.text_input("Username", key="login_user")
        with c2:
            p = st.text_input("Password", type="password", key="login_pass")

        b1, b2 = st.columns([1, 1])
        with b1:
            sign_in = st.form_submit_button("Sign in", use_container_width=True)
        with b2:
            clear = st.form_submit_button("Clear", use_container_width=True)

    if clear:
        st.session_state.login_user = ""
        st.session_state.login_pass = ""
        st.rerun()

    if sign_in:
        if u == APP_USERNAME and p == APP_PASSWORD:
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("Invalid credentials.")

if not st.session_state.authed:
    login_screen()
    st.stop()

# -----------------------------
# Main UI
# -----------------------------
apply_css(is_login=False)

logo_html_small = (
    f'<img src="data:image/png;base64,{LOGO_B64}" style="height:38px;width:auto;" />'
    if LOGO_B64 else ""
)
st.markdown(f"""
<div class="topbar">
  <div class="brand">
    {logo_html_small}
    <div>
      <h1>Payslip Analysis</h1>
      <p>Reports & KPIs</p>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# Controls row
ctrl_l, ctrl_r = st.columns([1, 1])
with ctrl_l:
    if st.button("Refresh data"):
        hard_refresh()
with ctrl_r:
    if st.button("Logout"):
        st.session_state.authed = False
        st.rerun()

# Sidebar settings
with st.sidebar:
    st.markdown("### Data Sources")
    leads_url = st.text_input("Leads Bank (Google Sheets URL)", value=DEFAULT_LEADS_URL)
    hours_url = st.text_input("Hours Data Bank (Google Sheets URL)", value=DEFAULT_HOURS_URL)

    st.markdown("### Rules")
    cutoff_hour = st.number_input("Cutoff hour (Cairo)", min_value=0, max_value=23, value=7)
    leads_target_per_day = st.number_input("Lead target / day", min_value=0, max_value=50, value=2)

    st.markdown("### Payroll")
    hours_target_per_day = st.number_input("Hours target / day", min_value=0.0, max_value=24.0, value=8.0, step=0.5)
    hourly_rate = st.number_input("Hourly rate", min_value=0.0, max_value=1000.0, value=0.0, step=0.5)

    st.markdown("---")
    if st.button("Force refresh now", use_container_width=True):
        hard_refresh()

# Load data
try:
    pay_daily, leads2, raw_pay, raw_leads = load_data_from_google_sheets(
        leads_url=leads_url.strip(),
        hours_url=hours_url.strip(),
        cutoff_hour=int(cutoff_hour),
    )
except Exception as e:
    st.error(str(e))
    st.stop()

# Date defaults from both sheets
pay_min = pay_daily["work_date"].min() if len(pay_daily) else None
pay_max = pay_daily["work_date"].max() if len(pay_daily) else None
lead_min = leads2["work_date"].min() if len(leads2) else None
lead_max = leads2["work_date"].max() if len(leads2) else None

candidates_min = [d for d in [pay_min, lead_min] if d is not None and not pd.isna(d)]
candidates_max = [d for d in [pay_max, lead_max] if d is not None and not pd.isna(d)]
default_min = min(candidates_min) if candidates_min else date.today()
default_max = max(candidates_max) if candidates_max else date.today()

# Selection controls
agents_pay = sorted(pay_daily["Name"].dropna().astype(str).str.strip().unique().tolist())
if not agents_pay:
    st.error("No agent names found in Hours Data Bank.")
    st.stop()

agent_name = st.selectbox("Agent Name", agents_pay)

date_range = st.date_input("Date Range", value=(default_min, default_max))
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date = date_range
    end_date = date_range

if start_date > end_date:
    st.error("Start date must be before end date.")
    st.stop()

lead_agents = sorted(leads2["Agent Name"].dropna().astype(str).unique().tolist())
if not lead_agents:
    st.error("No agent names found in Leads Bank.")
    st.stop()

first2 = " ".join(str(agent_name).split()[:2]).strip().lower()
auto_matches = [a for a in lead_agents if safe_lower(a).startswith(first2)]
default_lead_agent = auto_matches[0] if auto_matches else lead_agents[0]

lead_agent_choice = st.selectbox("Leads Agent Name", options=lead_agents, index=lead_agents.index(default_lead_agent))

# Filter payslip rows
pay_f = pay_daily[
    (pay_daily["Name"].astype(str).str.strip() == str(agent_name).strip())
    & (pay_daily["work_date"] >= start_date)
    & (pay_daily["work_date"] <= end_date)
].copy()

working_days = int(pay_f["work_date"].nunique()) if len(pay_f) else 0
logged_hours = float(pay_f["Logged Time"].apply(parse_duration_to_hours).sum()) if "Logged Time" in pay_f.columns else 0.0
payable_hours = float(pay_f["Payable (t)"].apply(parse_duration_to_hours).sum()) if "Payable (t)" in pay_f.columns else logged_hours
unpayable_hours = float(pay_f["Unpayable (t)"].apply(parse_duration_to_hours).sum()) if "Unpayable (t)" in pay_f.columns else 0.0

agent_id = str(pay_f["User ID"].dropna().iloc[0]) if "User ID" in pay_f.columns and len(pay_f["User ID"].dropna()) else ""
login_id = str(pay_f["Login ID"].dropna().iloc[0]) if "Login ID" in pay_f.columns and len(pay_f["Login ID"].dropna()) else ""

# Filter leads rows
leads_f = leads2[
    (leads2["Agent Name"].astype(str) == str(lead_agent_choice))
    & (leads2["work_date"] >= start_date)
    & (leads2["work_date"] <= end_date)
].copy()

qualified_leads = int((leads_f["Lead Result"].apply(safe_lower) == "qualified").sum())
disqualified_leads = int((leads_f["Lead Result"].apply(safe_lower) == "disqualified").sum())
callbacks = int((leads_f["Lead Result"].apply(safe_lower) == "call back").sum())
above_market = int((leads_f["Case"].apply(safe_lower) == "above market value").sum()) if "Case" in leads_f.columns else 0

payable_leads = int((
    (leads_f["Lead Result"].apply(safe_lower) == "qualified")
    & (leads_f["Lead Status"].apply(safe_lower) == "pushed to client")
).sum())

leads_target = working_days * int(leads_target_per_day)
target_met = (payable_leads >= leads_target) if working_days > 0 else False

hours_target = working_days * float(hours_target_per_day)
total_pay = payable_hours * float(hourly_rate) if hourly_rate and hourly_rate > 0 else None

lead_summary = pd.DataFrame({
    "Metric": [
        "Qualified Leads",
        "Disqualified Leads",
        "Call Backs",
        "Above Market Value",
        "Payable Leads"
    ],
    "Value": [qualified_leads, disqualified_leads, callbacks, above_market, payable_leads]
})

snapshot = pd.DataFrame({
    "Field": [
        "Agent ID", "Agent Name", "Login ID",
        "Date Range", "Working Days",
        "Leads Target", "Leads Achieved", "Target Met",
        "Hours Target", "Hours Achieved", "Unpayable Hours",
        "Hourly Rate", "Grand Total"
    ],
    "Value": [
        agent_id or "-", agent_name, login_id or "-",
        f"{start_date} → {end_date}", working_days,
        leads_target, payable_leads, "YES" if target_met else "NO",
        format_num(hours_target),
        format_num(payable_hours),
        format_num(unpayable_hours),
        "-" if not hourly_rate else format_num(hourly_rate),
        "-" if total_pay is None else format_num(total_pay)
    ]
})

# KPIs
k1, k2, k3, k4 = st.columns(4)
k1.metric("Working Days", working_days)
k2.metric("Payable Leads", payable_leads)
k3.metric("Lead Target", leads_target)
k4.metric("Target Met", "YES" if target_met else "NO")

grid = st.columns(2)
with grid[0]:
    st.markdown('<div class="card"><p class="card-title">Lead Summary</p>', unsafe_allow_html=True)
    st.dataframe(lead_summary, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

with grid[1]:
    st.markdown('<div class="card"><p class="card-title">Hours Summary</p>', unsafe_allow_html=True)
    h = st.columns(3)
    h[0].metric("Payable Hours", format_num(payable_hours))
    h[1].metric("Logged Hours", format_num(logged_hours))
    h[2].metric("Unpayable Hours", format_num(unpayable_hours))
    st.markdown("</div>", unsafe_allow_html=True)

st.markdown('<div class="card"><p class="card-title">Payroll Snapshot</p>', unsafe_allow_html=True)
st.dataframe(snapshot, use_container_width=True, hide_index=True)
st.markdown("</div>", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["Hours Rows", "Lead Rows", "Download PDF"])

with tab1:
    st.markdown('<div class="card"><p class="card-title">Hours Rows (selected)</p>', unsafe_allow_html=True)
    st.dataframe(pay_f, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

with tab2:
    st.markdown('<div class="card"><p class="card-title">Lead Rows (selected)</p>', unsafe_allow_html=True)
    st.dataframe(leads_f, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

with tab3:
    st.markdown('<div class="card"><p class="card-title">PDF Report</p>', unsafe_allow_html=True)

    pdf_bytes = build_pdf_report(
        logo_path="logo.png" if LOGO_EXISTS else None,
        agent_name=agent_name,
        agent_id=agent_id,
        login_id=login_id,
        start_date=start_date,
        end_date=end_date,
        cutoff_hour=int(cutoff_hour),
        lead_summary_df=lead_summary,
        snapshot_df=snapshot
    )

    st.download_button(
        "Download PDF",
        data=pdf_bytes,
        file_name=f"Payslip_Report_{agent_name.replace(' ', '_')}_{start_date}_{end_date}.pdf",
        mime="application/pdf"
    )

    st.markdown("</div>", unsafe_allow_html=True)
