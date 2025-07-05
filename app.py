# debt_manager_app.py

import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import gspread
from google.oauth2.service_account import Credentials
import json # Import the json library
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.units import cm
from reportlab.lib import colors
from io import BytesIO

# ---------------- Configuration ----------------
# สำคัญ: URL Google Sheet
# ใช้ URL ที่คุณระบุในไฟล์ app.py ล่าสุด
GSHEET_URL = "https://docs.google.com/spreadsheets/d/1NnXtkjXjiy0EKCzj9-Eclt6udXUrvxF4jkN3IzkXBjI/edit#gid=0"

# --- REQUIRED GOOGLE SHEET COLUMN NAMES (Exact Match) ---
# กรุณาตรวจสอบให้ **มั่นใจ 100%** ว่าหัวตาราง (แถวแรกสุด) ใน Google Sheet ของคุณ
# มีชื่อ **ตรงกันเป๊ะ** กับที่ระบุไว้ด้านล่างนี้ (คัดลอกและวางได้เลย)
# ไม่มีช่องว่างนำหน้า/ต่อท้าย หรืออักขระพิเศษอื่นใดที่มองไม่เห็น

# สำหรับชีต 'customers'
CUSTOMER_GSHEET_COLS = ["ลำดับที่", "ชื่อ", "รวมเงินกู้ทั้งหมด"]

# สำหรับชีต 'pay'
PAYMENT_GSHEET_COLS = ["ผู้จ่าย", "วันที่จ่าย", "จำนวน", "หมายเหตุ"]
# ---------------------------------------------------------

# ---------------- Google Sheets Helpers ----------------
@st.cache_resource
def get_gspread_client():
    try:
        # Load the service account info directly from Streamlit secrets
        if "gcp_service_account" not in st.secrets:
            st.error("❌ ไม่พบ SECRET 'gcp_service_account' ใน Streamlit Cloud Secrets หรือไฟล์ secrets.toml ของคุณ")
            st.stop()

        # Parse the JSON string from secrets into a Python dictionary
        service_account_info = json.loads(st.secrets["gcp_service_account"])

        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"] 
        
        # Create credentials from the dictionary
        creds = Credentials.from_service_account_info(service_account_info, scopes=scope)
        
        client = gspread.authorize(creds)
        return client
    except json.JSONDecodeError as e:
        st.error(f"❌ **ข้อผิดพลาดในการอ่าน JSON Secret**: {e}")
        st.error("โปรดตรวจสอบการจัดรูปแบบของ 'gcp_service_account' ใน Streamlit Cloud Secrets หรือไฟล์ secrets.toml ของคุณ")
        st.warning("ตรวจสอบให้แน่ใจว่าไม่มีอักขระพิเศษที่ไม่ถูกต้อง (invalid control character) ปะปนอยู่")
        st.stop()
    except Exception as e:
        st.error(f"❌ **ข้อผิดพลาดในการเชื่อมต่อ Google Sheets**: {e}")
        st.error(f"รายละเอียด: {e}") 
        st.error("ไม่สามารถเชื่อมต่อกับ Google Sheets ได้ โปรดตรวจสอบ Service Account Key และสิทธิ์การเข้าถึงของคุณ")
        st.stop()
        return None

# Helper to normalize column names from Google Sheets
# This will strip invisible characters or extra spaces from raw headers
def _normalize_gsheet_col_name(col_name):
    if isinstance(col_name, str):
        return col_name.strip().replace('\xa0', ' ').replace('\ufeff', '')
    return str(col_name) 

def read_sheet_to_df(sheet_name, required_cols):
    client = get_gspread_client()
    try:
        spreadsheet = client.open_by_url(GSHEET_URL)
        sheet = spreadsheet.worksheet(sheet_name)
        raw_data = sheet.get_all_values()
        
        if not raw_data:
            st.warning(f"⚠️ ชีต '{sheet_name}' ว่างเปล่า.")
            # Return a DataFrame with required columns, but empty
            return pd.DataFrame(columns=required_cols)
            
        # Normalize headers before using them
        headers = [_normalize_gsheet_col_name(h) for h in raw_data[0]]

        # Validate columns
        missing_cols = [col for col in required_cols if col not in headers]
        if missing_cols:
            st.error(f"❌ **ข้อผิดพลาด**: ชีต '{sheet_name}' ขาดคอลัมน์ที่จำเป็น: {', '.join(missing_cols)}")
            st.error(f"โปรดตรวจสอบว่าหัวตารางในชีต '{sheet_name}' ตรงกับที่ระบุในโค้ด: {', '.join(required_cols)}")
            st.stop()

        df = pd.DataFrame(raw_data[1:], columns=headers)
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ ไม่พบชีตชื่อ '{sheet_name}' ใน Google Sheet กรุณาตรวจสอบชื่อชีตให้ถูกต้อง.")
        st.stop()
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดในการอ่านข้อมูลจากชีต '{sheet_name}': {e}")
        st.stop()

def write_df_to_sheet(sheet_name, df_to_write, original_col_names):
    client = get_gspread_client()
    try:
        spreadsheet = client.open_by_url(GSHEET_URL)
        sheet = spreadsheet.worksheet(sheet_name)
        
        # Ensure the DataFrame has all expected columns in the correct order for writing
        final_df_for_gsheet = pd.DataFrame(columns=original_col_names)
        for col in original_col_names:
            if col in df_to_write.columns:
                final_df_for_gsheet[col] = df_to_write[col].astype(str) # Ensure all data is string for gspread
            else:
                final_df_for_gsheet[col] = '' # Fill missing columns with empty string

        # Convert to list of lists for gspread update
        data_to_upload = [original_col_names] + final_df_for_gsheet.values.tolist()

        sheet.clear()
        sheet.update(data_to_upload)
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาดในการเขียนข้อมูลลงชีต '{sheet_name}': {e}")
        st.stop()

