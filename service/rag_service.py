from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from openai import OpenAI
import csv
import re
from collections import Counter
from service.query_intent import (
    is_employee_count_by_department_question,
    is_employee_count_question,
)

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
CSV_PATH = DATA_DIR / "hr" / "hr_data.csv"

def load_local_context(collection: str) -> str | None:
    collection_dir = DATA_DIR / collection

    if not collection_dir.exists():
        return None

    context_parts = []

    for file_path in sorted(collection_dir.glob("*")):
        if file_path.is_file() and file_path.suffix.lower() in {
            ".md", ".txt", ".csv", ".json", ".yaml", ".yml"
        }:
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = file_path.read_text(
                    encoding="utf-8", errors="ignore"
                )

            context_parts.append(
                f"File Location: {file_path.as_posix()}\nContent:\n{content}"
            )

    return "\n\n---\n\n".join(context_parts) if context_parts else None


def query_rag(query: str, collection: str) -> str:
    if collection.casefold() == "hr" and is_employee_count_question(query):
        return get_employee_count_answer(query)

    load_dotenv()
    client = OpenAI()

    try:
        embedding_model = OpenAIEmbeddings(
            model="text-embedding-3-small"
        )

        vector_db = QdrantVectorStore.from_existing_collection(
            url="http://localhost:6333",
            collection_name=collection,
            embedding=embedding_model,
        )

        search_results = vector_db.similarity_search(
            query=query,
            k=3,
        )

        context_list = [
            f"File Location: {res.metadata.get('source')}\n"
            f"Content:\n{res.page_content}"
            for res in search_results
        ]

        context = "\n\n---\n\n".join(context_list)

    except Exception:
        local_context = load_local_context(collection)

        if not local_context:
            raise RuntimeError(
                "No department context was found locally and "
                "the Qdrant collection could not be reached."
            )

        context = local_context

    system_prompt = f"""
    You are a helpful AI assistant who answers questions
    using the provided context.

    Use only the information from the context below.

    Context:
    {context}
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
    )

    return response.choices[0].message.content or ""

def get_employee_count(department=None):
    """Count employees directly from the HR CSV."""

    employees = _load_employee_records()

    if department:
        employees = [
            row for row in employees
            if row.get("department", "").strip().casefold()
            == department.strip().casefold()
        ]

    return len(employees)


def _load_employee_records() -> list[dict[str, str]]:
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        return [
            row
            for row in csv.DictReader(file)
            if row.get("employee_id", "").strip()
        ]


def get_employee_count_answer(query: str) -> str:
    employees = _load_employee_records()
    department_counts = Counter(
        row.get("department", "").strip() or "Unspecified"
        for row in employees
    )
    total = len(employees)

    if is_employee_count_by_department_question(query):
        breakdown = "\n".join(
            f"- {department}: {count}"
            for department, count in sorted(department_counts.items(), key=lambda item: item[0].casefold())
        )
        return (
            f"The HR dataset contains {total} employee records. "
            f"Breakdown by department:\n{breakdown}"
        )

    normalized_query = query.casefold()
    matched_departments = [
        department
        for department in department_counts
        if re.search(rf"(?<!\w){re.escape(department.casefold())}(?!\w)", normalized_query)
    ]
    if matched_departments:
        breakdown = "\n".join(
            f"- {department}: {department_counts[department]}"
            for department in sorted(matched_departments, key=str.casefold)
        )
        return f"Employee records for the requested department(s):\n{breakdown}"

    return f"The HR dataset contains {total} employee records."