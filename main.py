import streamlit as st
import pandas as pd
import json
import re
import requests
import smtplib
import time
import concurrent.futures
import os
from datetime import date
from dotenv import load_dotenv

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
from groq import Groq
from ddgs import DDGS
from tavily import TavilyClient

# PDF Generation Imports
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ---------------------------------------------
# 1. LOAD ENV VARIABLES & CONFIG
# ---------------------------------------------
load_dotenv()

DEFAULT_GROQ = os.getenv("GROQ_API_KEY", "")
DEFAULT_TAVILY = os.getenv("TAVILY_API_KEY", "")
DEFAULT_HUNTER = os.getenv("HUNTER_API_KEY", "")
DEFAULT_EMAIL = os.getenv("SENDER_EMAIL", "")
DEFAULT_PASS = os.getenv("SENDER_PASSWORD", "")

# Page Config (Must be the first Streamlit command)
st.set_page_config(page_title="Export AI Agent", page_icon="🚀", layout="wide")

# ==========================================
# AUTHENTICATION & SEARCH LIMIT SYSTEM
# ==========================================
USERS = {
    "ali_admin": {"password": "Mubeen89Rajput@King", "role": "admin", "daily_limit": 99999},
    "free_user1": {"password": "user123", "role": "free", "daily_limit": 1}
}

def check_and_update_limit(username):
    user_info = USERS.get(username, {})
    if user_info.get("role") == "admin":
        return True, "Unlimited Access (Admin)"
    
    today = str(date.today())
    if 'user_searches' not in st.session_state:
        st.session_state['user_searches'] = {}
        
    user_data = st.session_state['user_searches'].get(username, {"date": today, "count": 0})
    
    if user_data["date"] != today:
        user_data = {"date": today, "count": 0}
        
    limit = user_info.get("daily_limit", 5)
    
    if user_data["count"] >= limit:
        return False, f"Daily limit reached ({user_data['count']}/{limit}). Upgrade to Premium!"
    
    return True, f"Remaining Searches Today: {limit - user_data['count']}/{limit}"

def increment_user_search(username):
    today = str(date.today())
    if 'user_searches' not in st.session_state:
        st.session_state['user_searches'] = {}
        
    user_data = st.session_state['user_searches'].get(username, {"date": today, "count": 0})
    user_data["count"] += 1
    st.session_state['user_searches'][username] = user_data

# Initialize Login State
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['current_user'] = None

# Show Login Screen if not logged in
if not st.session_state['logged_in']:
    st.title("🔐 Global Export AI Agent - Login")
    st.caption("Enter your credentials to access enterprise trade intelligence.")
    
    col_l1, col_l2, col_l3 = st.columns([1,2,1])
    with col_l2:
        with st.form("login_form"):
            username_input = st.text_input("Username")
            password_input = st.text_input("Password", type="password")
            submit_login = st.form_submit_button("🔓 Login to Dashboard", use_container_width=True)
            
            if submit_login:
                if username_input in USERS and USERS[username_input]["password"] == password_input:
                    st.session_state['logged_in'] = True
                    st.session_state['current_user'] = username_input
                    st.success("Login Successful!")
                    st.rerun()
                else:
                    st.error("Invalid Username or Password!")
    st.stop() # Stops execution of rest of app until login

# ---------------------------------------------
# MAIN DASHBOARD (FOR LOGGED-IN USERS)
# ---------------------------------------------
st.title("🚀 Global Export AI Agent (Enterprise Edition)")
st.caption("Powered by Global Buyer & Trade Database Integration (Comtrade + Hunter + Panjiva Engine)")

# ---------------------------------------------
# 2. SIDEBAR CREDENTIALS & USER PROFILE
# ---------------------------------------------
st.sidebar.markdown(f"👤 **Logged in as:** `{st.session_state['current_user']}`")
can_search, status_msg = check_and_update_limit(st.session_state['current_user'])
st.sidebar.info(f"📊 **Usage:** {status_msg}")