# ---------------- Load / Save Functions ----------------
@st.cache_data(ttl=3600)
def load_data():
    loading_status = st.empty()
    loading_status.info("⌛ กำลังโหลดข้อมูลจาก Google Sheets... โปรดรอสักครู่")

    try:
        # Directly read using the defined Google Sheet column names
        customers_df = read_sheet_to_df("customers", CUSTOMER_GSHEET_COLS)
        payments_df = read_sheet_to_df("pay", PAYMENT_GSHEET_COLS)

        # --- Data Cleaning and Type Conversion for customers_df ---
        if not customers_df.empty:
            customers_df['รวมเงินกู้ทั้งหมด'] = customers_df['รวมเงินกู้ทั้งหมด'].astype(str).str.replace(r'[^\d.]', '', regex=True)
            customers_df['รวมเงินกู้ทั้งหมด'] = pd.to_numeric(customers_df['รวมเงินกู้ทั้งหมด'], errors='coerce').fillna(0)
            
            customers_df['ลำดับที่'] = pd.to_numeric(customers_df['ลำดับที่'], errors='coerce').fillna(0).astype(int)
            customers_df = customers_df.sort_values(by='ลำดับที่', ascending=True).reset_index(drop=True)
            customers_df['ลำดับที่'] = range(1, len(customers_df) + 1) # Re-index for consistency
        else:
            customers_df = pd.DataFrame(columns=CUSTOMER_GSHEET_COLS) # Ensure empty DF has correct columns

        # --- Data Cleaning and Type Conversion for payments_df ---
        if not payments_df.empty:
            payments_df['จำนวน'] = payments_df['จำนวน'].astype(str).str.replace(r'[^\d.]', '', regex=True)
            payments_df['จำนวน'] = pd.to_numeric(payments_df['จำนวน'], errors='coerce').fillna(0)

            # Convert 'วันที่จ่าย' to datetime, trying multiple formats, store as 'วันที่จ่าย_dt'
            payments_df['วันที่จ่าย_dt'] = pd.to_datetime(payments_df['วันที่จ่าย'], errors='coerce', dayfirst=False)
            
            invalid_dates_mask = payments_df['วันที่จ่าย_dt'].isna()
            if invalid_dates_mask.any():
                payments_df.loc[invalid_dates_mask, 'วันที่จ่าย_dt'] = pd.to_datetime(
                    payments_df.loc[invalid_dates_mask, 'วันที่จ่าย'], errors='coerce', dayfirst=True
                )
            
            payments_df = payments_df.dropna(subset=['วันที่จ่าย_dt'])
            payments_df = payments_df.reset_index(drop=True).assign(temp_index=range(len(payments_df))) # temp_index for internal use
        else:
            payments_df = pd.DataFrame(columns=PAYMENT_GSHEET_COLS)
            payments_df['วันที่จ่าย_dt'] = pd.Series(dtype='datetime64[ns]') # Explicitly set datetime dtype
            payments_df['temp_index'] = pd.Series(dtype=int) # Ensure temp_index also exists with correct dtype

        loading_status.success("✅ โหลดข้อมูลเสร็จสมบูรณ์!")
        return customers_df, payments_df

    except Exception as e:
        loading_status.error(f"❌ เกิดข้อผิดพลาดในการโหลดข้อมูลจาก Google Sheets: {e}")
        st.info("โปรดตรวจสอบ Spreadsheet ID, URL, ชื่อชีต, ชื่อคอลัมน์ และสิทธิ์การเข้าถึงของ Service Account.")
        st.stop()
        return pd.DataFrame(columns=CUSTOMER_GSHEET_COLS), pd.DataFrame(columns=PAYMENT_GSHEET_COLS + ['วันที่จ่าย_dt'])

def clear_cache_and_rerun():
    st.cache_data.clear()
    st.rerun()

# ========== HELPER FUNCTIONS FOR DEBT CALCULATION ==========
def get_debt_periods(start_year=2025):
    periods = []
    contract_start_date = date(2025, 4, 5) 

    for i in range(4): # 4 ปี
        period_start = date(contract_start_date.year + i, 4, 5)
        period_end = date(contract_start_date.year + i + 1, 3, 5) 
        periods.append((period_start, period_end))
    return periods

