import csv
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
MANIFEST_DB = APP_DIR / "index_manifest.db"
QDRANT_URL = "http://localhost:6333"
EMBEDDING_MODEL = "text-embedding-3-small"

embedding_model = OpenAIEmbeddings(model=EMBEDDING_MODEL)
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=400,
)
qdrant_client = QdrantClient(url=QDRANT_URL)


def initialize_manifest() -> None:
    """Create local tables that remember indexed files and their Qdrant point IDs."""
    with sqlite3.connect(MANIFEST_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS indexed_files (
                collection_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                point_ids TEXT NOT NULL,
                PRIMARY KEY (collection_name, file_path)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS indexed_collections (
                collection_name TEXT PRIMARY KEY
            )
            """
        )


def file_hash(file_path: Path) -> str:
    """Return a SHA-256 hash of the file's current bytes."""
    digest = hashlib.sha256()
    with file_path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_file_documents(file_path: Path) -> list[Document]:
    """Load one supported file and attach a consistent absolute source path."""
    source = str(file_path.resolve())

    if file_path.suffix.lower() == ".md":
        docs = TextLoader(file_path=str(file_path), encoding="utf-8").load()
        for doc in docs:
            doc.metadata["source"] = source
        return docs

    if file_path.suffix.lower() == ".csv":
        docs = []
        with file_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if not reader.fieldnames:
                raise ValueError(f"CSV file has no header row: {file_path}")

            for row_number, row in enumerate(reader, start=2):
                row_text = "\n".join(
                    f"{field}: {value or ''}" for field, value in row.items() if field
                )
                docs.append(
                    Document(
                        page_content=row_text,
                        metadata={"source": source, "row": row_number},
                    )
                )
        return docs

    return []


def get_file_record(collection_name: str, file_path: str):
    with sqlite3.connect(MANIFEST_DB) as conn:
        return conn.execute(
            "SELECT content_hash, point_ids FROM indexed_files "
            "WHERE collection_name = ? AND file_path = ?",
            (collection_name, file_path),
        ).fetchone()


def save_file_record(
    collection_name: str, file_path: str, content_hash: str, point_ids: list[str]
) -> None:
    with sqlite3.connect(MANIFEST_DB) as conn:
        conn.execute(
            """
            INSERT INTO indexed_files (collection_name, file_path, content_hash, point_ids)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(collection_name, file_path) DO UPDATE SET
                content_hash = excluded.content_hash,
                point_ids = excluded.point_ids
            """,
            (collection_name, file_path, content_hash, json.dumps(point_ids)),
        )


def get_tracked_files(collection_name: str) -> dict[str, tuple[str, list[str]]]:
    with sqlite3.connect(MANIFEST_DB) as conn:
        rows = conn.execute(
            "SELECT file_path, content_hash, point_ids FROM indexed_files WHERE collection_name = ?",
            (collection_name,),
        ).fetchall()
    return {path: (content_hash, json.loads(point_ids)) for path, content_hash, point_ids in rows}


def collection_was_initialized(collection_name: str) -> bool:
    with sqlite3.connect(MANIFEST_DB) as conn:
        return conn.execute(
            "SELECT 1 FROM indexed_collections WHERE collection_name = ?",
            (collection_name,),
        ).fetchone() is not None


def mark_collection_initialized(collection_name: str) -> None:
    with sqlite3.connect(MANIFEST_DB) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO indexed_collections (collection_name) VALUES (?)",
            (collection_name,),
        )


def delete_points(vector_store: QdrantVectorStore, point_ids: list[str]) -> None:
    if point_ids:
        vector_store.delete(ids=point_ids)


def index_collection(collection_dir: Path) -> None:
    collection_name = collection_dir.name
    source_files = sorted(
        file_path
        for pattern in ("*.md", "*.csv")
        for file_path in collection_dir.glob(pattern)
        if file_path.is_file()
    )

    if not source_files:
        print(f"⚠️ No Markdown or CSV files found in '{collection_name}'. Skipping.")
        return

    print(f"\n📂 Department: {collection_name}")
    current_paths = {str(path.resolve()) for path in source_files}
    tracked_files = get_tracked_files(collection_name)

    # Bootstrap tracking from the collection that has already been indexed.
    # This avoids embedding all documents again on the first incremental run.
    if not collection_was_initialized(collection_name):
        try:
            existing_ids_by_source: dict[str, list[str]] = {}
            next_offset = None
            while True:
                points, next_offset = qdrant_client.scroll(
                    collection_name=collection_name,
                    limit=256,
                    offset=next_offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    metadata = payload.get("metadata") or {}
                    raw_source = metadata.get("source")
                    if raw_source:
                        normalized_source = str(Path(raw_source).resolve())
                        existing_ids_by_source.setdefault(normalized_source, []).append(str(point.id))
                if next_offset is None:
                    break

            missing_sources = [source for source in current_paths if source not in existing_ids_by_source]
            if missing_sources:
                raise ValueError(
                    "Could not match existing Qdrant points to every source file: "
                    + ", ".join(Path(source).name for source in missing_sources)
                )

            # Remove orphaned points for source files that were deleted before tracking began.
            for old_source, old_ids in existing_ids_by_source.items():
                if old_source not in current_paths and old_ids:
                    qdrant_client.delete(collection_name=collection_name, points=old_ids)
                    print(f"  🗑️ Removed points for deleted source: {Path(old_source).name}")

            for file_path in source_files:
                source = str(file_path.resolve())
                save_file_record(
                    collection_name,
                    source,
                    file_hash(file_path),
                    existing_ids_by_source[source],
                )
            mark_collection_initialized(collection_name)
            print(
                "  🧭 Tracking initialized from existing Qdrant points; "
                "no embeddings were generated during this setup."
            )
            tracked_files = get_tracked_files(collection_name)
        except Exception as exc:
            raise RuntimeError(
                f"Could not initialize incremental tracking for '{collection_name}' "
                "without re-indexing. Check that the collection exists and its payloads "
                "contain metadata.source. No collection was intentionally recreated. "
                f"Details: {exc}"
            ) from exc

    vector_store = QdrantVectorStore.from_existing_collection(
        url=QDRANT_URL,
        collection_name=collection_name,
        embedding=embedding_model,
    )

    # Add new files and replace only files whose content hash changed.
    for file_path in source_files:
        source = str(file_path.resolve())
        current_hash = file_hash(file_path)
        previous_record = get_file_record(collection_name, source)

        if previous_record and previous_record[0] == current_hash:
            print(f"  ⏭️ Unchanged: {file_path.name} — skipping embeddings.")
            continue

        if previous_record:
            old_ids = json.loads(previous_record[1])
            delete_points(vector_store, old_ids)
            print(f"  ♻️ Modified: {file_path.name} — replaced {len(old_ids)} old chunks.")
        else:
            print(f"  🆕 New file: {file_path.name}.")

        docs = load_file_documents(file_path)
        chunks = text_splitter.split_documents(docs)
        new_ids = [str(uuid.uuid4()) for _ in chunks]

        if chunks:
            vector_store.add_documents(documents=chunks, ids=new_ids)
        save_file_record(collection_name, source, current_hash, new_ids)
        print(f"     Indexed {len(chunks)} chunks.")

    # Remove Qdrant points for files that were deleted from the data folder.
    for old_source, (_, old_ids) in tracked_files.items():
        if old_source not in current_paths:
            delete_points(vector_store, old_ids)
            with sqlite3.connect(MANIFEST_DB) as conn:
                conn.execute(
                    "DELETE FROM indexed_files WHERE collection_name = ? AND file_path = ?",
                    (collection_name, old_source),
                )
            print(f"  🗑️ Deleted source removed: {Path(old_source).name}")

    print(f"✅ Incremental indexing complete for '{collection_name}'.")


def main() -> None:
    initialize_manifest()

    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Data directory not found: {DATA_DIR}")

    for collection_dir in sorted(DATA_DIR.iterdir()):
        if collection_dir.is_dir():
            index_collection(collection_dir)

    print("\n🎉 Incremental indexing run completed.")


if __name__ == "__main__":
    main()