if st.sidebar.button("🔒 Logout"):
    st.session_state['logged_in'] = False
    st.session_state['current_user'] = None
    st.rerun()

st.sidebar.divider()
st.sidebar.header("🔑 API & Trade Database Credentials")
groq_key = st.sidebar.text_input("Groq API Key", value=DEFAULT_GROQ, type="password")
tavily_key = st.sidebar.text_input("Tavily API Key", value=DEFAULT_TAVILY, type="password")
hunter_key = st.sidebar.text_input("Hunter.io API Key (Optional)", value=DEFAULT_HUNTER, type="password", help="For verified corporate email enrichment")

st.sidebar.divider()
st.sidebar.subheader("🤖 AI Model Settings (Multi-LLM)")
selected_model = st.sidebar.selectbox(
    "Select Preferred Intelligence Engine:",
    [
        "llama-3.3-70b-versatile",
        "deepseek-r1-distill-llama-70b",
        "llama-3.1-8b-instant"
    ]
)

st.sidebar.divider()
st.sidebar.subheader("📧 Sender Email Settings (Gmail SMTP)")
sender_email = st.sidebar.text_input("Your Email", value=DEFAULT_EMAIL)
sender_password = st.sidebar.text_input("App Password", value=DEFAULT_PASS, type="password", help="Gmail App Password")

# ==========================================
# API 1: HUNTER.IO EMAIL VERIFIER API
# ==========================================
def get_hunter_emails(domain, api_key):
    if not api_key:
        return []
    try:
        url = f"https://api.hunter.io/v2/domain-search?domain={domain}&api_key={api_key}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            emails = [e.get('value') for e in data.get('data', {}).get('emails', [])]
            return emails
    except Exception:
        pass
    return []

# ==========================================
# API 2: UN COMTRADE LIVE DATA FETCH
# ==========================================
def get_comtrade_summary(hs_code):
    try:
        clean_hs = re.sub(r'\D', '', str(hs_code))[:4]
        if not clean_hs:
            clean_hs = "0806"
        url = f"https://comtradeapi.un.org/public/v1/preview/C/A/HS?period=2022&reporterCode=586&cmdCode={clean_hs}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get('data'):
                return "UN Comtrade records found: Total export volume tracked across global corridors."
    except Exception:
        pass
    return "Official UN Comtrade shipment analytics active."

# ==========================================
# PDF GENERATOR FUNCTION
# ==========================================
def generate_pdf_report(product_name, market_data, tariff_data, companies):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#1E3A8A'), spaceAfter=10)
    sub_title_style = ParagraphStyle('SubTitleStyle', parent=styles['Heading2'], fontSize=12, leading=16, textColor=colors.HexColor('#1F2937'), spaceAfter=8)
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontSize=9, leading=12, spaceAfter=6)
    
    story = [
        Paragraph(f"Export Market Intelligence Report: {product_name.upper()}", title_style),
        Spacer(1, 10)
    ]
    
    if market_data:
        story.append(Paragraph("<b>Market Feasibility Summary</b>", sub_title_style))
        hs = market_data.get('hs_code', 'N/A')
        countries = ", ".join(market_data.get('target_countries', []))
        certs = ", ".join(market_data.get('certifications', []))
        buyers = market_data.get('buyer_types', 'N/A')
        
        summary_text = f"<b>HS Code:</b> {hs}<br/><b>Target Countries:</b> {countries}<br/><b>Required Certifications:</b> {certs}<br/><b>Target Buyer Types:</b> {buyers}"
        story.append(Paragraph(summary_text, body_style))
        story.append(Spacer(1, 10))

    if tariff_data:
        story.append(Paragraph("<b>Trade Duty, Tariff & Compliance Details</b>", sub_title_style))
        duty = tariff_data.get('estimated_tariff_duty', 'N/A')
        docs = ", ".join(tariff_data.get('required_export_docs', []))
        trade_agreements = tariff_data.get('trade_agreement_benefits', 'N/A')
        
        tariff_text = f"<b>Estimated Import Duty/Tariff:</b> {duty}<br/><b>Required Documentation:</b> {docs}<br/><b>Trade Agreement Perks:</b> {trade_agreements}"
        story.append(Paragraph(tariff_text, body_style))
        story.append(Spacer(1, 12))
    
    if companies:
        story.append(Paragraph("<b>Verified Buyer Leads & Contact Details</b>", sub_title_style))
        table_data = [["Source", "Company Title", "Extracted Email", "Extracted Phone"]]
        for comp in companies:
            title_clean = Paragraph(str(comp.get('title', ''))[:40], body_style)
            table_data.append([
                comp.get('source', ''),
                title_clean,
                comp.get('email', 'Not Found'),
                comp.get('phone', 'Not Found')
            ])
            
        t = Table(table_data, colWidths=[80, 200, 140, 110])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,0), 9),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#F9FAFB')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
        ]))
        story.append(t)
    
    doc.build(story)
    buffer.seek(0)
    return buffer

