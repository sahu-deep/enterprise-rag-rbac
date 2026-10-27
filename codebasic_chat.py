import re
from pathlib import Path
from service.query_intent import is_employee_count_question

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency in test environments
    def load_dotenv() -> bool:
        return False

try:
    from langchain_openai import OpenAIEmbeddings
    from langchain_qdrant import QdrantVectorStore
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency in test environments
    OpenAIEmbeddings = None
    QdrantVectorStore = None
    OpenAI = None

load_dotenv()
openai_client = OpenAI() if OpenAI else None

embedding_model = OpenAIEmbeddings(model="text-embedding-3-small") if OpenAIEmbeddings else None
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SUPPORTED_CONTEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}


def load_local_context(collection: str) -> str:
    """Read local markdown/text context files for the selected department."""
    collection_dir = DATA_DIR / collection
    if not collection_dir.exists():
        return ""

    context_parts = []
    for file_path in sorted(collection_dir.glob("*")):
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_CONTEXT_EXTENSIONS:
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            context_parts.append(content)

    return "\n\n".join(context_parts)


# =====================================================================
# GUARDRAIL 1: LOCAL PII SANITIZATION (Regex Approach)
# =====================================================================
def sanitize_pii(text: str) -> str:
    """Masks obvious email addresses and phone numbers locally before processing."""
    # Email regex
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[REDACTED_EMAIL]', text)
    # Generic 10-12 digit phone numbers
    text = re.sub(r'\b\+?\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b', '[REDACTED_PHONE]', text)
    return text

# =====================================================================
# GUARDRAIL 2: OUT-OF-SCOPE DETECTOR
# =====================================================================
def is_query_in_scope(query: str, collection: str, context: str | None = None, use_llm: bool = True) -> bool:
    """Return True when a question is relevant to the provided department context."""
    normalized_query = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
    normalized_collection = collection.lower()
    if normalized_collection == "hr" and is_employee_count_question(query):
        return True

    context_text = (context or load_local_context(normalized_collection) or "").lower()

    if not normalized_query or not context_text:
        return False

    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "about",
        "at",
        "for",
        "from",
        "give",
        "have",
        "how",
        "is",
        "in",
        "many",
        "of",
        "on",
        "please",
        "show",
        "tell",
        "that",
        "the",
        "this",
        "to",
        "what",
        "when",
        "where",
        "who",
        "why",
        "with",
        "you",
        "we",
    }
    query_terms = [term for term in normalized_query.split() if term not in stop_words and len(term) > 2]
    if not query_terms:
        return False

    context_terms = set(re.findall(r"[a-z0-9]+", context_text))
    if not context_terms:
        return False

    if any(term in context_terms for term in query_terms):
        return True
    if any(term in context_text for term in query_terms):
        return True

    engineering_keywords = {
        "microservice",
        "microservices",
        "architecture",
        "api",
        "gateway",
        "kubernetes",
        "aws",
        "cloud",
        "deployment",
    }
    if normalized_collection == "engineering" and any(term in normalized_query for term in engineering_keywords):
        return True

    collection_terms = {normalized_collection, "department", "documentation", "document", "context", "files", "information"}
    if any(term in query_terms for term in collection_terms):
        return True

    if normalized_collection in context_terms and any(
        term in query_terms for term in {"department", "documentation", "document", "context", "information", "files"}
    ):
        return True

    database_keywords = {"database", "databases", "db", "postgresql", "mongodb", "redis", "sql", "nosql", "storage"}
    if any(term in query_terms for term in {"database", "databases", "db"}) and any(
        term in context_terms for term in database_keywords
    ):
        return True

    if not use_llm or openai_client is None:
        return False

    scope_prompt = f"""
    You are a strict internal gatekeeper for a corporate database. 
    Your job is to determine if the user query is relevant to the documentation found in the '{collection}' department.

    Allowed topics for '{collection}': Anything related to {collection} procedures, files, documentation, or workflows.
    Disallowed topics: Coding unrelated to this department, casual chitchat, dangerous content, political opinions, or other departments.

    Respond with exactly one word: 'YES' if it is within scope, or 'NO' if it is out-of-scope.
    
    User Query: "{query}"
    Output:"""
    
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": scope_prompt}],
        temperature=0.0,
    )
    
    decision = response.choices[0].message.content.strip().upper()
    return "YES" in decision


# =====================================================================
# MAIN CHAT PIPELINE WITH GUARDRAILS
# =====================================================================
def main():
    print("Available collections: engineering, finance, general, hr, marketing")
    collection_choice = input("Enter collection name: ").strip().lower()
    raw_user_query = input("Ask something: ")

    # 1. Trigger PII Guardrail
    user_query = sanitize_pii(raw_user_query)
    if "[REDACTED" in user_query:
        print(f"🔒 Guardrail Note: Sensitive PII was masked: \"{user_query}\"")

    # 2. Trigger Out-Of-Scope Guardrail
    if not is_query_in_scope(user_query, collection_choice):
        print(f"🛑 Guardrail Blocked: Your question is out of scope for the '{collection_choice}' department.")
        return

    if collection_choice == "hr" and is_employee_count_question(user_query):
        from service.rag_service import get_employee_count_answer

        print(f"\n🤖: {get_employee_count_answer(user_query)}")
        return

    if embedding_model is None or QdrantVectorStore is None:
        print("⚠️ Vector search dependencies are not available in this environment.")
        return

    try:
        # 3. Dynamic Vector Search (Safe to execute now!)
        vector_db = QdrantVectorStore.from_existing_collection(
            url="http://localhost:6333",
            collection_name=collection_choice,
            embedding=embedding_model,
        )
        search_results = vector_db.similarity_search(query=user_query, k=3)
    except Exception as e:
        print(f"❌ Error connecting to collection '{collection_choice}': {e}")
        return

    # Format Context
    context_list = [f"File Location: {res.metadata.get('source')}\nContent:\n{res.page_content}" for res in search_results]
    context = "\n\n---\n\n".join(context_list)

    system_prompt = f"""
    You are a helpful AI Assistant who answers user queries based on the available context.
    You should only answer the user based strictly on the following context.

    Context:
    {context}
    """

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query},
        ],
    )

    print(f"\n🤖: {response.choices[0].message.content}")


if __name__ == "__main__":
    main()