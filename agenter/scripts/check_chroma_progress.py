"""Безопасная проверка прогресса ChromaDB индексации — НЕ трогает работающий процесс."""
import chromadb
from pathlib import Path

chroma_path = Path(r"D:\CURSORIC\agenter\agenter\data\platform_docs_chroma")
client = chromadb.PersistentClient(path=str(chroma_path))
try:
    col = client.get_collection("platform_docs")
    count = col.count()
    print(f"ChromaDB: {count:,} / 25,509  ({100*count/25509:.1f}%)")
except Exception as e:
    print(f"Collection не существует ещё: {e}")
