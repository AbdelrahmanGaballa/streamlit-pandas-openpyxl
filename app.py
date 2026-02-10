import streamlit as st
import pandas as pd
import base64
import re
from io import BytesIO
from datetime import date, datetime
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

# PDF imports
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# =============================
# CONFIG
# =============================
st.set_page_config(
    page_title="DFU-VA | Payslip Analysis",
    layout="wide",
    initial_sidebar_state="expanded"
)

APP_USERNAME = "admin"
APP_PASSWORD = "Dfu-va@admin"
DEFAULT_LEADS_URL = "https://docs.google.com/spreadsheets/d/1KLWWiqYsOv0O7DVxfS0XOoFoe8xr-4NT-ZQYSKGz2bk/edit?usp=sharing"

# =============================
# HELPER FUNCTIONS
# =============================

def safe_lower(x) -> str:
    return str(x).strip().lower()

def format_num(x, decimals=2):
    try:
        return f"{float(x):.{decimals}f}"
    except Exception:
        return str(x)

def parse_duration_to_hours(val) -> float:
    """Parse duration strings like '8 hours 56 min. 10 s.' to float hours"""
    if pd.isna(val):
        return 0.0
    s = str(val).strip().lower()
    if s in ("-", "na", "n/a", ""):
        return 0.0
    
    hours = mins = secs = 0
    mh = re.search(r"(\d+)\s*hour", s)
    if mh:
        hours = int(mh.group(1))
    mm = re.search(r"(\d+)\s*min", s)
    if mm:
        mins = int(mm.group(1))
    ms = re.search(r"(\d+)\s*(s|sec)", s)
    if ms:
        secs = int(ms.group(1))
    
    return float(hours + mins / 60.0 + secs / 3600.0)

def is_date_value(val) -> bool:
    """Check if a value looks like a date"""
    if pd.isna(val):
        return False
    
    # If it's already a datetime
    if isinstance(val, (datetime, pd.Timestamp)):
        return True
    
    # Try parsing as string
    s = str(val).strip()
    if not s or s == "-":
        return False
    
    # Check for date patterns
    date_patterns = [
        r'^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$',  # 1/1/2026 or 01-01-2026
        r'^\d{1,2}-[A-Za-z]{3}$',  # 5-Jan
        r'^[A-Za-z]{3}-\d{1,2}$',  # Jan-5
    ]
    
    for pattern in date_patterns:
        if re.match(pattern, s):
            return True
    
    # Try parsing with pandas
    try:
        pd.to_datetime(s)
        return True
    except:
        return False

def find_total_row(agent_df: pd.DataFrame) -> Optional[pd.Series]:
    """
    Super robust TOTAL row detection.
    Tries multiple methods in order of reliability.
    """
    if len(agent_df) == 0:
        return None
    
    st.write("🔍 **Searching for TOTAL row...**")
    
    # Method 1: Day/date is exactly "-"
    if "Day/date" in agent_df.columns:
        candidates = agent_df[agent_df["Day/date"].astype(str).str.strip() == "-"]
        if len(candidates) > 0:
            st.success(f"✅ Method 1: Found TOTAL row where Day/date = '-'")
            return candidates.iloc[-1]  # Take last if multiple
    
    # Method 2: Day/date is NaN or empty
    if "Day/date" in agent_df.columns:
        candidates = agent_df[
            agent_df["Day/date"].isna() | 
            (agent_df["Day/date"].astype(str).str.strip() == "")
        ]
        if len(candidates) > 0:
            st.success(f"✅ Method 2: Found TOTAL row where Day/date is empty/NaN")
            return candidates.iloc[-1]
    
    # Method 3: Days Work column is populated with high value
    if "Days Work" in agent_df.columns:
        days_work_numeric = pd.to_numeric(agent_df["Days Work"], errors="coerce")
        candidates = agent_df[days_work_numeric > 0]
        if len(candidates) > 0:
            # Take the row with the highest Days Work value (likely the total)
            max_idx = days_work_numeric.idxmax()
            if not pd.isna(max_idx):
                st.success(f"✅ Method 3: Found TOTAL row with Days Work = {days_work_numeric[max_idx]}")
                return agent_df.loc[max_idx]
    
    # Method 4: Last row has non-date Day/date value
    if "Day/date" in agent_df.columns:
        last_row = agent_df.iloc[-1]
        if not is_date_value(last_row["Day/date"]):
            st.success(f"✅ Method 4: Last row has non-date Day/date ('{last_row['Day/date']}')")
            return last_row
    
    # Method 5: Last row as fallback
    st.warning("⚠️ Method 5 (fallback): Using last row as TOTAL")
    return agent_df.iloc[-1]

