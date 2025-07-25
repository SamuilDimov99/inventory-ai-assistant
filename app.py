import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import set_with_dataframe
from datetime import datetime
import re
import json
import google.generativeai as genai
from copy import copy

# --- Page and PWA Configuration ---
st.set_page_config(
    page_title="Складов AI Асистент",
    layout="centered",
    page_icon="static/icon-192x192.png" # Sets the browser tab icon
)
# Link to the PWA manifest
st.markdown('<link rel="manifest" href="/static/manifest.json">', unsafe_allow_html=True)


# --- API Key Configuration ---
# This function configures the Gemini API key from Streamlit Secrets
def configure_genai():
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
        genai.configure(api_key=api_key)
        return True
    except (KeyError, FileNotFoundError):
        st.error("Вашият Gemini API ключ не е намерен в Streamlit Secrets. Моля, добавете го.")
        return False

# Configure the API at the start
AI_ENABLED = configure_genai()

# --- Google Sheets Authentication and Functions ---
@st.cache_resource
def get_gspread_client():
    """Initializes and returns the gspread client using Streamlit Secrets."""
    try:
        return gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    except Exception as e:
        st.error(f"Грешка при свързване с Google Sheets: {e}")
        return None


@st.cache_data(ttl=60)  # Cache data for 60 seconds
def load_data_from_sheet(sheet_name):
    """Loads data from a specified Google Sheet into a pandas DataFrame."""
    client = get_gspread_client()
    if not client:
        return None
    try:
        sheet = client.open(sheet_name).sheet1
        # For "SalesData", headers are on row 4. For "Inventory", on row 1.
        header_row = 4 if sheet_name == "SalesData" else 1
        all_data = sheet.get_all_records(head=header_row, default_blank="")
        df = pd.DataFrame(all_data)
        # Clean up column names by removing extra spaces
        df.columns = [re.sub(r'\s+', ' ', str(c).strip()) for c in df.columns]

        # --- FIX: Filter out the 'TOTAL' row ---
        if 'Клиент име' in df.columns:
            df = df[df['Клиент име'].astype(str).str.strip().str.upper() != 'ОБЩО']

        return df.fillna('')
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"Google Sheet с име '{sheet_name}' не е намерен. Моля, проверете името и правата за достъп.")
        return None
    except Exception as e:
        st.error(f"Грешка при зареждане на '{sheet_name}': {e}")
        return None

def update_inventory(product_name, quantity_to_subtract):
    """Finds a product in the Inventory sheet and updates its quantity."""
    client = get_gspread_client()
    if not client: return False
    try:
        sheet = client.open("Inventory").sheet1
        cell = sheet.find(product_name, in_column=1)
        if not cell:
            st.error(f"Продукт '{product_name}' не е намерен в 'Inventory'.")
            return False
        current_quantity = int(sheet.cell(cell.row, 2).value)
        new_quantity = current_quantity - quantity_to_subtract
        if new_quantity < 0:
            st.error(f"Недостатъчна наличност за '{product_name}'.")
            return False
        sheet.update_cell(cell.row, 2, new_quantity)
        load_data_from_sheet.clear() # Clear cache to show update
        return True
    except Exception as e:
        st.error(f"Грешка при обновяване на инвентара: {e}")
        return False


def append_to_sales(row_data, all_cols):
    """Appends a new row of data to the SalesData sheet before the 'TOTAL' row."""
    client = get_gspread_client()
    if not client: return False
    try:
        sheet = client.open("SalesData").sheet1
        # Find the "ОБЩО" row to insert above it
        total_cell = sheet.find("ОБЩО")  # Search the entire sheet
        insert_row_index = total_cell.row if total_cell else len(sheet.get_all_values()) + 1
        row_to_insert = [row_data.get(col, '') for col in all_cols]

        # --- THE FIX: Add inherit_from_before=True ---
        # This tells Google Sheets to copy the style from the row ABOVE, not below.
        sheet.insert_row(
            row_to_insert,
            insert_row_index,
            value_input_option='USER_ENTERED',
            inherit_from_before=True
        )

        load_data_from_sheet.clear()  # Clear cache
        return True
    except Exception as e:
        st.error(f"Грешка при добавяне на запис в 'SalesData': {e}")
        return False