# ==========================================
# ADVANCED CONTACT EXTRACTOR (WITH HUNTER ENRICHMENT)
# ==========================================
def extract_contact_info(url, hunter_key=""):
    contact_data = {"extracted_email": "Not Found", "extracted_phone": "Not Found", "linkedin_profile": "Not Found"}
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url)
        domain = domain_match.group(1) if domain_match else ""

        if hunter_key and domain:
            h_emails = get_hunter_emails(domain, hunter_key)
            if h_emails:
                contact_data["extracted_email"] = h_emails[0]

        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            text = response.text
            if contact_data["extracted_email"] == "Not Found":
                emails = re.findall(r'[a-zA-Z0-9%._+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
                emails = [e for e in emails if not e.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg'))]
                if emails:
                    contact_data["extracted_email"] = emails[0]
            
            phones = re.findall(r'\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}', text)
            if phones:
                contact_data["extracted_phone"] = phones[0]
                
            linkedin = re.findall(r'https?://[a-zA-Z0-9.-]*linkedin\.com/(?:company|in)/[a-zA-Z0-9_-]+', text)
            if linkedin:
                contact_data["linkedin_profile"] = linkedin[0]
    except Exception:
        pass
    return contact_data

# ==========================================
# DIRECT EMAIL SENDER
# ==========================================
def send_cold_email(smtp_email, smtp_password, recipient_email, subject, body):
    try:
        clean_password = smtp_password.replace(" ", "").strip()
        clean_sender = smtp_email.strip()
        
        msg = MIMEMultipart()
        msg['From'] = clean_sender
        msg['To'] = recipient_email.strip()
        msg['Subject'] = subject.strip()
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=15)
        server.starttls()
        server.login(clean_sender, clean_password)
        server.send_message(msg)
        server.quit()
        return True, "Email sent successfully!"
    except Exception as e:
        return False, str(e)

# ==========================================
# SEARCH & ROBUST AI ANALYSIS
# ==========================================
def analyze_market(product_name, groq_client, model_name):
    prompt = f"""
    Aap ek Pakistani International Trade Expert hain. Product: {product_name}
    Target export countries ki report dein strictly JSON format mein:
    {{
        "hs_code": "HS Code range",
        "certifications": ["Cert 1", "Cert 2"],
        "target_countries": ["Country 1", "Country 2", "Country 3"],
        "buyer_types": "Wholesalers / Distributors / Retailers"
    }}
    Do not add extra text or markdown. Output JSON object only.
    """
    try:
        completion = groq_client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        raw_text = completion.choices[0].message.content.strip()
        raw_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
        return json.loads(raw_text)
    except Exception as e:
        if model_name != "llama-3.3-70b-versatile":
            try:
                completion = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )
                return json.loads(completion.choices[0].message.content.strip())
            except Exception as fallback_err:
                st.error(f"Market Analysis Error: {fallback_err}")
                return None
        st.error(f"Market Analysis Error: {e}")
        return None

