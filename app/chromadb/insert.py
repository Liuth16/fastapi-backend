from .setup import turns_collection


async def insert_turn(campaign_id: str, turn_id: str, user_input: str, narrative: str):
    """
    Insert a single turn into ChromaDB.
    """
    text = f"Player action: {user_input}\nNarrator response: {narrative}"

    turns_collection.add(
        documents=[text],
        ids=[str(turn_id)],
        metadatas=[{
            "campaign_id": campaign_id,
            "user_input": user_input,
            "narrative": narrative
        }]
    )
