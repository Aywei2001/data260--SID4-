from langchain_community.document_loaders import DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.chat_models import ChatOllama

loader = DirectoryLoader("./docs", glob = "*.txt")

docs = loader.load()

text_splitter = RecursiveCharacterTextSplitter(chunk_size = 500, chunk_overlap = 50)
chunks = text_splitter.split_documents(docs)

for i, chunk in enumerate(chunks):
    chunk.metadata["chunk_id"] = f"chunk {i}"
    chunk.metadata["source"] = chunk.metadata.get("source", "unknown")

embeddings = OllamaEmbeddings(model = "nomic-embed-text")
vectorstore = Chroma.from_documents(chunks, embeddings)

llm = ChatOllama(model = "llama3", temperature = 0)

def ollama_experiment(query, config_type = "A", k = 3):

    retrieved_docs = vectorstore.similarity_search_with_score(query, k = k)

    print(f"\n--- Query: '{query}' | Config: {config_type} | k={k} ---")

    for doc, score in retrieved_docs:
        print(f"Source: {doc.metadata.get('source')} | ID: {doc.metadata.get('chunk_id')} | Score: {score:.2f}")

    if config_type == "A":
        return llm.invoke(query).content

    elif config_type == "B":
        context = "\n".join([doc.page_content for doc , _ in retrieved_docs])
        return llm.invoke(f"Context: {context} \n Question: {query}").content

    elif config_type == "C":
        unique_docs = {doc.page_content: doc for doc , _ in retrieved_docs}
        format_context = ""

        for i, (content, doc) in enumerate(unique_docs.items(), start = 1):
            source_name = doc.metadata.get('source', 'unknown')
            format_context += f"source {i}: {source_name}, {content}"

        prompt = ""

        return llm.invoke(prompt).content



if __name__ == "__main__":

    test_questions = []