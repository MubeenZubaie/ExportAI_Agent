import streamlit as st
import pandas as pd
import json
import re
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
import concurrent.futures
from groq import Groq
from ddgs import DDGS
from tavily import TavilyClient

# ---------------------------------------------
# 1. LOAD ENV VARIABLES FROM .ENV FILE
# ---------------------------------------------
import os
from dotenv import load_dotenv

# Force load .env file
load_dotenv()

DEFAULT_GROQ = os.getenv("GROQ_API_KEY", "")
DEFAULT_TAVILY = os.getenv("TAVILY_API_KEY", "")
DEFAULT_EMAIL = os.getenv("SENDER_EMAIL", "")
DEFAULT_PASS = os.getenv("SENDER_PASSWORD", "")

# Page Config
st.set_page_config(page_title="Export AI Agent", page_icon="🚀", layout="wide")

st.title("🚀 Global Export AI Agent (Enterprise Edition)")
st.caption("Powered by Groq Llama-3.3, Tavily AI, DDGS, & Direct Email Automation")

# ---------------------------------------------
# 2. SIDEBAR WITH AUTO-FILLED VALUES
# ---------------------------------------------
st.sidebar.header("🔑 API & Email Credentials")
groq_key = st.sidebar.text_input("Groq API Key", value=DEFAULT_GROQ, type="password")
tavily_key = st.sidebar.text_input("Tavily API Key", value=DEFAULT_TAVILY, type="password")

st.sidebar.divider()
st.sidebar.subheader("📧 Sender Email Settings (Gmail SMTP)")
sender_email = st.sidebar.text_input("Your Email", value=DEFAULT_EMAIL)
sender_password = st.sidebar.text_input("App Password", value=DEFAULT_PASS, type="password", help="Gmail App Password")

