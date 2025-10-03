from .setup import turns_collection


async def query_turns(query_text: str, campaign_id: str, k: int = 3):
    """
    Query ChromaDB for turns most similar to the query_text.
    Restricted to the same campaign_id.
    """
    results = turns_collection.query(
        query_texts=[query_text],
        n_results=k,
        where={"campaign_id": campaign_id}
    )

    contexts = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        contexts.append(
            f"Player: {meta['user_input']} | Narrator: {meta['narrative']}")

    return contexts