# --- Restored AI Search Function ---
def run_ai_doc_search(doc_number, data_string, doc_column_name):
    """Uses the improved 'few-shot' prompt to reliably find doc info."""
    if not AI_ENABLED:
        st.error("AI функцията е деактивирана поради липсващ API ключ.")
        return None
    model = genai.GenerativeModel('gemini-1.5-pro-latest')
    prompt = f"""
    You are an expert AI assistant for analyzing tabular data from a CSV string.
    Your task is to find all rows for document number '{doc_number}' and extract the specified information for each row into a valid JSON format.
    The main challenge is to correctly identify the 'Име на продукт' (Product Name) and 'Количество' (Quantity). The 'Име на продукт' is the *name of the column* that contains the quantity for that specific row. This column will be located between the 'Общо кол-во' and 'Цена' columns.
    ---
    **EXAMPLE:**
    *Input Data Snippet:*
    ```csv
    Клиент име,Бележка,Дата,Фактура №,Общо кол-во,Product A,Product B,Цена,Сума лв.
    ЗП ИВАН ПЕТРОВ,,2024-07-20,59460,10,,10,150.00,1500.00
    ```
    *Desired JSON Output for the example:*
    ```json
    {{
      "документи": [
        {{
          "Име на клиент": "ЗП ИВАН ПЕТРОВ",
          "Бележка": "",
          "Дата на издаване": "2024-07-20",
          "Име на продукт": "Product B",
          "Количество": "10",
          "Цена": "150.00",
          "Сума лв.": "1500.00"
        }}
      ]
    }}
    ```
    ---
    **NOW, ANALYZE THE FOLLOWING DATA AND PROVIDE THE JSON OUTPUT:**
    **Document to find:** '{doc_number}'
    **Data:**
    ```csv
    {data_string}
    ```
    **Instructions:**
    1. Find ALL rows where the '{doc_column_name}' column is exactly '{doc_number}'.
    2. For each matching row:
        - Extract "Име на клиент", "Бележка", "Дата", "Цена", and "Сума лв." directly from their columns. Use the 'Дата' value for "Дата на издаване".
        - To find "Име на продукт" and "Количество": Look at the columns between "Общо кол-во" and "Цена". The one column that has a number in it for this specific row is the "Име на продукт", and the number itself is the "Количество".
    3. If no document is found, return an empty JSON object like `{{"документи": []}}`.
    """
    try:
        response = model.generate_content(prompt)
        clean_response = response.text.strip().replace("```json", "").replace("```", "")
        if not clean_response or not clean_response.strip().startswith('{'):
            return None
        return json.loads(clean_response)
    except Exception:
        return None

# --- Main Streamlit App Logic ---
st.title("Складов AI Асистент 📦")

# Load data from Google Sheets
documents_df = load_data_from_sheet("SalesData")
inventory_df = load_data_from_sheet("Inventory")

app_mode = st.sidebar.radio(
    "Изберете режим на работа:",
    ("Добавяне на запис", "Справка по Документ (с AI)", "Справка по Продукт")
)

# --- Mode 1: Add Entry ---
if app_mode == "Добавяне на запис":
    st.header("Добавяне на нов запис")
    if documents_df is None:
        st.warning("Не мога да заредя 'SalesData'. Проверете настройките.")
    else:
        all_cols = documents_df.columns.tolist()
        try:
            start_index = all_cols.index('Общо кол-во') + 1
            end_index = all_cols.index('Цена')
            product_list = all_cols[start_index:end_index]
        except (ValueError, IndexError):
            product_list = []
            st.error("Структурата на 'SalesData' е невалидна. Липсват 'Общо кол-во' или 'Цена'.")

        if product_list:
            with st.form("new_entry_form"):
                st.subheader("Данни за документа")
                client_name = st.text_input("Име на клиент")
                doc_number = st.text_input("Фактура №")
                doc_date = st.date_input("Дата на издаване", value=datetime.now())
                doc_note = st.text_input("Бележка")
                selected_product = st.selectbox("Избери продукт", options=product_list)
                quantity = st.number_input("Количество", min_value=1, step=1)
                price = st.number_input("Ед. цена (лв.)", min_value=0.0, format="%.2f")
                submitted = st.form_submit_button("✅ Запази записа")

                if submitted:
                    if not doc_number or not client_name:
                        st.warning("Моля, попълнете 'Фактура №' и 'Име на клиент'.")
                    else:
                        st.info("Обработка...")
                        if update_inventory(selected_product, quantity):
                            new_row_data = {col: '' for col in all_cols}
                            new_row_data['Дата'] = doc_date.strftime('%m/%d/%Y')
                            new_row_data['Фактура №'] = doc_number
                            new_row_data['Клиент име'] = client_name.upper()
                            new_row_data['Бележка'] = doc_note
                            new_row_data['Общо кол-во'] = int(quantity)
                            new_row_data[selected_product] = int(quantity)
                            new_row_data['Цена'] = float(price)
                            new_row_data['Сума лв.'] = float(quantity) * float(price)
                            if append_to_sales(new_row_data, all_cols):
                                st.success("✅ Записът е добавен и наличностите са обновени!")
                                st.balloons()
                            else:
                                st.error("❌ Грешка при запазване на записа. Проверете ръчно.")
                        else:
                            st.error("❌ Грешка при обновяване на инвентара.")

