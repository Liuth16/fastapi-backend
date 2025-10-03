from .setup import turns_collection, reranker


async def query_turns(query_text: str, campaign_id: str, fetch_k: int = 20, return_k: int = 5):
    """
    Query ChromaDB for turns most similar to the query_text.
    Then rerank the top fetch_k using a cross-encoder on CPU and return return_k.
    """
    results = turns_collection.query(
        query_texts=[query_text],
        n_results=fetch_k,
        where={"campaign_id": campaign_id}
    )

    docs = results["documents"][0]
    metas = results["metadatas"][0]

    pairs = [
        (query_text, f"Player: {m['user_input']} | Narrative: {m['narrative']}") for m in metas]

    scores = reranker.predict(pairs)

    reranked = sorted(
        zip(docs, metas, scores),
        key=lambda x: x[2],
        reverse=True
    )

    contexts = [
        f"Player: {meta['user_input']} | Narrative: {meta['narrative']}"
        for _, meta, _ in reranked[:return_k]
    ]

    return contexts
