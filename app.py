import streamlit as st
import pandas as pd
import os
import json
import google.generativeai as genai
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, Border, Side, Alignment
import re
from copy import copy

# --- Configuration and API Key ---
st.set_page_config(page_title="Складов AI Асистент", layout="centered")

def get_api_key():
    try:
        return st.secrets["GEMINI_API_KEY"]
    except (FileNotFoundError, KeyError):
        try:
            with open("config.txt", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return None

GEMINI_API_KEY = get_api_key()
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    st.error("Вашият Gemini API ключ не е намерен. Моля, добавете го в secrets.toml или config.txt.")

# --- File Names ---
DOCUMENTS_EXCEL_FILE = "Книга1.xlsx"
INVENTORY_EXCEL_FILE = "inventory.xlsx"


# --- Data Loading Functions ---
@st.cache_data
def load_documents_data(file_path):
    try:
        if not os.path.exists(file_path):
            st.error(f"Файлът '{file_path}' не е намерен. Моля, уверете се, че е в същата папка.")
            return None
        df = pd.read_excel(file_path, header=3, dtype=str).fillna('')
        df.columns = df.columns.str.strip().str.replace(r'\s+', ' ', regex=True)
        if 'Бележка' not in df.columns:
            df['Бележка'] = ''
        df_display = df[df['Клиент име'].str.strip().str.upper() != 'ОБЩО']
        return df_display
    except Exception as e:
        st.error(f"Грешка при зареждане на '{file_path}': {e}")
        return None

@st.cache_data
def load_inventory_data(file_path):
    try:
        if not os.path.exists(file_path):
            st.error(f"Файлът '{file_path}' не е намерен. Моля, уверете се, че е в същата папка.")
            return None
        return pd.read_excel(file_path, dtype=str).fillna('')
    except Exception as e:
        st.error(f"Грешка при зареждане на '{file_path}': {e}")
        return None

# --- AI and Helper Functions ---
def find_document_column_name(df):
    possible_names = ['Фактура №', 'фактура №', 'Номер на документ', 'Фактура']
    for name in possible_names:
        if name in df.columns:
            return name
    return None

# --- NEW: Restored and Improved AI Function ---
def run_ai_doc_search(doc_number, data_string, doc_column_name):
    """
    Uses a more robust "few-shot" prompt to guide the AI, making it more reliable.
    """
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
    3. If no document is found, or if you cannot process the data, return an empty JSON object like `{{"документи": []}}`.
    """
    try:
        response = model.generate_content(prompt)
        clean_response = response.text.strip().replace("```json", "").replace("```", "")
        if not clean_response or not clean_response.strip().startswith('{'):
            return None
        return json.loads(clean_response)
    except Exception:
        return None


# --- File Writing Functions ---
def update_inventory(file_path, product_name, quantity_to_subtract):
    try:
        df = pd.read_excel(file_path)
        product_rows = df.index[df['Продукт'] == product_name].tolist()
        if not product_rows:
            raise ValueError(f"Продуктът '{product_name}' не беше намерен в '{file_path}'.")
        idx = product_rows[0]
        current_quantity = pd.to_numeric(df.loc[idx, 'Наличност'], errors='coerce')
        if pd.isna(current_quantity):
             raise TypeError(f"Наличността за '{product_name}' не е валидно число.")
        new_quantity = int(current_quantity) - int(quantity_to_subtract)
        if new_quantity < 0:
            raise ValueError(f"Недостатъчна наличност за '{product_name}'. Налични: {current_quantity}, Нужни: {quantity_to_subtract}.")
        df.loc[idx, 'Наличност'] = new_quantity
        df.to_excel(file_path, index=False)
        return True
    except PermissionError:
        raise PermissionError(f"Няма достъп до '{file_path}'. Моля, затворете файла, ако е отворен, и опитайте отново.")
    except Exception as e:
        raise e

def append_to_documents(file_path, row_data, all_cols):
    try:
        workbook = openpyxl.load_workbook(file_path)
        sheet = workbook.active
        try:
            client_name_col_index = all_cols.index('Клиент име') + 1
        except ValueError:
            client_name_col_index = 2
        insert_row_index = -1
        for row_num in range(sheet.max_row, 3, -1):
            cell_value = sheet.cell(row=row_num, column=client_name_col_index).value
            if isinstance(cell_value, str) and cell_value.strip().upper() == 'ОБЩО':
                insert_row_index = row_num
                break
        if insert_row_index == -1:
            insert_row_index = sheet.max_row + 1
        sheet.insert_rows(insert_row_index)
        style_source_row_num = insert_row_index - 1
        if style_source_row_num > 3:
            for col_idx, col_name in enumerate(all_cols, 1):
                source_cell = sheet.cell(row=style_source_row_num, column=col_idx)
                target_cell = sheet.cell(row=insert_row_index, column=col_idx)
                if source_cell.has_style:
                    target_cell._style = copy(source_cell._style)
                target_cell.value = row_data.get(col_name)
                if col_name == 'Дата' and isinstance(target_cell.value, datetime):
                    target_cell.number_format = 'm/d/yyyy'
        else:
            for col_idx, col_name in enumerate(all_cols, 1):
                 sheet.cell(row=insert_row_index, column=col_idx).value = row_data.get(col_name)
        workbook.save(file_path)
        return True
    except PermissionError:
        raise PermissionError(f"Няма достъп до '{file_path}'. Моля, затворете файла, ако е отворен, и опитайте отново.")
    except Exception as e:
        raise e

# --- Streamlit App ---
st.title("Складов AI Асистент 📦")

# Load Data
documents_df = load_documents_data(DOCUMENTS_EXCEL_FILE)
inventory_df = load_inventory_data(INVENTORY_EXCEL_FILE)

app_mode = st.sidebar.radio(
    "Изберете режим на работа:",
    ("Добавяне на запис", "Справка по Документ (с AI)", "Справка по Продукт")
)

# --- Mode 1: Add Entry ---
if app_mode == "Добавяне на запис":
    # ... (This section is unchanged)
    st.header("Добавяне на нов запис")
    st.info("Попълнете формата, за да добавите нов ред към 'Книга1.xlsx' и автоматично да обновите 'inventory.xlsx'.")
    all_cols_from_df = []
    try:
        temp_df = pd.read_excel(DOCUMENTS_EXCEL_FILE, header=3)
        all_cols_from_df = [re.sub(r'\s+', ' ', str(c).strip()) for c in temp_df.columns]
    except FileNotFoundError:
        pass
    except Exception as e:
        st.error(f"Неуспешно прочитане на колоните от '{DOCUMENTS_EXCEL_FILE}': {e}")
    if documents_df is None or inventory_df is None:
        st.warning("Един или повече от файловете не са заредени. Моля, проверете съобщенията за грешки по-горе.")
    else:
        try:
            start_index = all_cols_from_df.index('Общо кол-во') + 1
            end_index = all_cols_from_df.index('Цена')
            product_list = all_cols_from_df[start_index:end_index]
        except (ValueError, IndexError):
            st.error("Структурата на Excel файла е невалидна. Липсват колони 'Общо кол-во' или 'Цена'.")
            product_list = []
        if product_list:
            with st.form("new_entry_form"):
                st.subheader("Данни за документа")
                col1, col2 = st.columns(2)
                with col1:
                    doc_number = st.text_input("Фактура №", placeholder="Пример: 2000012345")
                    client_name = st.text_input("Име на клиент (ще бъде с главни букви)")
                with col2:
                    doc_date = st.date_input("Дата на издаване", value=datetime.now())
                    doc_note = st.text_input("Бележка")
                st.subheader("Данни за продукта")
                col3, col4, col5 = st.columns(3)
                with col3:
                    selected_product = st.selectbox("Избери продукт", options=product_list)
                with col4:
                    quantity = st.number_input("Количество", min_value=1, step=1)
                with col5:
                    price = st.number_input("Ед. цена (лв.)", min_value=0.0, value=0.0, format="%.2f")
                submitted = st.form_submit_button("✅ Запази записа и обнови наличности")
                if submitted:
                    if not doc_number or not client_name or not selected_product:
                        st.warning("Моля, попълнете 'Фактура №', 'Име на клиент' и изберете продукт.")
                    else:
                        new_row_data = {col: None for col in all_cols_from_df}
                        new_row_data['Дата'] = doc_date
                        new_row_data['Фактура №'] = doc_number
                        new_row_data['Клиент име'] = client_name.upper()
                        new_row_data['Бележка'] = doc_note
                        new_row_data['Общо кол-во'] = int(quantity)
                        new_row_data[selected_product] = int(quantity)
                        new_row_data['Цена'] = float(price)
                        new_row_data['Сума лв.'] = float(quantity) * float(price)
                        try:
                            update_inventory(INVENTORY_EXCEL_FILE, selected_product, quantity)
                            append_to_documents(DOCUMENTS_EXCEL_FILE, new_row_data, all_cols_from_df)
                            st.success(f"✅ Успешно! Записът е добавен и наличността за '{selected_product}' е обновена.")
                            st.balloons()
                            st.cache_data.clear()
                        except Exception as e:
                            st.error(f"❌ Грешка: {e}")

# --- Mode 2: Product Search ---
elif app_mode == "Справка по Продукт":
    # ... (This section is unchanged)
    st.header("Търсене по продукт")
    if documents_df is None or inventory_df is None:
        st.error("Един или повече от файловете ('Книга1.xlsx', 'inventory.xlsx') не са намерени.")
    else:
        doc_column_name = find_document_column_name(documents_df)
        if not doc_column_name:
            st.error("Не мога да намеря колона за номер на документ.")
        else:
            all_cols = documents_df.columns.tolist()
            try:
                start_index = all_cols.index('Общо кол-во') + 1
                end_index = all_cols.index('Цена')
                product_list = all_cols[start_index:end_index]
            except ValueError:
                st.error("Не са намерени колоните 'Общо кол-во' или 'Цена'.")
                product_list = []
            selected_product = st.selectbox("Изберете продукт:", product_list)
            if st.button("Търси"):
                matching_docs = documents_df[documents_df[selected_product].notna() & (documents_df[selected_product] != '')].copy()
                inventory_info = inventory_df[inventory_df['Продукт'].str.strip().str.replace(r'\s+', ' ', regex=True) == selected_product]
                quantity_available = inventory_info['Наличност'].iloc[0] if not inventory_info.empty else '0'
                st.metric(label=f"Наличност за '{selected_product}'", value=f"{quantity_available} бр.")
                st.subheader("Документи, съдържащи продукта:")
                if matching_docs.empty:
                    st.info("Няма документи, съдържащи този продукт.")
                else:
                    processed_rows = []
                    for index, row in matching_docs.iterrows():
                        new_row = {
                            doc_column_name: row.get(doc_column_name),
                            'Дата на издаване': row.get('Дата'),
                            'Име на клиент': row.get('Клиент име'),
                            'Бележка': row.get('Бележка', ''),
                            'Количество': row.get(selected_product),
                            'Цена': row.get('Цена'),
                            'Сума лв.': row.get('Сума лв.')
                        }
                        processed_rows.append(new_row)
                    for doc_item in processed_rows:
                        with st.expander(f"**Документ №:** {doc_item.get(doc_column_name, '-')} | **Клиент:** {doc_item.get('Име на клиент', '-')}"):
                            st.markdown(f"**Дата:** {doc_item.get('Дата на издаване', '-')}")
                            st.markdown(f"**Бележка:** *{doc_item.get('Бележка') or 'Няма'}*")
                            st.markdown(f"**Количество:** {doc_item.get('Количество', '-')} | **Цена:** {doc_item.get('Цена', '-')} лв. | **Сума:** {doc_item.get('Сума лв.', '-')} лв.")

# --- Mode 3: Document Search (Reverted to AI with improved prompt) ---
elif app_mode == "Справка по Документ (с AI)":
    st.header("Търсене по номер на документ (с AI)")
    if documents_df is None:
        st.error(f"Файлът '{DOCUMENTS_EXCEL_FILE}' не е намерен.")
    else:
        doc_column_name = find_document_column_name(documents_df)
        if not doc_column_name:
            st.error("Не мога да намеря колона за номер на документ.")
        else:
            doc_number = st.text_input("Въведете номер на документ:").strip()
            if st.button("Търси с AI"):
                if not doc_number:
                    st.warning("Моля, въведете номер на документ.")
                else:
                    # First, filter with pandas to get a relevant subset of data
                    matching_docs_df = documents_df[documents_df[doc_column_name].astype(str).str.strip() == doc_number]
                    if matching_docs_df.empty:
                        st.error(f"Документ с номер '{doc_number}' не е намерен в данните.")
                    else:
                        # Convert only the relevant part of the DataFrame to a CSV string
                        data_string_subset = matching_docs_df.to_csv(index=False)
                        with st.spinner("AI анализира данните... Моля, изчакайте."):
                            # Call the new, more reliable AI function
                            result = run_ai_doc_search(doc_number, data_string_subset, doc_column_name)

                        if not result or not result.get("документи"):
                            st.error(f"AI не успя да обработи документ №{doc_number}. Опитайте отново или проверете данните във файла.")
                        else:
                            st.success(f"Намерени са {len(result['документи'])} записа за документ №{doc_number}")
                            for doc_item in result.get("документи", []):
                                with st.expander(f"**Клиент:** {doc_item.get('Име на клиент', '-')} | **Продукт:** {doc_item.get('Име на продукт', '-')}"):
                                    st.markdown(f"**Дата на издаване:** {doc_item.get('Дата на издаване', '-')}")
                                    st.markdown(f"**Бележка към записа:** *{doc_item.get('Бележка', 'Няма')}*")
                                    st.markdown(
                                        f"**Количество:** {doc_item.get('Количество', '-')} | **Цена:** {doc_item.get('Цена', '-')} | **Сума:** {doc_item.get('Сума лв.', '-')}")