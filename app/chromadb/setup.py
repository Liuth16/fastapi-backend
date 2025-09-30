import chromadb
from chromadb.utils import embedding_functions
from app.config import settings  # centralized config

# Initialize Chroma client (persistent, so data is saved locally)
client = chromadb.PersistentClient(path="vectordb")

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

google_embedding_function = embedding_functions.GoogleGenerativeAiEmbeddingFunction(
    api_key=settings.gemini_api_key,)

# Create or load a collection
turns_collection = client.get_or_create_collection(
    name="turns",
    embedding_function=embedding_fn
)
