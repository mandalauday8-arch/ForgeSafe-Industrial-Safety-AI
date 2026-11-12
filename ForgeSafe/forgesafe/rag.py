from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from forgesafe.schemas import KnowledgeChunk


class KnowledgeBase:
    """RAG index and retrieval engine for industrial SOPs and safety procedures."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.chunks: List[KnowledgeChunk] = []
        self._load()

    def _load(self) -> None:
        self.chunks.clear()
        if not self.root.exists() or not self.root.is_dir():
            return

        for path in sorted(self.root.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            # Split sections by markdown top headers
            raw_sections = re.split(r"(?m)^(?=# )", content)
            for section in raw_sections:
                lines = [line.strip() for line in section.splitlines() if line.strip()]
                if not lines:
                    continue
                title = lines[0].lstrip("# ").strip()
                text = " ".join(lines[1:]) if len(lines) > 1 else lines[0]
                if not text:
                    continue

                tags = tuple(sorted(set(re.findall(r"[a-z][a-z-]{2,}", f"{title} {text}".lower()))))
                
                standard = ""
                std_match = re.search(r"(OSHA [^,\n]+|ISO [^,\n]+|NFPA [^,\n]+|ASHRAE [^,\n]+|ANSI [^,\n]+)", text)
                if std_match:
                    standard = std_match.group(1).strip()

                self.chunks.append(
                    KnowledgeChunk(
                        source=path.name,
                        title=title,
                        text=text,
                        tags=tags,
                        standard=standard,
                        sop_id=path.stem.upper(),
                    )
                )

    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Search the knowledge base by token overlap and exact title matching."""
        query_lower = query.lower()
        terms = set(re.findall(r"[a-z][a-z-]{2,}", query_lower))

        ranked: List[Tuple[int, KnowledgeChunk]] = []
        for chunk in self.chunks:
            words = set(chunk.tags)
            score = len(terms & words)

            title_lower = chunk.title.lower()
            title_words = set(re.findall(r"[a-z][a-z-]{2,}", title_lower))

            # Highest boost for title phrases occurring directly in query
            if title_lower in query_lower:
                score += 50
            elif title_words and title_words.issubset(terms):
                score += 30
            else:
                score += len(terms & title_words) * 3

            if score > 0:
                ranked.append((score, chunk))

        ranked.sort(key=lambda item: (-item[0], item[1].source, item[1].title))

        results = []
        for score, chunk in ranked[:limit]:
            results.append({
                "source": chunk.source,
                "title": chunk.title,
                "text": chunk.text,
                "score": score,
                "standard": chunk.standard,
                "sop_id": chunk.sop_id,
            })
        return results

    def get_all_chunks(self) -> List[Dict[str, Any]]:
        """Return all indexed chunks for UI browser."""
        return [chunk.to_dict() for chunk in self.chunks]
