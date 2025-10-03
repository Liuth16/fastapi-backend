import chromadb
from chromadb.utils import embedding_functions
from app.config import settings


client = chromadb.PersistentClient(path="vectordb")

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

google_embedding_function = embedding_functions.GoogleGenerativeAiEmbeddingFunction(
    api_key=settings.gemini_api_key,)

turns_collection = client.get_or_create_collection(
    name="turns",
    embedding_function=embedding_fn
)
