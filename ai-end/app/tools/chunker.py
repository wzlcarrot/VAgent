import re
from typing import List

CHUNK_SIZE = 512
CHUNK_OVERLAP = 128


def chunk_document(text: str, chunk_size: int = CHUNK_SIZE,
                   chunk_overlap: int = CHUNK_OVERLAP) -> List[str]:
    if not text:
        return []

    segments = _semantic_segmentation(text)
    chunks = _length_split(segments, chunk_size, chunk_overlap)
    return chunks


def _semantic_segmentation(text: str) -> List[str]:
    text = re.sub(r'\n{3,}', '\n\n', text)

    patterns = [
        r'(?=\n#{1,6}\s)',       # Markdown headers
        r'(?=\n\d+[\.、])',      # Numbered lists
        r'(?=\n[-*]\s)',          # Bullet lists
        r'(?=\n)',                # Double newlines -> paragraph breaks
    ]

    segments = [text]
    for pattern in patterns[:-1]:
        new_segments = []
        for seg in segments:
            parts = re.split(pattern, seg, maxsplit=0)
            new_segments.extend([p.strip() for p in parts if p.strip()])
        segments = new_segments if new_segments else segments

    final_segments = []
    for seg in segments:
        paragraphs = re.split(patterns[-1], seg)
        for p in paragraphs:
            stripped = p.strip()
            if stripped:
                final_segments.append(stripped)

    return final_segments


def _length_split(segments: List[str], chunk_size: int,
                  chunk_overlap: int) -> List[str]:
    chunks = []
    current_chunk = []
    current_tokens = 0

    for seg in segments:
        seg_tokens = _count_tokens(seg)

        if seg_tokens > chunk_size:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_tokens = 0
            sub_chunks = _split_large_segment(seg, chunk_size, chunk_overlap)
            chunks.extend(sub_chunks)
            continue

        if current_tokens + seg_tokens > chunk_size and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            overlap_texts = _get_overlap_segments(current_chunk, chunk_overlap)
            current_chunk = overlap_texts
            current_tokens = sum(_count_tokens(t) for t in overlap_texts)

        current_chunk.append(seg)
        current_tokens += seg_tokens

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


def _count_tokens(text: str) -> int:
    return len(text) // 2


def _get_overlap_segments(segments: List[str], overlap_tokens: int) -> List[str]:
    overlap = []
    tokens = 0
    for seg in reversed(segments):
        seg_tokens = _count_tokens(seg)
        if tokens + seg_tokens > overlap_tokens and overlap:
            break
        overlap.insert(0, seg)
        tokens += seg_tokens
    return overlap


def _split_large_segment(text: str, chunk_size: int, overlap: int) -> List[str]:
    sentences = re.split(r'(?<=[。！？.!?])', text)
    chunks = []
    current = ""
    current_tokens = 0

    for sent in sentences:
        if not sent.strip():
            continue
        sent_tokens = _count_tokens(sent)

        if current_tokens + sent_tokens > chunk_size:
            if current:
                chunks.append(current.strip())
                overlap_text = _get_char_overlap(current, overlap)
                current = overlap_text
                current_tokens = _count_tokens(overlap_text)

        current += sent
        current_tokens += sent_tokens

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _get_char_overlap(text: str, overlap_tokens: int) -> str:
    chars_needed = overlap_tokens * 2
    if len(text) > chars_needed:
        return text[-chars_needed:]
    return text
