"""
General RAG approach: Generic embedding-based retrieval + vanilla LLM.

No domain knowledge, no schema guidance. Uses text-embedding-3-small for
retrieval and GPT-4o for generation without specialized prompts.
"""
import json
import numpy as np
from pathlib import Path
from openai import OpenAI

benchmark_root = Path(__file__).parent.parent


def load_rag_corpus(corpus_dir=None):
    """Load pre-built RAG corpus (embeddings + metadata)."""
    if corpus_dir is None:
        corpus_dir = benchmark_root / "data" / "rag_corpus"

    embeddings_file = corpus_dir / "embeddings.npy"
    metadata_file = corpus_dir / "metadata.json"

    if not embeddings_file.exists() or not metadata_file.exists():
        print(f"Warning: RAG corpus not found at {corpus_dir}. Have you run setup.py?")
        return None

    embeddings = np.load(embeddings_file)
    with open(metadata_file) as f:
        metadata = json.load(f)

    return {"embeddings": embeddings, "metadata": metadata}


def retrieve_top_k(question, embeddings, metadata, k=5):
    """Retrieve top-K chunks by cosine similarity with the question."""
    client = OpenAI()

    # Embed the question
    q_response = client.embeddings.create(
        model="text-embedding-3-small",
        input=question
    )
    q_embedding = np.array(q_response.data[0].embedding, dtype=np.float32)

    # Cosine similarity
    if embeddings.size == 0:
        return []

    # Normalize embeddings for cosine similarity
    embeddings_norm = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-8)
    q_embedding_norm = q_embedding / (np.linalg.norm(q_embedding) + 1e-8)

    similarities = embeddings_norm @ q_embedding_norm
    top_indices = np.argsort(similarities)[::-1][:k]

    results = []
    for idx in top_indices:
        if idx < len(metadata):
            results.append({
                "chunk_id": idx,
                "similarity": float(similarities[idx]),
                "metadata": metadata[idx],
            })

    return results


def answer_question_rag(question, rag_corpus):
    """Answer a question using generic RAG (no domain knowledge)."""
    client = OpenAI()

    if not rag_corpus:
        return "No RAG corpus available"

    embeddings = rag_corpus["embeddings"]
    metadata = rag_corpus["metadata"]

    # Retrieve top-5 chunks
    retrieved = retrieve_top_k(question, embeddings, metadata, k=5)

    if not retrieved:
        return "No relevant documents found"

    # Build context from retrieved chunks
    context = "\n\n".join([
        f"[Document: {chunk['metadata'].get('report', 'unknown')}]\n{chunk['metadata'].get('text_preview', '')}"
        for chunk in retrieved
    ])

    # Generic Q&A prompt (no domain knowledge)
    system_prompt = """You are a helpful assistant. Answer the question using only the provided context.
If the context does not contain enough information to answer, say so clearly."""

    user_prompt = f"""Context:
{context}

Question: {question}

Please answer based solely on the provided context."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0,
            max_tokens=500
        )
        answer = response.choices[0].message.content
        return answer
    except Exception as e:
        return f"Error: {e}"
