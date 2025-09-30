import chromadb

client = chromadb.PersistentClient(path="vectordb")
print(client.list_collections())

turns_collection = client.get_collection("turns")
print(turns_collection.count())  # number of records

docs = turns_collection.get()
print(docs.keys())  # usually: ids, documents, embeddings, metadatas
print(docs["ids"])
# print(docs["documents"][:5])   # preview first 5 docs
doc = turns_collection.get(ids=["68dbaec158c4eae98484d1c3"])
print(doc["documents"])
