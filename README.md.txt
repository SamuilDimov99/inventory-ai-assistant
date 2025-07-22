# Складов AI Асистент (Inventory AI Assistant)

A Streamlit application for managing sales and inventory data from Excel files, featuring AI-assisted search capabilities.

## ✨ Features

-   **Добавяне на запис (Add Record):** Add new sales entries, which automatically updates both the main sales ledger and the inventory file.
-   **Справка по Документ (с AI) (Search by Document):** Search for all items related to a specific invoice number using an AI-powered search.
-   **Справка по Продукт (Search by Product):** Check stock levels and see all sales records for a specific product.

## ⚙️ Setup and Installation

Follow these steps to run the application locally.

### 1. Clone the Repository

```bash
git clone [https://github.com/your-username/your-repo-name.git](https://github.com/your-username/your-repo-name.git)
cd your-repo-name
```

### 2. Create and Activate a Virtual Environment

It's highly recommended to use a virtual environment to manage project dependencies.

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Required Libraries

Install all necessary libraries using the `requirements.txt` file.

```bash
pip install -r requirements.txt
```

### 4. Set Up Data Files

This application requires two Excel files to be placed in the root directory:

-   `Книга1.xlsx`: The main sales ledger.
-   `inventory.xlsx`: A simple two-column file listing product names and current stock (`Продукт`, `Наличност`).

### 5. Add Your API Key

Create a file named `config.txt` in the root directory and paste your Gemini API key into it.

```text
# config.txt
YOUR_GEMINI_API_KEY_HERE
```
_Note: The `config.txt` file is included in `.gitignore` and will not be uploaded to GitHub for security reasons._

## 🚀 Running the Application

Once everything is set up, run the following command in your terminal:

```bash
streamlit run app.py
```

Your web browser should open with the application running.