# ==========================================
# SCRAPER & EMAIL EXTRACTOR (STEP 3)
# ==========================================
def extract_contact_info(url):
    contact_data = {"extracted_email": "Not Found", "extracted_phone": "Not Found"}
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            text = response.text
            # Regex for Emails
            emails = re.findall(r'[a-zA-Z0-9%._+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
            # Filter non-image extensions
            emails = [e for e in emails if not e.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg'))]
            if emails:
                contact_data["extracted_email"] = emails[0]
            
            # Regex for Phone Numbers
            phones = re.findall(r'\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}', text)
            if phones:
                contact_data["extracted_phone"] = phones[0]
    except Exception:
        pass
    return contact_data

# ==========================================
# DIRECT EMAIL SENDER (STEP 2)
# ==========================================
def send_cold_email(smtp_email, smtp_password, recipient_email, subject, body):
    try:
        # Password aur email clean karna
        clean_password = smtp_password.replace(" ", "").strip()
        clean_sender = smtp_email.strip()
        
        msg = MIMEMultipart()
        msg['From'] = clean_sender
        msg['To'] = recipient_email.strip()
        msg['Subject'] = subject.strip()
        msg.attach(MIMEText(body, 'plain'))

        # Gmail SMTP Connection
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=15)
        server.starttls()
        server.login(clean_sender, clean_password)
        server.send_message(msg)
        server.quit()
        return True, "Email sent successfully!"
    except Exception as e:
        return False, str(e)

# ==========================================
# SEARCH & AI FUNCTIONS
# ==========================================
def analyze_market(product_name, groq_client):
    prompt = f"""
    Aap ek Pakistani International Trade Expert hain. Product: {product_name}
    Target export countries ki report dein strictly JSON format mein:
    {{
        "hs_code": "HS Code range",
        "certifications": ["Cert 1", "Cert 2"],
        "target_countries": ["Country 1", "Country 2", "Country 3"],
        "buyer_types": "Wholesalers / Distributors / Retailers"
    }}
    Only valid JSON format, no extra text or markdown code blocks.
    """
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        raw_text = completion.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(raw_text)
    except Exception as e:
        st.error(f"Market Analysis Error: {e}")
        return None

def run_tavily(query, tavily_client):
    results = []
    try:
        res = tavily_client.search(query=query, max_results=3)
        for item in res.get('results', []):
            results.append({
                "source": "Tavily AI",
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
                "source": "DDGS Engine",
                "title": r.get('title'),
                "link": r.get('href'),
                "snippet": r.get('body')
            })
    except Exception:
        pass
    return results

def search_parallel(product_name, country, tavily_client):
    query = f"top {product_name} importers distributors wholesalers in {country}"
    all_companies = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        f_tavily = executor.submit(run_tavily, query, tavily_client)
        f_ddgs = executor.submit(run_ddgs, query)
        all_companies.extend(f_tavily.result())
        all_companies.extend(f_ddgs.result())
    return all_companies

def generate_company_pitch(product_name, company, groq_client):
    prompt = f"""
    You are an expert B2B Export Sales Specialist representing a manufacturer from Pakistan.
    Product: {product_name}
    Target Company Title: {company['title']}
    Company Details: {company['snippet']}
    
    Write a highly professional B2B Cold Email targeting the Sourcing/Purchase Manager of this company.
    
    STRICT RULES:
    1. The ENTIRE output MUST be strictly in professional, formal English language.
    2. Do NOT use any Hindi, Urdu, Roman Hindi, or Devanagari script.
    3. Output must start with "Subject: [Your Subject Line]" on the first line, followed by the Email Body.
    """
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Error generating pitch: {e}"

# ==========================================
# MAIN INTERFACE
# ==========================================
product_input = st.text_input("📦 Enter Pakistani Export Product:", placeholder="e.g. Surgical Instruments, Leather Jackets, Rice")

if st.button("🚀 Run AI Export Search Agent", type="primary"):
    if not groq_key or not tavily_key:
        st.warning("⚠️ Sidebar mein Groq aur Tavily Keys enter karein!")
    elif not product_input.strip():
        st.warning("⚠️ Product name enter karein!")
    else:
        groq_client = Groq(api_key=groq_key)
        tavily_client = TavilyClient(api_key=tavily_key)
        
        # Step 1: Feasibility Analysis
        with st.spinner("🧠 1/4: Market Feasibility Analysis..."):
            market_data = analyze_market(product_input, groq_client)
            
        if market_data:
            st.subheader("📌 Export Feasibility Report")
            col1, col2, col3 = st.columns(3)
            col1.metric("HS Code", market_data.get('hs_code', 'N/A'))
            col2.metric("Target Countries", ", ".join(market_data.get('target_countries', [])[:2]))
            col3.metric("Certifications Required", ", ".join(market_data.get('certifications', [])[:2]))
            
            target_country = market_data.get('target_countries', ['United States'])[0]
            
            # Step 2: Live Buyers Parallel Search & Scraping
            with st.spinner(f"🔍 2/4: Buyers search & Contact details extract ho rahe hain ({target_country})..."):
                found_companies = search_parallel(product_input, target_country, tavily_client)
                
                # Scraping Web Pages for Emails & Phone
                for comp in found_companies:
                    contact = extract_contact_info(comp['link'])
                    comp['email'] = contact['extracted_email']
                    comp['phone'] = contact['extracted_phone']
                
            if found_companies:
                st.subheader(f"🏢 Live Buyer Profiles & Extracted Contacts ({target_country.upper()})")
                df = pd.DataFrame(found_companies)
                st.dataframe(df[["source", "title", "email", "phone", "link"]], use_container_width=True)
                
                # Step 3: Pitch Generation
                with st.spinner("⚡ 3/4: High-Converting Sales Pitches generate ho rahi hain..."):
                    for comp in found_companies[:3]:
                        pitch_text = generate_company_pitch(product_input, comp, groq_client)
                        comp["generated_pitch"] = pitch_text
                
                # Save results to session state so UI inputs stay active
                st.session_state['found_companies'] = found_companies
                st.session_state['product_name'] = product_input

# ==========================================
# STEP 3: PITCH & DIRECT EMAIL SENDER UI (WITH BULK SENDING)
# ==========================================
if 'found_companies' in st.session_state and st.session_state['found_companies']:
    companies = st.session_state['found_companies'][:3]
    prod_name = st.session_state.get('product_name', 'Export Item')
    
    st.divider()
    
    # ---------------------------------------------------------
    # MASTER BULK EMAIL BUTTON
    # ---------------------------------------------------------
    st.subheader("🔥 Bulk Email Outreach")
    st.info("💡 Yeh feature tamam scraped companies ko baari-baari 3 second ke interval se email bhejega.")
    
    if st.button("🚀 Send Cold Emails to ALL Companies at Once", type="primary"):
        if not sender_email or not sender_password:
            st.error("❌ Pehle Sidebar mein Sender Email aur Gmail App Password confirm karein!")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            success_count = 0
            
            import time
            for idx, comp in enumerate(companies):
                rec_email = comp.get('email')
                if rec_email and rec_email != "Not Found":
                    status_text.text(f"Sending email {idx+1}/{len(companies)} to {rec_email}...")
                    
                    pitch_content = comp.get("generated_pitch", "")
                    
                    # Extract Subject
                    subj = f"Export Opportunity: High Quality {prod_name} from Pakistan"
                    if "Subject:" in pitch_content:
                        for line in pitch_content.split("\n"):
                            if line.startswith("Subject:"):
                                subj = line.replace("Subject:", "").strip()
                                break
                    
                    # Clean body
                    clean_body = re.sub(r"^Subject:.*?\n", "", pitch_content, flags=re.MULTILINE).strip()
                    
                    # Send Email
                    ok, err = send_cold_email(sender_email, sender_password, rec_email, subj, clean_body)
                    if ok:
                        success_count += 1
                    
                    # Delay to avoid Gmail rate limit
                    time.sleep(3)
                
                progress_bar.progress((idx + 1) / len(companies))
            
            status_text.text("Bulk Sending Completed!")
            st.success(f"🎉 Process Complete! Successfully sent {success_count} out of {len(companies)} emails.")
            st.balloons()

    st.divider()
    
    # ---------------------------------------------------------
    # INDIVIDUAL TABS FOR SINGLE EMAIL PREVIEW & SENDING
    # ---------------------------------------------------------
    st.subheader("✉️ Individual Pitch Preview & Outreach")
    tabs = st.tabs([f"Company {i+1}" for i in range(len(companies))])
    
    for idx, tab in enumerate(tabs):
        comp = companies[idx]
        with tab:
            st.markdown(f"**Target Company:** [{comp['title']}]({comp['link']})")
            st.markdown(f"**Extracted Email:** `{comp['email']}`")
            
            pitch_content = comp.get("generated_pitch", "")
            
            # Extract Subject Line
            subject_default = f"Export Opportunity: High Quality {prod_name} from Pakistan"
            if "Subject:" in pitch_content:
                for line in pitch_content.split("\n"):
                    if line.startswith("Subject:"):
                        subject_default = line.replace("Subject:", "").strip()
                        break
            
            email_subject = st.text_input("Email Subject:", value=subject_default, key=f"subj_{idx}")
            email_body = st.text_area("Email Pitch Body:", value=pitch_content, height=200, key=f"body_{idx}")
            
            st.write("---")
            target_email_input = st.text_input("Recipient Email Address:", value=comp['email'] if comp['email'] != "Not Found" else "", key=f"target_email_{idx}")
            
            if st.button(f"🚀 Send Single Email", key=f"send_btn_{idx}"):
                if not sender_email or not sender_password:
                    st.error("❌ Pehle Sidebar mein Sender Email aur Gmail App Password daraj karein!")
                elif not target_email_input or target_email_input == "Not Found":
                    st.error("❌ Sahi recipient email address daalein!")
                else:
                    with st.spinner("⏳ Sending email..."):
                        clean_body = re.sub(r"^Subject:.*?\n", "", email_body, flags=re.MULTILINE).strip()
                        success, msg = send_cold_email(
                            sender_email, 
                            sender_password, 
                            target_email_input, 
                            email_subject, 
                            clean_body
                        )
                    if success:
                        st.success(f"✅ Email SUCCESSFUL: {target_email_input}")
                        st.balloons()
                    else:
                        st.error(f"❌ Email Failed: {msg}")

    # Step 4: CSV Export Button
    export_df = pd.DataFrame(st.session_state['found_companies'])
    csv_data = export_df.to_csv(index=False).encode('utf-8')
    st.divider()
    st.download_button(
        label="📥 Download Complete Report & Scraped Leads (CSV)",
        data=csv_data,
        file_name=f"export_leads_{prod_name.replace(' ', '_')}.csv",
        mime="text/csv",
        type="primary"
    )