def extract_working_days(total_row: pd.Series) -> int:
    """Extract working days from TOTAL row, trying multiple column names"""
    
    # Try different column names
    possible_columns = [
        "Days Work",
        "Days",
        "Working Days",
        "Work Days",
        "Days Worked",
        "Total Days"
    ]
    
    for col in possible_columns:
        if col in total_row.index:
            val = total_row[col]
            if pd.notna(val):
                try:
                    working_days = int(float(val))
                    if working_days > 0:
                        st.info(f"📊 Working Days found in column '{col}': {working_days}")
                        return working_days
                except:
                    pass
    
    st.error("❌ Could not find Working Days in any column!")
    return 0

def extract_google_sheet_id(url: str) -> Optional[str]:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    return m.group(1) if m else None

def download_google_sheet_xlsx(sheet_url: str) -> bytes:
    sheet_id = extract_google_sheet_id(sheet_url)
    if not sheet_id:
        raise ValueError("Invalid Google Sheets URL.")
    
    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    req = Request(export_url, headers={"User-Agent": "Mozilla/5.0"})
    
    with urlopen(req) as resp:
        return resp.read()

def read_agent_report(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        return pd.DataFrame()
    
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(uploaded_file)
    
    raise ValueError("Unsupported file type")

def pick_sheet(xlsx_bytes: bytes, preferred_name: str):
    try:
        xl = pd.ExcelFile(BytesIO(xlsx_bytes))
        return preferred_name if preferred_name in xl.sheet_names else xl.sheet_names[0]
    except Exception:
        return 0

@st.cache_data(ttl=300, show_spinner=False)
def load_leads_from_google_sheets(leads_url: str, cutoff_hour: int) -> pd.DataFrame:
    leads_xlsx = download_google_sheet_xlsx(leads_url)
    leads_sheet = pick_sheet(leads_xlsx, "Leads Bank")
    leads = pd.read_excel(BytesIO(leads_xlsx), sheet_name=leads_sheet)
    
    required_leads_cols = ["Timestamp", "Agent Name", "Lead Result"]
    missing = [c for c in required_leads_cols if c not in leads.columns]
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")
    
    leads2 = leads.copy()
    leads2["Timestamp"] = pd.to_datetime(leads2["Timestamp"], errors="coerce")
    leads2 = leads2[leads2["Timestamp"].notna()].copy()
    leads2["work_date"] = (leads2["Timestamp"] - pd.Timedelta(hours=int(cutoff_hour))).dt.date
    leads2["Agent Name"] = leads2["Agent Name"].astype(str).str.strip()
    
    if "Case" in leads2.columns:
        leads2["Case"] = leads2["Case"].astype(str)
    if "Pushed to Client" in leads2.columns:
        leads2["Pushed to Client"] = leads2["Pushed to Client"].astype(str).str.strip()
    
    return leads2

def build_pdf_report(
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
        leftMargin=1.4*cm, 
        rightMargin=1.4*cm,
        topMargin=1.2*cm,
        bottomMargin=1.2*cm
    )
    
    # Brand colors
    DFU_RED = colors.HexColor("#E30613")
    DFU_PINK_BG = colors.HexColor("#FDECEF")
    TEXT_DARK = colors.HexColor("#111827")
    TEXT_MUTED = colors.HexColor("#6B7280")
    BORDER_LIGHT = colors.HexColor("#E5E7EB")
    
    # Custom styles
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        textColor=DFU_RED,
        spaceAfter=6,
        alignment=0
    )
    
    subtitle_style = ParagraphStyle(
        "CustomSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=TEXT_MUTED,
        spaceAfter=12,
        leading=14
    )
    
    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=DFU_RED,
        spaceBefore=14,
        spaceAfter=8,
        borderPadding=4,
        leftIndent=0
    )
    
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        textColor=TEXT_MUTED,
        alignment=1  # Center
    )
    
    # Background and page decoration
    def draw_background(canvas, doc):
        canvas.saveState()
        # Light pink background
        canvas.setFillColor(DFU_PINK_BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        
        # Red top stripe
        canvas.setFillColor(DFU_RED)
        canvas.rect(0, A4[1] - 0.8*cm, A4[0], 0.8*cm, fill=1, stroke=0)
        
        # Footer line
        canvas.setStrokeColor(DFU_RED)
        canvas.setLineWidth(2)
        canvas.line(1.4*cm, 1.5*cm, A4[0] - 1.4*cm, 1.5*cm)
        
        canvas.restoreState()
    
    elements = []
    
    # Logo and Header
    logo_path = "dfu_logo.png"
    logo_exists = False
    try:
        from pathlib import Path
        if Path(logo_path).exists():
            logo_exists = True
    except:
        pass
    
    if logo_exists:
        try:
            from reportlab.lib.utils import ImageReader
            ir = ImageReader(logo_path)
            img_width, img_height = ir.getSize()
            
            # Scale logo to fit
            target_height = 1.2 * cm
            target_width = (img_width / img_height) * target_height
            
            logo_img = Image(logo_path, width=target_width, height=target_height)
            
            # Header table with logo and title
            header_content = [
                [logo_img, Paragraph("Payslip Analysis Report", title_style)]
            ]
            header_table = Table(header_content, colWidths=[4*cm, 14*cm])
            header_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (0, 0), 0),
                ('LEFTPADDING', (1, 0), (1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            elements.append(header_table)
        except Exception as e:
            # Fallback if logo fails
            elements.append(Paragraph("DFU-VA Payslip Analysis Report", title_style))
    else:
        elements.append(Paragraph("DFU-VA Payslip Analysis Report", title_style))
    
    # Agent info
    agent_info = f"""
    <b>Agent:</b> {agent_name}<br/>
    <b>Agent ID:</b> {agent_id or 'N/A'} | <b>Login ID:</b> {login_id or 'N/A'}<br/>
    <b>Period:</b> {start_date} to {end_date} | <b>Cutoff Hour:</b> {cutoff_hour}:00 (Cairo)
    """
    elements.append(Paragraph(agent_info, subtitle_style))
    
    # Divider
    divider_table = Table([[""]], colWidths=[18*cm])
    divider_table.setStyle(TableStyle([
        ('LINEBELOW', (0, 0), (-1, -1), 3, DFU_RED),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(divider_table)
    
    elements.append(Spacer(1, 8))
    
    # Lead Summary Section
    elements.append(Paragraph("📊 Lead Summary", heading_style))
    
    lead_data = [list(lead_summary_df.columns)] + lead_summary_df.astype(str).values.tolist()
    lead_table = Table(lead_data, colWidths=[10*cm, 8*cm])
    lead_table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), DFU_RED),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
        ('BOX', (0, 0), (-1, -1), 1.5, DFU_RED),
        
        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF7F8")]),
        
        # Padding
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(lead_table)
    
    elements.append(Spacer(1, 16))
    
    # Payroll Snapshot Section
    elements.append(Paragraph("💼 Payroll Snapshot", heading_style))
    
    snap_data = [list(snapshot_df.columns)] + snapshot_df.astype(str).values.tolist()
    snap_table = Table(snap_data, colWidths=[9*cm, 9*cm])
    snap_table.setStyle(TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), TEXT_DARK),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9.5),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
        ('BOX', (0, 0), (-1, -1), 1.5, DFU_RED),
        
        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF7F8")]),
        
        # Highlight important rows (Total Salary)
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#FFEBEE")),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, -1), (-1, -1), DFU_RED),
        
        # Padding
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    elements.append(snap_table)
    
    elements.append(Spacer(1, 20))
    
    # Footer
    footer_text = f"DFU-VA Payslip Analysis | Generated on {date.today().strftime('%B %d, %Y')}"
    elements.append(Paragraph(footer_text, footer_style))
    
    # Build PDF
    doc.build(elements, onFirstPage=draw_background, onLaterPages=draw_background)
    
    buffer.seek(0)
    return buffer.read()

# =============================
# CSS
# =============================
st.markdown("""
<style>
    .main-header {
        background-color: #E30613;
        padding: 1rem;
        border-radius: 8px;
        color: white;
        margin-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# =============================
# AUTHENTICATION
# =============================
if "authed" not in st.session_state:
    st.session_state.authed = False

if not st.session_state.authed:
    st.markdown("## 🔐 DFU-VA Payslip Analysis - Login")
    st.markdown("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter username")
            password = st.text_input("Password", type="password", placeholder="Enter password")
            
            col_a, col_b = st.columns(2)
            with col_a:
                login_btn = st.form_submit_button("🔓 Login", use_container_width=True)
            with col_b:
                clear_btn = st.form_submit_button("🗑️ Clear", use_container_width=True)
            
            if login_btn:
                if username == APP_USERNAME and password == APP_PASSWORD:
                    st.session_state.authed = True
                    st.rerun()
                else:
                    st.error("❌ Invalid credentials")
            
            if clear_btn:
                st.rerun()
    
    st.stop()

# =============================
# MAIN APP
# =============================
st.markdown('<div class="main-header"><h1>📊 DFU-VA Payslip Analysis</h1><p>Reports & KPIs Dashboard</p></div>', unsafe_allow_html=True)

col_ctrl1, col_ctrl2, col_ctrl3, col_ctrl4 = st.columns([1, 1, 1, 1])
with col_ctrl1:
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with col_ctrl4:
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.authed = False
        st.rerun()

st.markdown("---")

# =============================
# SIDEBAR
# =============================
with st.sidebar:
    st.header("⚙️ Configuration")
    
    st.subheader("📊 Leads Bank")
    leads_url = st.text_input("Google Sheets URL", value=DEFAULT_LEADS_URL)
    
    st.subheader("⏰ Cutoff Rule")
    cutoff_hour = st.number_input("Cutoff hour (Cairo)", min_value=0, max_value=23, value=7)
    
    st.subheader("📁 Agent Report")
    agent_file = st.file_uploader("Upload CSV or XLSX", type=["csv", "xlsx", "xls"])
    
    st.subheader("💰 Payroll Settings")
    hourly_rate = st.number_input("Hourly Rate", min_value=0.0, value=0.0, step=0.5)
    kpis_full_amount = st.number_input("Full KPIs Amount", min_value=0.0, value=0.0, step=10.0)
    agent_type = st.selectbox("Agent Type", ["Full-time", "Part-time"])

# =============================
# LOAD DATA
# =============================

with st.spinner("📥 Loading leads data..."):
    try:
        leads2 = load_leads_from_google_sheets(leads_url.strip(), int(cutoff_hour))
        st.success(f"✅ Loaded {len(leads2)} lead records")
    except Exception as e:
        st.error(f"❌ Error loading leads: {str(e)}")
        st.stop()

try:
    raw_pay = read_agent_report(agent_file)
except Exception as e:
    st.error(f"❌ Agent report error: {e}")
    st.stop()

if raw_pay.empty:
    st.warning("⚠️ Please upload an Agent Report file")
    st.stop()

required_pay_cols = ["Day/date", "Name"]
missing_pay = [c for c in required_pay_cols if c not in raw_pay.columns]
if missing_pay:
    st.error(f"❌ Missing columns: {', '.join(missing_pay)}")
    st.stop()

# =============================
# AGENT SELECTION
# =============================
st.subheader("👤 Select Agent")

agents_pay = sorted(raw_pay["Name"].dropna().astype(str).str.strip().unique().tolist())
agent_name = st.selectbox("Agent Name (from Report)", agents_pay, key="agent_select")

lead_agents = sorted(leads2["Agent Name"].dropna().astype(str).str.strip().unique().tolist())
if not lead_agents:
    st.error("❌ No agents found in leads data")
    st.stop()

first2 = " ".join(str(agent_name).split()[:2]).strip().lower()
auto_matches = [a for a in lead_agents if safe_lower(a).startswith(first2)]
default_lead_agent = auto_matches[0] if auto_matches else lead_agents[0]

lead_agent_choice = st.selectbox(
    "Agent Name (from Leads Bank)",
    options=lead_agents,
    index=lead_agents.index(default_lead_agent),
    key="lead_agent_select"
)

# =============================
# DATE RANGE
# =============================
st.subheader("📅 Select Date Range")

lead_min = leads2["work_date"].min() if len(leads2) else date.today()
lead_max = leads2["work_date"].max() if len(leads2) else date.today()

date_range = st.date_input("Date Range", value=(lead_min, lead_max))

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date = end_date = date_range

if start_date > end_date:
    st.error("❌ Start date must be before end date")
    st.stop()

st.markdown("---")

# =============================
# PROCESS DATA - IMPROVED
# =============================

pay_agent = raw_pay[raw_pay["Name"].astype(str).str.strip() == str(agent_name).strip()].copy()

st.write(f"📊 **Agent Data:** {len(pay_agent)} rows found")

# Show structure
with st.expander("🔍 View Agent Data Structure"):
    st.write(f"**Columns:** {list(pay_agent.columns)}")
    st.write(f"**First 3 Day/date values:** {pay_agent['Day/date'].head(3).tolist()}")
    st.write(f"**Last 3 Day/date values:** {pay_agent['Day/date'].tail(3).tolist()}")
    st.dataframe(pay_agent[["Day/date", "Name", "Days Work", "Logged Time", "Payable (t)", "Break (t)"]].tail(5) 
                 if all(c in pay_agent.columns for c in ["Days Work", "Logged Time", "Payable (t)", "Break (t)"]) 
                 else pay_agent.tail(5))

# Get agent IDs
agent_id = ""
login_id = ""
try:
    if "User ID" in pay_agent.columns and not pay_agent["User ID"].dropna().empty:
        agent_id = str(pay_agent["User ID"].dropna().iloc[0])
    if "Login ID" in pay_agent.columns and not pay_agent["Login ID"].dropna().empty:
        login_id = str(pay_agent["Login ID"].dropna().iloc[0])
except Exception:
    pass

# =============================
# FIND TOTAL ROW - ROBUST
# =============================

total_row = find_total_row(pay_agent)

if total_row is not None:
    with st.expander("📊 View TOTAL Row"):
        st.write(total_row.to_dict())
    
    # Extract working days
    working_days = extract_working_days(total_row)
    
    # Extract hours
    logged_hours = parse_duration_to_hours(total_row.get("Logged Time", 0))
    payable_hours_raw = parse_duration_to_hours(total_row.get("Payable (t)", 0))
    break_hours = parse_duration_to_hours(total_row.get("Break (t)", 0))
    
    # CRITICAL: Break time is NOT payable, so deduct it
    payable_hours = max(0.0, payable_hours_raw - break_hours)
    
    st.info(f"✅ **Extracted:** {working_days} days, {format_num(payable_hours_raw)} raw hours - {format_num(break_hours)} break = {format_num(payable_hours)} payable hours")
else:
    st.error("❌ Could not find TOTAL row!")
    working_days = 0
    logged_hours = 0.0
    payable_hours_raw = 0.0
    payable_hours = 0.0
    break_hours = 0.0

# =============================
# FILTER LEADS
# =============================

leads_f = leads2[
    (leads2["Agent Name"].astype(str).str.strip() == str(lead_agent_choice).strip()) &
    (leads2["work_date"] >= start_date) &
    (leads2["work_date"] <= end_date)
].copy()

qualified_leads = int((leads_f["Lead Result"].apply(safe_lower) == "qualified").sum())
disqualified_leads = int((leads_f["Lead Result"].apply(safe_lower) == "disqualified").sum())
callbacks = int((leads_f["Lead Result"].apply(safe_lower) == "call back").sum())

payable_leads = qualified_leads
pushed_present = "Pushed to Client" in leads_f.columns

if pushed_present:
    pushed_yes = leads_f["Pushed to Client"].apply(safe_lower).isin(["yes", "y", "true", "1", "pushed"])
    payable_leads = int(((leads_f["Lead Result"].apply(safe_lower) == "qualified") & pushed_yes).sum())

# =============================
# KPI CALCULATIONS
# =============================

target_per_day = 2.0 if agent_type == "Full-time" else 1.5
leads_target = working_days * target_per_day
performance_pct = (payable_leads / leads_target * 100.0) if leads_target > 0 else 0.0

if performance_pct < 60:
    tier = 0.0
elif performance_pct < 80:
    tier = 0.50
elif performance_pct < 100:
    tier = 0.80
else:
    tier = 1.0

kpi_bonus = float(kpis_full_amount) * tier
base_salary = float(hourly_rate) * float(payable_hours)
total_salary = base_salary + kpi_bonus

# =============================
# DISPLAY
# =============================

st.header("📊 Key Performance Indicators")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Working Days", working_days)
col2.metric("Payable Leads", payable_leads)
col3.metric("Lead Target", format_num(leads_target, 2))
col4.metric("KPI Tier", f"{int(tier*100)}%")

st.markdown("---")

st.subheader("📈 Lead Summary")
lead_summary = pd.DataFrame({
    "Metric": ["Qualified Leads", "Payable Leads", "Disqualified Leads", "Call Backs"],
    "Value": [qualified_leads, payable_leads, disqualified_leads, callbacks]
})
st.dataframe(lead_summary, use_container_width=True, hide_index=True)

st.subheader("⏱️ Hours Summary")
col_h1, col_h2, col_h3, col_h4 = st.columns(4)
col_h1.metric("Logged Hours", format_num(logged_hours))
col_h2.metric("Payable (Raw)", format_num(payable_hours_raw))
col_h3.metric("Break (Unpaid)", format_num(break_hours))
col_h4.metric("Payable (Net)", format_num(payable_hours))

st.markdown("---")

st.subheader("💼 Payroll Snapshot")

snapshot = pd.DataFrame({
    "Field": [
        "Agent Type", "Date Range", "Working Days", "Target / Day", "Leads Target",
        "Payable Leads", "Performance %", "KPI Tier", 
        "Logged Hours", "Payable Hours (Raw)", "Break Hours (Unpaid)", "Payable Hours (Net)",
        "Hourly Rate", "Base Salary (Hours × Rate)",
        "KPIs Amount (Full)", "KPIs Earned (Tier × Full)", "Total Salary (Base + KPIs)"
    ],
    "Value": [
        agent_type, f"{start_date} → {end_date}", str(working_days),
        format_num(target_per_day, 2), format_num(leads_target, 2),
        str(payable_leads), f"{format_num(performance_pct, 2)}%", f"{int(tier*100)}%",
        format_num(logged_hours), format_num(payable_hours_raw), format_num(break_hours), format_num(payable_hours),
        format_num(hourly_rate), format_num(base_salary), format_num(kpis_full_amount),
        format_num(kpi_bonus), format_num(total_salary)
    ]
})

if "snapshot_overrides" not in st.session_state:
    st.session_state.snapshot_overrides = {}

edited_snapshot = st.data_editor(
    snapshot,
    use_container_width=True,
    hide_index=True,
    disabled=["Field"],
    key="snapshot_editor"
)

st.session_state.snapshot_overrides = dict(zip(
    edited_snapshot["Field"].astype(str),
    edited_snapshot["Value"].astype(str)
))

if st.button("🔄 Reset Edits"):
    st.session_state.snapshot_overrides = {}
    st.rerun()

with st.expander("🧮 Salary Calculation Breakdown"):
    st.markdown(f"""
    **Hours Calculation:**
    - Logged Hours: {format_num(logged_hours)} hrs
    - Payable Hours (Raw): {format_num(payable_hours_raw)} hrs
    - Break Hours (Unpaid): {format_num(break_hours)} hrs
    - **Payable Hours (Net) = {format_num(payable_hours_raw)} - {format_num(break_hours)} = {format_num(payable_hours)} hrs**
    
    **Base Salary:**
    - Payable Hours (Net): {format_num(payable_hours)} hrs
    - Hourly Rate: ${format_num(hourly_rate)}
    - **Base Salary = {format_num(payable_hours)} × ${format_num(hourly_rate)} = ${format_num(base_salary)}**
    
    **KPI Bonus:**
    - Full KPIs Amount: ${format_num(kpis_full_amount)}
    - Performance: {format_num(performance_pct, 2)}%
    - KPI Tier: {int(tier*100)}%
    - **KPI Bonus = ${format_num(kpis_full_amount)} × {int(tier*100)}% = ${format_num(kpi_bonus)}**
    
    **Total Salary:**
    - **Total = ${format_num(base_salary)} + ${format_num(kpi_bonus)} = ${format_num(total_salary)}**
    """)

st.markdown("---")

tab1, tab2, tab3 = st.tabs(["📋 Agent Report", "📊 Lead Records", "📄 PDF Report"])

with tab1:
    st.dataframe(pay_agent, use_container_width=True)

with tab2:
    st.dataframe(leads_f, use_container_width=True)

with tab3:
    if st.button("📥 Generate PDF", use_container_width=True):
        try:
            with st.spinner("Generating PDF..."):
                pdf_bytes = build_pdf_report(
                    agent_name=agent_name,
                    agent_id=agent_id,
                    login_id=login_id,
                    start_date=start_date,
                    end_date=end_date,
                    cutoff_hour=int(cutoff_hour),
                    lead_summary_df=lead_summary,
                    snapshot_df=edited_snapshot
                )
            
            st.download_button(
                "📥 Download PDF",
                data=pdf_bytes,
                file_name=f"Payslip_{agent_name}_{start_date}_{end_date}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
            st.success("✅ PDF generated!")
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")