def calculate_yearly_summary(debtor_name, total_loan, payments_df):
    total_loan = pd.to_numeric(total_loan, errors='coerce')
    if pd.isna(total_loan):
        total_loan = 0
    
    yearly_target = total_loan * 0.25
    periods = get_debt_periods()
    summary_data = []
    total_fine_all_years = 0
    total_paid_all_years = 0
    current_date = datetime.now().date()

    for idx, (start_date, end_date) in enumerate(periods):
        year_label = f"ปีที่ {idx+1} ({start_date.year}/{end_date.year})"
        
        mask = (
            (payments_df['ผู้จ่าย'] == debtor_name) & 
            (payments_df['วันที่จ่าย_dt'].dt.date >= start_date) &
            (payments_df['วันที่จ่าย_dt'].dt.date <= end_date)
        )
        paid_in_period = payments_df.loc[mask, 'จำนวน'].sum() 
        total_paid_all_years += paid_in_period
        
        shortfall = max(0, yearly_target - paid_in_period) 
        fine = 0
        fine_status = ""
        fine_deadline = end_date 

        if current_date > fine_deadline:
            if shortfall > 0:
                fine = round(shortfall * 0.15) 
                total_fine_all_years += fine
                fine_status = f"❌ มีค่าปรับ **{fine:,.0f}** บาท"
            else:
                fine_status = "✅ จ่ายครบแล้ว"
        else:
            fine_status = "⏳ ยังไม่ครบกำหนดคิดค่าปรับ"

        summary_data.append({
            "ปี": year_label,
            "เป้าหมายรายปี": f"{yearly_target:,.0f} บาท",
            "จ่ายแล้วในปีนี้": f"{paid_in_period:,.0f} บาท",
            "ยอดขาด": f"{shortfall:,.0f} บาท",
            "สถานะค่าปรับ": fine_status
        })
    
    remaining_original_debt = max(0, total_loan - total_paid_all_years)
    remaining_overall_debt_with_fine = remaining_original_debt + total_fine_all_years 

    return summary_data, total_paid_all_years, total_fine_all_years, remaining_overall_debt_with_fine

# ========== PDF GENERATION SETUP (GLOBAL SCOPE) ==========
@st.cache_resource
def setup_pdf_styles():
    thai_font_name_local = 'THSarabunNew'
    thai_font_name_bold_local = 'THSarabunNewBold'
    try:
        import os
        if not os.path.exists('THSarabunNew.ttf'):
            st.error("❌ ไม่พบไฟล์ฟอนต์ 'THSarabunNew.ttf' ในโฟลเดอร์เดียวกันกับ `debt_manager_app.py`")
            raise FileNotFoundError("THSarabunNew.ttf not found")
        if not os.path.exists('THSarabunNew Bold.ttf'):
            st.error("❌ ไม่พบไฟล์ฟอนต์ 'THSarabunNew Bold.ttf' ในโฟลเดอร์เดียวกันกับ `debt_manager_app.py`")
            raise FileNotFoundError("THSarabunNew Bold.ttf not found")

        if 'THSarabunNew' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('THSarabunNew', 'THSarabunNew.ttf'))
        if 'THSarabunNewBold' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('THSarabunNewBold', 'THSarabunNew Bold.ttf'))
    except Exception as e:
        st.warning(f"⚠️ **ข้อผิดพลาดในการโหลดฟอนต์ THSarabunNew**: {e}. PDF อาจแสดงผลไม่ถูกต้อง.")
        st.warning("โปรดตรวจสอบว่าไฟล์ 'THSarabunNew.ttf' และ 'THSarabunNew Bold.ttf' อยู่ในโฟลเดอร์เดียวกันกับ `debt_manager_app.py`")
        thai_font_name_local = 'Helvetica'
        thai_font_name_bold_local = 'Helvetica-Bold'
        
    styles = getSampleStyleSheet()
    style_definitions = [
        ('TitleStyle', thai_font_name_bold_local, 28, TA_CENTER, 20), 
        ('Heading1', thai_font_name_bold_local, 20, TA_LEFT, 6),     
        ('Normal', thai_font_name_local, 14, TA_LEFT, 0),           
        ('SignatureCenter', thai_font_name_local, 14, TA_CENTER, 0), 
        ('SignatureLeft', thai_font_name_local, 14, TA_LEFT, 0),    
        ('SignatureRight', thai_font_name_local, 14, TA_RIGHT, 0),   
        ('RightAlign', thai_font_name_local, 14, TA_RIGHT, 0),      
        ('BoldNormal', thai_font_name_bold_local, 14, TA_LEFT, 0),  
        ('RightAlignAmount', thai_font_name_bold_local, 14, TA_RIGHT, 0),
        ('NormalLeft', thai_font_name_local, 14, TA_LEFT, 0) 
    ]
    for name, font, size, alignment, space_after in style_definitions:
        if name not in styles.byName: 
            styles.add(ParagraphStyle(
                name=name, 
                fontName=font, 
                fontSize=size, 
                alignment=alignment, 
                leading=size + 2, 
                spaceAfter=space_after
            ))
        else: 
            styles[name].fontName = font
            styles[name].fontSize = size
            styles[name].alignment = alignment
            styles[name].leading = size + 2
            styles[name].spaceAfter = space_after
    return styles, thai_font_name_local, thai_font_name_bold_local

pdf_styles, thai_font_name, thai_font_name_bold = setup_pdf_styles()