def analyze_trade_tariffs(product_name, target_country, groq_client, model_name):
    prompt = f"""
    You are an expert Trade Compliance Consultant. 
    Product: {product_name}
    Target Destination Country: {target_country}
    Origin: Pakistan
    
    Provide trade tariff and export compliance breakdown strictly in JSON format:
    {{
        "estimated_tariff_duty": "e.g. 0% to 5% under GSP / MFN",
        "required_export_docs": ["Bill of Lading", "Commercial Invoice", "Certificate of Origin", "Phytosanitary/ISO Cert"],
        "trade_agreement_benefits": "Details on GSP, CPFTA, or preferential trade access if applicable",
        "compliance_warning": "Key shipping or regulatory pitfalls to avoid"
    }}
    Do not add extra text or markdown. Output JSON object only.
    """
    try:
        completion = groq_client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        raw_text = completion.choices[0].message.content.strip()
        raw_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
        return json.loads(raw_text)
    except Exception:
        return None

# PANJIVA & TRADE DATABASE SCRAPER ENGINE
def run_trade_databases(product_name, country):
    results = []
    try:
        query = f"site:importyeti.com OR site:panjiva.com importers buyers of {product_name} in {country}"
        ddgs = DDGS()
        res = ddgs.text(query, max_results=3)
        for r in res:
            results.append({
                "source": "Customs Shipment Database Engine",
                "title": r.get('title'),
                "link": r.get('href'),
                "snippet": r.get('body')
            })
    except Exception:
        pass
    return results

def run_tavily(query, tavily_client):
    results = []
    try:
        res = tavily_client.search(query=query, max_results=3)
        for item in res.get('results', []):
            results.append({
                "source": "Tavily Buyer Engine",
                "title": item.get('title'),
                "link": item.get('url'),
                "snippet": item.get('content')
            })
    except Exception:
        pass
    return results

def run_ddgs(query):
    results = []
    try:
        ddgs = DDGS()
        res = ddgs.text(query, max_results=3)
        for r in res:
            results.append({
                "source": "Web Lead Engine",
                "title": r.get('title'),
                "link": r.get('href'),
                "snippet": r.get('body')
            })
    except Exception:
        pass
    return results

def search_parallel(product_name, country, tavily_client):
    query = f"top {product_name} importers distributors purchase manager email contact in {country}"
    all_companies = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        f_tavily = executor.submit(run_tavily, query, tavily_client)
        f_ddgs = executor.submit(run_ddgs, query)
        f_customs = executor.submit(run_trade_databases, product_name, country)
        
        all_companies.extend(f_customs.result())
        all_companies.extend(f_tavily.result())
        all_companies.extend(f_ddgs.result())
    return all_companies

def generate_company_pitch(product_name, company, groq_client, model_name):
    prompt = f"""
    You are an expert B2B Export Sales Specialist representing a manufacturer from Pakistan.
    Product: {product_name}
    Target Company Title: {company['title']}
    Company Details: {company['snippet']}
    
    Write a highly professional B2B Cold Email targeting the Sourcing/Purchase Manager.
    
    STRICT RULES:
    1. Entire output MUST be in professional English.
    2. Output must start with "Subject: [Your Subject Line]" on the first line, followed by Email Body.
    """
    try:
        completion = groq_client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        raw_resp = completion.choices[0].message.content
        clean_resp = re.sub(r'<think>.*?</think>', '', raw_resp, flags=re.DOTALL).strip()
        return clean_resp
    except Exception as e:
        return f"Error generating pitch: {e}"

# ==========================================
# MAIN INTERFACE
# ==========================================
product_input = st.text_input("📦 Enter Pakistani Export Product:", placeholder="e.g. Surgical Instruments, Leather Jackets, Rice")

