# Departmental Knowledge Assistant

A Streamlit chat application backed by a FastAPI service. It answers questions from department-specific documents using OpenAI embeddings, Qdrant vector search, and an OpenAI chat model. User accounts are authenticated with JWTs and can query only the collections allowed for their role.

## Features

- Role-based access to department collections.
- First-run administrator setup and admin-managed user accounts.
- Local masking of obvious email addresses and phone numbers before a question is sent for processing.
- Retrieval-augmented answers from Markdown and CSV source files.
- Exact employee record counts calculated directly from the HR CSV, including department totals.

## Requirements

- Python 3.13 (the project environment is configured for Python 3.13).
- A valid OpenAI API key.
- Qdrant running at `http://localhost:6333` with collections indexed for the departments you want to query.

## Setup

Open PowerShell in this project directory:

```powershell
cd "D:\LLM Project\Python Udemy\enterprise-rag-rbac"
```

Create and activate a virtual environment, then install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Create a `.env` file in this directory if one does not already exist. Set these variables in it:

```dotenv
OPENAI_API_KEY=your-openai-api-key
JWT_SECRET_KEY=replace-with-a-long-random-secret
```

Keep `.env` private; do not commit API keys or other secrets. The API will not start if `JWT_SECRET_KEY` is missing.

Create the local administrator account (and optionally initial role accounts):

```powershell
python setup_users.py
```

This creates `users.db` locally. Each checkout has its own ignored database, so each person must create their own accounts. Keep passwords private; do not commit `users.db`.

## Start the application

Start Qdrant separately and make sure it is reachable at `http://localhost:6333`.

In the first PowerShell window, start the API:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

In a second PowerShell window opened in this project directory, start Streamlit:

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run app.py
```

Open the Streamlit URL shown in the terminal (normally `http://localhost:8501`) and sign in with the administrator account created by `setup_users.py`. Administrators can create more user accounts and assign roles in the app.

The FastAPI interactive API documentation is available at `http://127.0.0.1:8000/docs`.

## Department collections and permissions

The folders under `data` are the source collections. The collection names are their folder names:

- `engineering`
- `finance`
- `general`
- `hr`
- `marketing`

The collection names in Qdrant must match these names. Roles have the following access:

| Role | Collections |
| --- | --- |
| Finance Team | `finance` |
| Marketing Team | `marketing` |
| HR Team | `hr` |
| Engineering Department | `engineering` |
| Employee | `general` |
| C-Level Executive | `engineering`, `finance`, `marketing`, `hr`, `general` |

The administrator role manages users and does not have chat collection access by default.

## Index or update source files

The incremental indexer reads Markdown and CSV files from each directory under `data` and updates the matching Qdrant collection:

```powershell
.\.venv\Scripts\Activate.ps1
python codebasics_index_incremental.py
```

It requires Qdrant and OpenAI credentials. The indexer tracks indexed source files in `index_manifest.db`; unchanged files are skipped.

## Employee count questions

Employee totals are computed from `data\hr\hr_data.csv`, not inferred from the limited set of chunks returned by vector search. The count includes records with a non-empty `employee_id`.

Select the **HR** collection and try questions such as:

- `How many employees work in my company?`
- `How many in Finance department?`
- `How many employees are in each department?`

The department names and totals come from the CSV's `department` column. The HR data does not include a reliable active/inactive status field, so these answers count employee records, not necessarily currently active employees.

## Project layout

```text
codebasics_rag/
├── api.py                         # FastAPI API, login, authorization, and chat endpoint
├── app.py                         # Streamlit UI
├── codebasic_chat.py              # PII masking and query scope checks
├── codebasics_index_incremental.py # Incremental Qdrant indexing
├── rbac.py                        # Local SQLite accounts and role permissions
├── setup_users.py                 # First-run administrator and optional role-account setup
├── service/
│   ├── query_intent.py            # Employee-count question detection
│   └── rag_service.py             # RAG query flow and exact HR CSV counts
└── data/                          # Source files organized by collection
```