# ========== PDF GENERATION FUNCTIONS ==========
def create_receipt_pdf(debtor_name, payment_date, amount_paid, 
                       yearly_summary_df, total_loan, total_paid_all_years, remaining_overall_debt_with_fine,
                       total_fine_all_years): 
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                            leftMargin=2.5*cm, rightMargin=2.5*cm, 
                            topMargin=2.5*cm, bottomMargin=2.5*cm)
    elements = []

    elements.append(Paragraph("ใบเสร็จรับเงิน", pdf_styles['TitleStyle']))
    elements.append(Spacer(1, 0.8*cm)) 

    # ข้อมูลลูกหนี้และการชำระเงิน:
    data_info = [
        [Paragraph(f"ชื่อลูกหนี้: <font face='{thai_font_name_bold}'>{debtor_name}</font>", pdf_styles['NormalLeft']), ""],
        [Paragraph(f"วันที่ชำระ: {payment_date.strftime('%d/%m/%Y')}", pdf_styles['NormalLeft']), ""],
        [Paragraph(f"จำนวนเงินที่ชำระ:", pdf_styles['Normal']), Paragraph(f"<font face='{thai_font_name_bold}'>{amount_paid:,.2f} บาท</font>", pdf_styles['RightAlignAmount'])]
    ]
    table_info = Table(data_info, colWidths=[12*cm, 4*cm]) 
    table_info.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),  
        ('ALIGN', (1,2), (1,2), 'RIGHT'),  
        ('SPAN', (0,0), (1,0)), 
        ('SPAN', (0,1), (1,1)), 
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5), 
    ]))
    elements.append(table_info)
    
    elements.append(Spacer(1, 1.5*cm)) 
    elements.append(Paragraph("---", pdf_styles['Normal']))
    elements.append(Spacer(1, 1.5*cm)) 

    # สรุปยอดหนี้โดยรวม (ใช้ Table เพื่อจัดชิดขวา)
    data_summary = [
        [Paragraph(f"ยอดหนี้ทั้งหมด:", pdf_styles['Normal']), Paragraph(f"{total_loan:,.2f} บาท", pdf_styles['RightAlignAmount'])],
        [Paragraph(f"ยอดที่ชำระแล้วทั้งหมด:", pdf_styles['Normal']), Paragraph(f"{total_paid_all_years:,.2f} บาท", pdf_styles['RightAlignAmount'])],
        [Paragraph(f"ค่าปรับรวมทั้งหมด:", pdf_styles['Normal']), Paragraph(f"{total_fine_all_years:,.2f} บาท", pdf_styles['RightAlignAmount'])],
        [Paragraph(f"ยอดหนี้คงเหลือทั้งหมด (รวมค่าปรับ):", pdf_styles['BoldNormal']), Paragraph(f"<font face='{thai_font_name_bold}'>{remaining_overall_debt_with_fine:,.2f} บาท</font>", pdf_styles['RightAlignAmount'])]
    ]
    table_summary = Table(data_summary, colWidths=[10*cm, 6*cm]) 
    table_summary.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'), 
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5), 
    ]))
    elements.append(table_summary)
    
    elements.append(Spacer(1, 1.5*cm)) 
    elements.append(Paragraph("---", pdf_styles['Normal']))
    elements.append(Spacer(1, 1.0*cm)) 

    # ลายเซ็น: บรรทัดเดียวกัน ชิดซ้ายและขวา
    signature_table_data = [
        [Paragraph("___________________", pdf_styles['SignatureLeft']), Paragraph("___________________", pdf_styles['SignatureRight'])],
        [Paragraph("(&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;ผู้ชำระเงิน&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;)", pdf_styles['SignatureLeft']), Paragraph("(&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;ผู้รับเงิน&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;)", pdf_styles['SignatureRight'])]
    ]
    signature_table = Table(signature_table_data, colWidths=[8*cm, 8*cm]) 
    signature_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (0,-1), 'LEFT'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(signature_table)

    elements.append(Spacer(1, 0.5*cm))

    doc.build(elements)
    buffer.seek(0)
    return buffer

# ========== STREAMLIT APP ==========
st.set_page_config(layout="wide", page_title="ระบบจัดการลูกหนี้หมู่บ้าน")
st.title("🏡 **ระบบจัดการลูกหนี้หมู่บ้าน**")

# Load data and initial setup
customers_df, payments_df = load_data()
debtor_names = customers_df['ชื่อ'].tolist()

if 'selected_debtor' not in st.session_state:
    st.session_state.selected_debtor = debtor_names[0] if debtor_names else None

menu = st.sidebar.radio("📋 **เมนูหลัก**", ["หน้าหลัก (บันทึก & สรุป)", "👤 จัดการลูกหนี้"])