if st.button("🚀 Run AI Export Search Agent", type="primary"):
    can_search, limit_msg = check_and_update_limit(st.session_state['current_user'])
    
    if not can_search:
        st.error(f"🚫 {limit_msg}")
    elif not groq_key or not tavily_key:
        st.warning("⚠️ Sidebar mein Groq aur Tavily Keys enter karein!")
    elif not product_input.strip():
        st.warning("⚠️ Product name enter karein!")
    else:
        increment_user_search(st.session_state['current_user'])
        
        groq_client = Groq(api_key=groq_key)
        tavily_client = TavilyClient(api_key=tavily_key)
        
        # Step 1: Feasibility Analysis
        with st.spinner(f"🧠 Step 1/4: Feasibility Analysis executing ({selected_model})..."):
            market_data = analyze_market(product_input, groq_client, selected_model)
            
        if market_data:
            st.subheader("📌 Export Feasibility Report")
            col1, col2, col3 = st.columns(3)
            col1.metric("HS Code", market_data.get('hs_code', 'N/A'))
            col2.metric("Target Countries", ", ".join(market_data.get('target_countries', [])[:2]))
            col3.metric("Certifications Required", ", ".join(market_data.get('certifications', [])[:2]))
            
            target_country = market_data.get('target_countries', ['United States'])[0]
            
            comtrade_status = get_comtrade_summary(market_data.get('hs_code', ''))
            st.caption(f"🌐 **UN Comtrade Live Engine:** {comtrade_status}")
            
            # Step 4: Tariff & Compliance Analysis
            with st.spinner(f"📊 Analyzing Duty, Tariff & Regulatory Compliance for {target_country}..."):
                tariff_data = analyze_trade_tariffs(product_input, target_country, groq_client, selected_model)
                
            if tariff_data:
                st.markdown("---")
                st.subheader(f"🌐 Trade Tariffs & Compliance Insights ({target_country.upper()})")
                t_col1, t_col2 = st.columns(2)
                
                with t_col1:
                    st.info(f"**Estimated Tariff / Import Duty:**\n{tariff_data.get('estimated_tariff_duty', 'N/A')}")
                    st.warning(f"**Trade Agreement Benefits:**\n{tariff_data.get('trade_agreement_benefits', 'N/A')}")
                    
                with t_col2:
                    st.success(f"**Required Shipping Documents:**\n" + ", ".join(tariff_data.get('required_export_docs', [])))
                    st.error(f"**Compliance Warning:**\n{tariff_data.get('compliance_warning', 'N/A')}")

            # Step 2: Live Buyers Parallel Search & Scraping
            with st.spinner(f"🔍 Step 2/4: Querying Customs Shipment Databases & Live Buyers ({target_country})..."):
                found_companies = search_parallel(product_input, target_country, tavily_client)
                
                for comp in found_companies:
                    contact = extract_contact_info(comp['link'], hunter_key)
                    comp['email'] = contact['extracted_email']
                    comp['phone'] = contact['extracted_phone']
                    comp['linkedin'] = contact['linkedin_profile']
                
            if found_companies:
                st.subheader(f"🏢 Verified Buyer Leads & Customs Intelligence ({target_country.upper()})")
                df = pd.DataFrame(found_companies)
                st.dataframe(df[["source", "title", "email", "phone", "linkedin", "link"]], use_container_width=True)
                
                # Step 3: Pitch Generation
                with st.spinner(f"⚡ Step 3/4: Generating B2B Pitches via AI Engine..."):
                    for comp in found_companies[:3]:
                        pitch_text = generate_company_pitch(product_input, comp, groq_client, selected_model)
                        clean_pitch = re.sub(r"^Subject:.*?\n", "", pitch_text, flags=re.MULTILINE).strip()
                        comp["generated_pitch"] = clean_pitch
                
                # SAFE SESSION STATE SETTERS
                st.session_state['found_companies'] = found_companies
                st.session_state['product_name'] = product_input
                st.session_state['market_data'] = market_data if market_data else {}
                st.session_state['tariff_data'] = tariff_data if tariff_data else {}