# --- Mode 2: Product Search ---
# --- Mode 2: Product Search ---
elif app_mode == "Справка по Продукт":
    st.header("Търсене по продукт")
    if documents_df is None or inventory_df is None:
        st.error("Не мога да заредя данните от Google Sheets.")
    else:
        all_cols = documents_df.columns.tolist()
        try:
            start_index = all_cols.index('Общо кол-во') + 1
            end_index = all_cols.index('Цена')
            product_list = all_cols[start_index:end_index]
            selected_product = st.selectbox("Изберете продукт:", product_list)

            if st.button("Търси"):
                if selected_product:
                    # Inventory check
                    inventory_info = inventory_df[inventory_df['Продукт'] == selected_product]
                    quantity_available = inventory_info['Наличност'].iloc[0] if not inventory_info.empty else '0'
                    st.metric(label=f"Наличност за '{selected_product}'", value=f"{quantity_available} бр.")

                    # Find all documents containing the product
                    # pd.to_numeric helps handle any non-number values safely
                    matching_docs = documents_df[pd.to_numeric(documents_df[selected_product], errors='coerce').notna()]
                    st.subheader(f"Документи, съдържащи '{selected_product}':")

                    if matching_docs.empty:
                        st.info("Няма намерени документи за този продукт.")
                    else:
                        # --- IMPROVEMENT: Display results in clean expanders ---
                        for index, row in matching_docs.iterrows():
                            with st.expander(
                                    f"**Документ №:** {row.get('Фактура №', '-')} | **Клиент:** {row.get('Клиент име', '-')}"):
                                st.markdown(f"**Дата:** {row.get('Дата', '-')}")
                                st.markdown(f"**Бележка:** *{row.get('Бележка', 'Няма')}*")
                                st.markdown(
                                    f"**Количество:** {row.get(selected_product, '-')} | **Цена:** {row.get('Цена', '-')} лв. | **Сума:** {row.get('Сума лв.', '-')} лв.")

        except (ValueError, IndexError):
            st.error("Структурата на 'SalesData' е невалидна.")


# --- Mode 3: AI Document Search ---
elif app_mode == "Справка по Документ (с AI)":
    st.header("Търсене по номер на документ (с AI)")
    if documents_df is None:
        st.error("Не мога да заредя данните от Google Sheets.")
    else:
        doc_column_name = 'Фактура №'
        if doc_column_name not in documents_df.columns:
            st.error(f"Липсва колона '{doc_column_name}' в 'SalesData'.")
        else:
            doc_number = st.text_input("Въведете номер на документ:").strip()
            if st.button("Търси с AI"):
                if not doc_number:
                    st.warning("Моля, въведете номер на документ.")
                else:
                    matching_docs_df = documents_df[documents_df[doc_column_name].astype(str) == doc_number]
                    if matching_docs_df.empty:
                        st.error(f"Документ №'{doc_number}' не е намерен.")
                    else:
                        data_string_subset = matching_docs_df.to_csv(index=False)
                        with st.spinner("AI анализира данните..."):
                            result = run_ai_doc_search(doc_number, data_string_subset, doc_column_name)
                        if not result or not result.get("документи"):
                            st.error(f"AI не успя да обработи документ №{doc_number}.")
                        else:
                            st.success(f"Намерени са {len(result['документи'])} записа за документ №{doc_number}")
                            for doc_item in result.get("документи", []):
                                with st.expander(f"**Клиент:** {doc_item.get('Име на клиент', '-')} | **Продукт:** {doc_item.get('Име на продукт', '-')}"):
                                    st.markdown(f"**Дата на издаване:** {doc_item.get('Дата на издаване', '-')}")
                                    st.markdown(f"**Бележка:** *{doc_item.get('Бележка', 'Няма')}*")
                                    st.markdown(f"**Количество:** {doc_item.get('Количество', '-')} | **Цена:** {doc_item.get('Цена', '-')} | **Сума:** {doc_item.get('Сума лв.', '-')}")