# ========== PAGE: หน้าหลัก (บันทึก & สรุป) ==========
if menu == "หน้าหลัก (บันทึก & สรุป)":
    st.header("🏠 **หน้าหลัก: บันทึกการชำระ & สรุปสถานะหนี้**")

    # Use a clear default for selectbox if no debtors exist
    selected_debtor_for_summary_and_input = st.selectbox(
        "เลือกชื่อลูกหนี้", 
        debtor_names if debtor_names else ["ไม่มีลูกหนี้"], 
        key="global_debtor_select", 
        index=debtor_names.index(st.session_state.selected_debtor) if st.session_state.selected_debtor in debtor_names else (0 if debtor_names else 0),
        on_change=lambda: st.session_state.update(selected_debtor=st.session_state.global_debtor_select)
    )
    if st.session_state.selected_debtor != selected_debtor_for_summary_and_input:
        st.session_state.selected_debtor = selected_debtor_for_summary_and_input
        st.rerun()

    st.markdown("---") 

    with st.expander("📝 **บันทึกการชำระเงินใหม่**", expanded=True):
        if not st.session_state.selected_debtor or st.session_state.selected_debtor == "ไม่มีลูกหนี้":
            st.warning("⚠️ กรุณาเพิ่มลูกหนี้ในเมนู 'จัดการลูกหนี้' ก่อนทำการบันทึกการชำระเงิน.")
        else:
            with st.form("payment_form", clear_on_submit=True):
                st.write(f"**กำลังบันทึกการชำระเงินสำหรับ**: **{st.session_state.selected_debtor}**")
                pay_date = st.date_input("วันที่จ่าย", datetime.today().date(), key="payment_date_input")
                amount = st.number_input("จำนวน (บาท)", min_value=0.0, step=100.0, key="payment_amount_input")
                note = st.text_input("หมายเหตุ", "", key="payment_note_input")
                submitted = st.form_submit_button("💾 บันทึกการชำระ") 

            if submitted: 
                new_payment_row_data = {
                    "ผู้จ่าย": st.session_state.selected_debtor,
                    "วันที่จ่าย": pay_date.strftime("%Y-%m-%d"), # Store as string for Google Sheet
                    "จำนวน": amount,
                    "หมายเหตุ": note
                }
                
                # To maintain original column order when writing to sheet
                current_payments_df_for_gsheet = payments_df[PAYMENT_GSHEET_COLS].copy()
                new_payment_row_df = pd.DataFrame([new_payment_row_data], columns=PAYMENT_GSHEET_COLS)
                updated_payments_df_for_gsheet = pd.concat([current_payments_df_for_gsheet, new_payment_row_df], ignore_index=True)
                
                write_df_to_sheet("pay", updated_payments_df_for_gsheet, PAYMENT_GSHEET_COLS)

                st.success("✅ **บันทึกข้อมูลเรียบร้อยแล้ว!**")
                st.session_state.submitted_for_receipt = True
                st.session_state.last_payment_date = pay_date
                st.session_state.last_payment_amount = amount
                
                st.info("💡 ข้อมูลถูกบันทึกแล้ว โปรดรอสักครู่เพื่อสร้างใบเสร็จ PDF โดยอัตโนมัติ (หากคุณบันทึกในหน้าหลัก)")
                st.info("ถ้าไม่เห็นปุ่มดาวน์โหลดใบเสร็จ กรุณากดปุ่ม 'บันทึกการชำระ' อีกครั้งหลังจากที่หน้านี้โหลดเสร็จสมบูรณ์")
                clear_cache_and_rerun() # Force rerun to refresh data

    if 'submitted_for_receipt' in st.session_state and st.session_state.submitted_for_receipt:
        if st.session_state.selected_debtor and st.session_state.selected_debtor != "ไม่มีลูกหนี้":
            customers_df_latest, payments_df_latest = load_data()
            latest_selected_debtor_row = customers_df_latest[customers_df_latest['ชื่อ'] == st.session_state.selected_debtor]
            
            if not latest_selected_debtor_row.empty:
                total_loan_for_receipt = latest_selected_debtor_row['รวมเงินกู้ทั้งหมด'].iloc[0] 
                summary_data_receipt, total_paid_receipt, total_fine_receipt, remaining_overall_debt_with_fine_receipt = calculate_yearly_summary(
                    st.session_state.selected_debtor, total_loan_for_receipt, payments_df_latest
                )
                yearly_summary_df_receipt = pd.DataFrame(summary_data_receipt)

                pdf_buffer = create_receipt_pdf(
                    st.session_state.selected_debtor,
                    st.session_state.last_payment_date,
                    st.session_state.last_payment_amount,
                    yearly_summary_df_receipt,
                    total_loan_for_receipt,
                    total_paid_receipt,
                    remaining_overall_debt_with_fine_receipt, 
                    total_fine_receipt
                )
                st.download_button(
                    label="📄 พิมพ์ใบเสร็จ PDF",
                    data=pdf_buffer,
                    file_name=f"ใบเสร็จ_{st.session_state.selected_debtor}_{st.session_state.last_payment_date.strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                    key="download_receipt_button" 
                )
                st.info("💡 คลิกปุ่ม 'พิมพ์ใบเสร็จ PDF' ด้านบนเพื่อดาวน์โหลดใบเสร็จ")
                st.session_state.submitted_for_receipt = False
                if 'last_payment_date' in st.session_state:
                    del st.session_state.last_payment_date
                if 'last_payment_amount' in st.session_state:
                    del st.session_state.last_payment_amount
            else:
                st.warning("⚠️ ไม่พบข้อมูลลูกหนี้สำหรับสร้างใบเสร็จ โปรดตรวจสอบชื่อลูกหนี้")
        else:
            st.warning("⚠️ กรุณาเลือกชื่อลูกหนี้ที่ต้องการพิมพ์ใบเสร็จ.")

    st.markdown("---") 

    st.subheader("📊 **สรุปสถานะหนี้ลูกหนี้**")
    summary_debtor_name = st.session_state.selected_debtor 

    if summary_debtor_name and summary_debtor_name != "ไม่มีลูกหนี้":
        selected_debtor_row = customers_df[customers_df['ชื่อ'] == summary_debtor_name]
        if not selected_debtor_row.empty:
            total_loan_for_summary = selected_debtor_row['รวมเงินกู้ทั้งหมด'].iloc[0] 
            
            summary_data, total_paid, total_fine, remaining_overall_debt_with_fine = calculate_yearly_summary( 
                summary_debtor_name, total_loan_for_summary, payments_df
            )

            st.markdown(
                f"""
                <div style="background-color:#d4edda; padding:15px; border-radius:10px; border:2px solid #28a745;">
                    <h4 style="color:#155724; text-align:center;">**ข้อมูลหนี้ของ: {summary_debtor_name}**</h4>
                    <div style="display:flex; justify-content:space-around; margin-top:10px;">
                        <div style="text-align:center; flex:1;">
                            <p style="font-size:1.1em; color:#155724;">💰 **รวมยอดหนี้ทั้งหมด**</p>
                            <h3 style="color:#155724;">{total_loan_for_summary:,.2f} บาท</h3>
                        </div>
                        <div style="text-align:center; flex:1;">
                            <p style="font-size:1.1em; color:#856404;">✅ **ยอดที่จ่ายแล้ว (รวมทุกปี)**</p>
                            <h3 style="color:#856404;">{total_paid:,.2f} บาท</h3>
                        </div>
                        <div style="text-align:center; flex:1;">
                            <p style="font-size:1.1em; color:#721c24;">🔻 **ค่าปรับรวมทั้งหมด**</p>
                            <h3 style="color:#721c24;">{total_fine:,.2f} บาท</h3>
                        </div>
                        <div style="text-align:center; flex:1;">
                            <p style="font-size:1.1em; color:#004085;">📌 **ยอดหนี้คงเหลือ (รวมค่าปรับ)**</p>
                            <h3 style="color:#004085;">{remaining_overall_debt_with_fine:,.2f} บาท</h3>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True
            )

            st.markdown("---")
            st.subheader("🗓️ **รายละเอียดการชำระรายปี**")
            summary_df = pd.DataFrame(summary_data)
            st.dataframe(summary_df, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.subheader("📜 **ประวัติการชำระเงินทั้งหมด**")
            payment_history_for_display = payments_df[payments_df['ผู้จ่าย'] == summary_debtor_name].sort_values(by='วันที่จ่าย_dt', ascending=False)
            
            if not payment_history_for_display.empty:
                if 'show_edit_form' not in st.session_state:
                    st.session_state.show_edit_form = False
                if 'edit_payment_data' not in st.session_state:
                    st.session_state.edit_payment_data = None

                for i, row in payment_history_for_display.iterrows():
                    original_df_row_index = row['temp_index']
                    # Use client directly
                    client = get_gspread_client()
                    pay_sheet = client.open_by_url(GSHEET_URL).worksheet("pay")
                    
                    all_pay_values = pay_sheet.get_all_values()
                    
                    row_index_in_gsheet = -1
                    if all_pay_values:
                        headers = [_normalize_gsheet_col_name(h) for h in all_pay_values[0]]
                        target_date_str = row['วันที่จ่าย_dt'].strftime("%Y-%m-%d") 
                        
                        try:
                            payer_idx = headers.index("ผู้จ่าย")
                            date_idx = headers.index("วันที่จ่าย")
                            amount_idx = headers.index("จำนวน")
                            note_idx = headers.index("หมายเหตุ")
                        except ValueError as e:
                            st.error(f"❌ คอลัมน์ที่จำเป็นไม่ครบในชีต 'pay' ระหว่างการค้นหาแถว: {e}")
                            st.stop()
                            
                        for idx_gsheet, gsheet_row in enumerate(all_pay_values[1:]): # Skip header
                            gsheet_row_padded = gsheet_row + [''] * (max(payer_idx, date_idx, amount_idx, note_idx) + 1 - len(gsheet_row))
                            
                            gsheet_amount = pd.to_numeric(_normalize_gsheet_col_name(gsheet_row_padded[amount_idx]), errors='coerce')

                            if (
                                _normalize_gsheet_col_name(gsheet_row_padded[payer_idx]) == row['ผู้จ่าย'] and
                                _normalize_gsheet_col_name(gsheet_row_padded[date_idx]) == target_date_str and
                                gsheet_amount == row['จำนวน'] and 
                                _normalize_gsheet_col_name(gsheet_row_padded[note_idx]) == row['หมายเหตุ']
                            ):
                                row_index_in_gsheet = idx_gsheet + 2 # +2 for 1-based index and header row
                                break

                    if row_index_in_gsheet == -1:
                        st.warning(f"⚠️ ไม่พบรายการชำระเงินนี้ใน Google Sheet สำหรับแก้ไข (อาจถูกลบไปแล้ว): {row['ผู้จ่าย']} - {row['จำนวน']}")
                        continue 

                    edit_button_key = f"edit_payment_{original_df_row_index}"
                    receipt_button_key = f"print_receipt_{original_df_row_index}"

                    with st.expander(f"**รายการวันที่ {row['วันที่จ่าย_dt'].strftime('%d/%m/%Y')} จำนวน {row['จำนวน']:,.0f} บาท**", expanded=False):
                        st.write(f"**ผู้จ่าย**: {row['ผู้จ่าย']}")
                        st.write(f"**วันที่จ่าย**: {row['วันที่จ่าย_dt'].strftime('%d/%m/%Y')}")
                        st.write(f"**จำนวน**: {row['จำนวน']:,.0f} บาท")
                        st.write(f"**หมายเหตุ**: {row['หมายเหตุ'] if row['หมายเหตุ'] else '-'}")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("✏️ **แก้ไขรายการนี้**", key=edit_button_key):
                                st.session_state.edit_payment_data = {
                                    "sheet_row_index": row_index_in_gsheet, 
                                    "debtor_name": row['ผู้จ่าย'], 
                                    "payment_date": row['วันที่จ่าย_dt'].date(), 
                                    "amount": row['จำนวน'], 
                                    "note": row['หมายเหตุ'] 
                                }
                                st.session_state.show_edit_form = True
                                st.rerun() 
                        with col2:
                            customers_df_receipt, payments_df_receipt = load_data() 
                            selected_debtor_row_receipt = customers_df_receipt[customers_df_receipt['ชื่อ'] == summary_debtor_name]
                            total_loan_receipt = selected_debtor_row_receipt['รวมเงินกู้ทั้งหมด'].iloc[0] 
                            
                            summary_data_receipt, total_paid_all_receipt, total_fine_all_receipt, remaining_overall_debt_with_fine_receipt = calculate_yearly_summary(
                                summary_debtor_name, total_loan_receipt, payments_df_receipt
                            )
                            yearly_summary_df_receipt = pd.DataFrame(summary_data_receipt)

                            receipt_pdf_buffer = create_receipt_pdf(
                                debtor_name=row['ผู้จ่าย'], 
                                payment_date=row['วันที่จ่าย_dt'].date(), 
                                amount_paid=row['จำนวน'], 
                                yearly_summary_df=yearly_summary_df_receipt,
                                total_loan=total_loan_receipt,
                                total_paid_all_years=total_paid_all_receipt,
                                remaining_overall_debt_with_fine=remaining_overall_debt_with_fine_receipt, 
                                total_fine_all_years=total_fine_all_receipt
                            )

                            st.download_button(
                                label="📄 พิมพ์ใบเสร็จสำหรับรายการนี้",
                                data=receipt_pdf_buffer,
                                file_name=f"ใบเสร็จ_{row['ผู้จ่าย']}_{row['วันที่จ่าย_dt'].strftime('%Y%m%d')}_{row['จำนวน']}.pdf", 
                                mime="application/pdf",
                                key=receipt_button_key
                            )

            else:
                st.info("ℹ️ ลูกหนี้ยังไม่มีประวัติการชำระเงิน")
        else:
            st.info("ℹ️ กรุณาเลือกชื่อลูกหนี้ที่ต้องการพิมพ์ใบเสร็จ.")

    if 'show_edit_form' in st.session_state and st.session_state.show_edit_form:
        edit_data = st.session_state.edit_payment_data
        
        with st.form("edit_payment_dialog", clear_on_submit=False):
            st.subheader(f"แก้ไขรายการชำระเงินสำหรับ: {edit_data['debtor_name']}")
            edited_date = st.date_input("วันที่จ่าย", edit_data['payment_date'], key="edit_dialog_pay_date_input")
            edited_amount = st.number_input("จำนวน (บาท)", value=float(edit_data['amount']), min_value=0.0, step=100.0, key="edit_dialog_pay_amount_input")
            edited_note = st.text_input("หมายเหตุ", value=edit_data['note'], key="edit_dialog_pay_note_input")

            col_edit1, col_edit2 = st.columns(2)
            with col_edit1:
                update_submitted = st.form_submit_button("✅ อัปเดตการชำระเงิน")
            with col_edit2:
                cancel_edit = st.form_submit_button("❌ ยกเลิก")

            if update_submitted:
                updated_payment_list_for_gsheet = [
                    edit_data['debtor_name'], 
                    edited_date.strftime("%Y-%m-%d"), 
                    edited_amount, 
                    edited_note 
                ]
                try:
                    client = get_gspread_client()
                    ws = client.open_by_url(GSHEET_URL).worksheet("pay")
                    # Update all cells in the row based on the known index
                    ws.update(f'A{edit_data["sheet_row_index"]}:{chr(ord("A")+len(PAYMENT_GSHEET_COLS)-1)}{edit_data["sheet_row_index"]}', [updated_payment_list_for_gsheet])
                    
                    st.success("✅ **อัปเดตข้อมูลการชำระเงินเรียบร้อยแล้ว!**")
                    st.session_state.show_edit_form = False 
                    clear_cache_and_rerun() 
                except gspread.exceptions.APIError as e:
                    st.error(f"❌ **เกิดข้อผิดพลาดในการอัปเดตข้อมูล**: {e}")
            
            if cancel_edit:
                st.session_state.show_edit_form = False
                st.rerun() 

# ========== PAGE: จัดการลูกหนี้ ==========
elif menu == "👤 จัดการลูกหนี้":
    st.header("⚙️ **จัดการข้อมูลลูกหนี้**")

    with st.expander("➕ **เพิ่มลูกหนี้ใหม่**", expanded=True):
        with st.form("add_debtor", clear_on_submit=True):
            new_name = st.text_input("ชื่อลูกหนี้ใหม่", key="add_debtor_name_input")
            new_total = st.number_input("รวมเงินกู้ทั้งหมด (บาท)", min_value=0.0, step=1000.0, key="add_debtor_total_input")
            add_btn = st.form_submit_button("✅ เพิ่มลูกหนี้")

        if add_btn:
            if new_name in debtor_names:
                st.warning("⚠️ ชื่อนี้มีอยู่แล้ว กรุณาใช้ชื่ออื่น")
            else:
                new_id = customers_df['ลำดับที่'].max() + 1 if not customers_df.empty else 1 
                new_customer_row_data = {
                    'ลำดับที่': new_id, 
                    'ชื่อ': new_name, 
                    'รวมเงินกู้ทั้งหมด': new_total 
                }
                new_customer_row_df = pd.DataFrame([new_customer_row_data], columns=CUSTOMER_GSHEET_COLS)
                updated_customers_df = pd.concat([customers_df[CUSTOMER_GSHEET_COLS], new_customer_row_df], ignore_index=True)
                
                write_df_to_sheet("customers", updated_customers_df, CUSTOMER_GSHEET_COLS) 
                st.success(f"🎉 **เพิ่มลูกหนี้ {new_name} เรียบร้อยแล้ว!**")
                clear_cache_and_rerun() # Force rerun to refresh data
    
    st.markdown("---") 

    with st.expander("✏️ **แก้ไขยอดเงินกู้ทั้งหมดของลูกหนี้**", expanded=True):
        if not debtor_names:
            st.info("ℹ️ ยังไม่มีลูกหนี้ให้แก้ไข")
        else:
            debtor_to_edit_loan = st.selectbox("เลือกชื่อลูกหนี้ที่ต้องการแก้ไขยอดเงินกู้", debtor_names, key="edit_loan_debtor_select")
            if debtor_to_edit_loan:
                current_loan = customers_df[customers_df['ชื่อ'] == debtor_to_edit_loan]['รวมเงินกู้ทั้งหมด'].iloc[0] 
                new_loan_amount = st.number_input(f"ยอดเงินกู้ใหม่สำหรับ {debtor_to_edit_loan} (ปัจจุบัน: {current_loan:,.2f} บาท)", 
                                                value=float(current_loan), min_value=0.0, step=1000.0, key="new_loan_amount_input")
                if st.button("💾 บันทึกการแก้ไขยอดเงินกู้", key="save_edited_loan_button"):
                    customers_df.loc[customers_df['ชื่อ'] == debtor_to_edit_loan, 'รวมเงินกู้ทั้งหมด'] = new_loan_amount 
                    write_df_to_sheet("customers", customers_df, CUSTOMER_GSHEET_COLS) 
                    st.success(f"✅ **แก้ไขยอดเงินกู้ของ {debtor_to_edit_loan} เป็น {new_loan_amount:,.2f} บาท เรียบร้อยแล้ว!**")
                    clear_cache_and_rerun() # Force rerun to refresh data
    
    st.markdown("---") 

    st.subheader("📋 **รายชื่อลูกหนี้ทั้งหมด**")
    st.dataframe(customers_df[['ลำดับที่', 'ชื่อ', 'รวมเงินกู้ทั้งหมด']], use_container_width=True, hide_index=True)
    
    st.markdown("---") 

    with st.expander("🗑️ **ลบลูกหนี้**", expanded=False): 
        if not debtor_names:
            st.info("ℹ️ ไม่มีลูกหนี้ให้ลบ")
        else:
            debtor_to_delete = st.selectbox("เลือกชื่อลูกหนี้ที่ต้องการลบ", debtor_names, key="delete_debtor_select")
            
            st.warning(f"⚠️ การดำเนินการนี้จะลบข้อมูลของ **{debtor_to_delete}** และประวัติการชำระเงินทั้งหมดออกไปอย่างถาวร")
            confirm_delete = st.checkbox(f"ฉันเข้าใจและยืนยันที่จะลบข้อมูลลูกหนี้ '{debtor_to_delete}' รายนี้อย่างถาวร", key="confirm_delete_checkbox")
            
            if st.button("❗ ลบลูกหนี้", key="delete_debtor_button", disabled=not confirm_delete):
                if confirm_delete:
                    try:
                        # ลบจาก customers_df
                        updated_customers_df = customers_df[customers_df['ชื่อ'] != debtor_to_delete].copy()
                        write_df_to_sheet("customers", updated_customers_df, CUSTOMER_GSHEET_COLS)
                        st.success(f"🗑️ **ลบลูกหนี้ {debtor_to_delete} ออกจากชีท 'customers' เรียบร้อยแล้ว!**")

                        # ลบประวัติการชำระเงินทั้งหมดของลูกหนี้รายนี้
                        client = get_gspread_client()
                        pay_sheet = client.open_by_url(GSHEET_URL).worksheet("pay")
                        all_pay_values = pay_sheet.get_all_values()

                        if not all_pay_values: 
                            st.success(f"🗑️ **ลบลูกหนี้ {debtor_to_delete} และประวัติการชำระเงิน (ไม่มีประวัติ) เรียบร้อยแล้ว!**")
                        else:
                            pay_headers = [_normalize_gsheet_col_name(h) for h in all_pay_values[0]]
                            pay_data_to_keep = [all_pay_values[0]] 
                            
                            for row_idx, row_data in enumerate(all_pay_values[1:]): 
                                try:
                                    payer_col_index = pay_headers.index("ผู้จ่าย")
                                    if _normalize_gsheet_col_name(row_data[payer_col_index]) != debtor_to_delete:
                                        pay_data_to_keep.append(row_data)
                                except (ValueError, IndexError):
                                    pay_data_to_keep.append(row_data)

                            pay_sheet.clear()
                            pay_sheet.update(pay_data_to_keep)
                            
                            st.success(f"🗑️ **ลบลูกหนี้ {debtor_to_delete} และประวัติการชำระเงินทั้งหมดเรียบร้อยแล้ว!**")
                            clear_cache_and_rerun() 
                            
                    except Exception as e:
                        st.error(f"❌ **เกิดข้อผิดพลาดในการลบประวัติการชำระเงิน**: {e}")
                        st.warning("⚠️ ลูกหนี้ถูกลบแล้ว แต่อาจมีประวัติการชำระเงินค้างอยู่ใน Google Sheet 'pay' โปรดตรวจสอบด้วยตนเอง")
                else:
                    st.warning("โปรดติ๊กช่องยืนยันการลบก่อน")