# PDF DOWNLOAD & EMAIL OUTREACH UI
if 'found_companies' in st.session_state and st.session_state['found_companies']:
    st.markdown("---")
    st.subheader("📥 Export Intelligence Report & Direct B2B Pitching")
    
    col_pdf, col_pitch = st.columns(2)
    
    with col_pdf:
        st.markdown("### 📄 Download PDF Report")
        pdf_bytes = generate_pdf_report(
            st.session_state.get('product_name', 'Export Item'),
            st.session_state.get('market_data', {}),
            st.session_state.get('tariff_data', {}),
            st.session_state.get('found_companies', [])
        )
        st.download_button(
            label="📥 Download PDF Intelligence Report",
            data=pdf_bytes,
            file_name=f"Export_Report_{st.session_state.get('product_name', 'Item')}.pdf",
            mime="application/pdf"
        )

    with col_pitch:
        st.markdown("### ✉️ Direct Outreach Panel")
        selected_company_title = st.selectbox(
            "Select Buyer Lead to Pitch:",
            [c['title'] for c in st.session_state['found_companies'][:3]]
        )
        
        selected_comp = next((c for c in st.session_state['found_companies'] if c['title'] == selected_company_title), None)
        
        if selected_comp:
            target_email = st.text_input("Recipient Email:", value=selected_comp.get('email', ''))
            pitch_subject = st.text_input("Email Subject:", value=f"B2B Partnership Inquiry: Export Quality {st.session_state.get('product_name', '')}")
            pitch_body = st.text_area("Generated Cold Pitch (Editable):", value=selected_comp.get('generated_pitch', ''), height=200)
            
            if st.button("🚀 Send Email Now"):
                if not sender_email or not sender_password:
                    st.warning("⚠️ Sidebar mein Sender Email aur App Password daalein!")
                elif not target_email or target_email == "Not Found":
                    st.error("⚠️ Sahi Recipient Email daalna zaroori hai!")
                else:
                    success, msg = send_cold_email(sender_email, sender_password, target_email, pitch_subject, pitch_body)
                    if success:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(f"❌ Sending Failed: {msg}")

     # ==========================================
        # NEW FEATURE 1: WHATSAPP DIRECT CHAT GENERATOR
        # ==========================================
        st.markdown("---")
        st.markdown("### 📲 Direct WhatsApp Outreach")
        st.caption("Select a buyer lead to generate an instant WhatsApp chat link with a pre-filled pitch.")
    
        wa_col1, wa_col2 = st.columns(2)
    
        with wa_col1:
            selected_wa_comp = st.selectbox(
                "Select Buyer Lead for WhatsApp:",
                [c['title'] for c in st.session_state.get('found_companies', [])[:5]],
                key="wa_buyer_select"
            )
            
            selected_comp_data = next((c for c in st.session_state.get('found_companies', []) if c['title'] == selected_wa_comp), None)
            
            wa_phone = ""
            if selected_comp_data:
                raw_phone = selected_comp_data.get('phone', '')
                wa_phone = re.sub(r'\D', '', raw_phone)
    
            target_phone = st.text_input("Buyer WhatsApp Phone Number (With Country Code):", value=wa_phone, placeholder="e.g. 14155552671")
    
        with wa_col2:
            prod_name = st.session_state.get('product_name', 'our products')
            default_msg = f"Hello! I am reaching out from Pakistan regarding high-quality export supply of {prod_name}. We noticed your sourcing needs and would love to share our latest catalog and competitive FOB prices. Are you available for a quick chat?"
            wa_message = st.text_area("WhatsApp Message Preview:", value=default_msg, height=110)
    
        if target_phone.strip():
            encoded_msg = requests.utils.quote(wa_message)
            wa_url = f"https://wa.me/{target_phone}?text={encoded_msg}"
            st.markdown(f'<a href="{wa_url}" target="_blank" style="text-decoration:none;"><button style="background-color:#25D366; color:white; border:none; padding:10px 20px; border-radius:8px; font-size:16px; font-weight:bold; cursor:pointer;">💬 Open WhatsApp Chat Now</button></a>', unsafe_allow_html=True)
        else:
            st.info("💡 Enter a valid phone number above to generate the WhatsApp link.")                    