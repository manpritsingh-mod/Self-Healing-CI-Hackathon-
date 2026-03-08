"""
Vector DB Service — ChromaDB for similarity search + incident memory.
Single persistence layer: stores past fixes AND incident metadata.

Used by:
  - Orchestrator: search for similar past errors before calling LLM
  - Notify Agent: store incident metadata after resolution
  - Config Routes: query incident history via /api/incidents
"""

import chromadb
import logging
import json
from typing import List, Optional
from datetime import datetime
from config import CHROMA_PERSIST_DIR, CHROMA_COLLECTION, VECTOR_MATCH_HIGH, VECTOR_MATCH_PARTIAL

logger = logging.getLogger(__name__)


class VectorDBService:
    """ChromaDB wrapper for fix similarity search and incident memory."""

    def __init__(self):
        self._client = None
        self._collection = None

    def initialize(self):
        """Initialize ChromaDB client and collection. Call once at startup."""
        logger.info(f"[VECTOR] Initializing ChromaDB at {CHROMA_PERSIST_DIR}")

        self._client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self._collection = self._client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"description": "Healing incidents and past fixes"},
        )

        count = self._collection.count()
        logger.info(f"[VECTOR] Collection '{CHROMA_COLLECTION}' ready. {count} documents stored.")

    def _ensure_initialized(self):
        """Lazy initialization guard."""
        if self._collection is None:
            self.initialize()

    async def search(self, error_lines: List[str], top_k: int = 3) -> List[dict]:
        """
        Search for similar past errors.

        Returns list of matches with similarity scores:
          [{"id": str, "similarity": float, "fix": str, "metadata": dict}, ...]
        """
        self._ensure_initialized()

        if not error_lines:
            return []

        query_text = "\n".join(error_lines[:10])  # Cap query size

        try:
            results = self._collection.query(
                query_texts=[query_text],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )

            matches = []
            if results and results["ids"] and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    # ChromaDB returns L2 distance; convert to similarity (0-1)
                    distance = results["distances"][0][i] if results["distances"] else 1.0
                    similarity = max(0, 1 - (distance / 2))  # Normalize

                    metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                    document = results["documents"][0][i] if results["documents"] else ""

                    matches.append({
                        "id": doc_id,
                        "similarity": round(similarity, 3),
                        "fix": metadata.get("fix_description", document),
                        "fix_code": metadata.get("fix_code", ""),
                        "error_class": metadata.get("error_class", ""),
                        "root_cause": metadata.get("root_cause", ""),
                        "metadata": metadata,
                    })

            logger.info(
                f"[VECTOR] Search returned {len(matches)} matches. "
                f"Top similarity: {matches[0]['similarity'] if matches else 'N/A'}"
            )

            return matches

        except Exception as e:
            logger.error(f"[VECTOR] Search failed: {e}")
            return []

    async def store_incident(self, incident_id: str, error_text: str, metadata: dict):
        """
        Store a resolved incident for future similarity matching.
        The error_text becomes the embedding; metadata stores the fix details.
        """
        self._ensure_initialized()

        try:
            # Ensure all metadata values are strings (ChromaDB requirement)
            clean_metadata = {}
            for key, value in metadata.items():
                if isinstance(value, (list, dict)):
                    clean_metadata[key] = json.dumps(value)
                elif value is None:
                    clean_metadata[key] = ""
                else:
                    clean_metadata[key] = str(value)

            self._collection.upsert(
                ids=[incident_id],
                documents=[error_text],
                metadatas=[clean_metadata],
            )

            logger.info(f"[VECTOR] Stored incident {incident_id} ({len(error_text)} chars)")

        except Exception as e:
            logger.error(f"[VECTOR] Failed to store incident {incident_id}: {e}")

    async def get_incidents(self, limit: int = 20) -> List[dict]:
        """Get recent incidents from metadata (for /api/incidents endpoint)."""
        self._ensure_initialized()

        try:
            results = self._collection.get(
                limit=limit,
                include=["metadatas"],
            )

            incidents = []
            if results and results["ids"]:
                for i, doc_id in enumerate(results["ids"]):
                    meta = results["metadatas"][i] if results["metadatas"] else {}
                    incidents.append({
                        "id": doc_id,
                        "job_name": meta.get("job_name", ""),
                        "build_number": meta.get("build_number", ""),
                        "error_class": meta.get("error_class", ""),
                        "resolution_mode": meta.get("resolution_mode", ""),
                        "confidence": meta.get("final_confidence", ""),
                        "timestamp": meta.get("timestamp", ""),
                    })

            return incidents

        except Exception as e:
            logger.error(f"[VECTOR] Failed to get incidents: {e}")
            return []

    async def get_incident_by_id(self, incident_id: str) -> Optional[dict]:
        """Get a single incident's full metadata."""
        self._ensure_initialized()

        try:
            results = self._collection.get(
                ids=[incident_id],
                include=["documents", "metadatas"],
            )

            if results and results["ids"]:
                return {
                    "id": results["ids"][0],
                    "error_text": results["documents"][0] if results["documents"] else "",
                    "metadata": results["metadatas"][0] if results["metadatas"] else {},
                }

            return None

        except Exception as e:
            logger.error(f"[VECTOR] Failed to get incident {incident_id}: {e}")
            return None

    def get_stats(self) -> dict:
        """Get collection statistics."""
        self._ensure_initialized()
        return {
            "total_documents": self._collection.count(),
            "collection_name": CHROMA_COLLECTION,
            "persist_dir": CHROMA_PERSIST_DIR,
        }


# Singleton instance
vector_db_service = VectorDBService()
