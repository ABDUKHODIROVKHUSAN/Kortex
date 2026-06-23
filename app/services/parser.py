def parse_pdf(file_path: str) -> list[dict]:
    import fitz

    pages: list[dict] = []
    with fitz.open(file_path) as doc:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text("text").strip()
            if text:
                pages.append({"text": text, "page": page_num + 1})
    return pages


def parse_docx(file_path: str) -> list[dict]:
    from docx import Document as DocxDocument

    doc = DocxDocument(file_path)
    paragraphs: list[dict] = []
    for idx, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if text:
            paragraphs.append({"text": text, "paragraph_index": idx + 1})
    return paragraphs


def chunk_text(
    pages: list[dict], doc_id: str, chunk_size: int = 500, overlap: int = 50
) -> list[dict]:
    chunks: list[dict] = []
    chunk_index = 0

    for item in pages:
        text = item["text"]
        page = item.get("page")
        paragraph_index = item.get("paragraph_index")
        start = 0

        while start < len(text):
            end = start + chunk_size
            chunk_text_slice = text[start:end].strip()
            if chunk_text_slice:
                metadata: dict = {"chunk_index": chunk_index, "doc_id": doc_id}
                if page is not None:
                    metadata["page"] = page
                if paragraph_index is not None:
                    metadata["paragraph_index"] = paragraph_index

                chunks.append({"text": chunk_text_slice, "metadata": metadata})
                chunk_index += 1

            if end >= len(text):
                break
            start = end - overlap

    return chunks
