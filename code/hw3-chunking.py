import os
import json
import numpy as np
import pandas as pd
import requests
from typing import List
from llama_index.core import Document, VectorStoreIndex, Settings
from llama_index.core.node_parser import(
    TokenTextSplitter,
    SentenceWindowNodeParser,
    SemanticSplitterNodeParser
)

from llama_index.embeddings.huggingface import HuggingFaceEmbedding

#Getting FDA food recall data
def load_openfda_documents(limit: int = 50) -> List[Document]:
    url = f"https://api.fda.gov/food/enforcement.json?limit={limit}"
    print(f"Fetching data from openFDA API {limit}")
    
    response = requests.get(url)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to fetch the data")
        
    data = response.json()
    results = data.get("results", [])
    
    documents = []
    for record in results:
        #creating text content chunking
        text = (
            f"Recalling Firm: {record.get('recalling_firm', 'N/A')}\n"
            f"Product Description: {record.get('product_description', 'N/A')}\n"
            f"Reason for Recall: {record.get('reason_for_recall', 'N/A')}\n"
            f"Classification: {record.get('classification', 'N/A')}\n"
            f"Status: {record.get('status', 'N/A')}"
        )
        
        #store metadata for traceability
        metadata = {
            "recall_number": record.get("recall_number", ""),
            "recalling_firm": record.get("recalling_firm", ""),
            "classification": record.get("classification", "")
        }
        
        documents.append(Document(text=text, extra_info=metadata))
        
    print(f"Loaded {len(documents)} documents.")
    return documents


# Load dataset and initialize model
documents = load_openfda_documents(limit=50)


embed_model = HuggingFaceEmbedding(model_name = "sentence-transformers/all-MiniLM-L6-v2")

Settings.embed_model = embed_model

def cosine_similarity(v1:list, v2:list) -> float:
    a = np.array(v1)
    b = np.array(v2)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def get_nodes(technique: str, docs: List[Document]):
    if technique == "Token":
        splitter = TokenTextSplitter(chunk_size=50, chunk_overlap=10)
        return splitter.get_nodes_from_documents(docs)
    
    elif technique == "Semantic":
        splitter = SemanticSplitterNodeParser(
            buffer_size=1, 
            breakpoint_percentile_threshold=95, 
            embed_model=embed_model
        )
        return splitter.get_nodes_from_documents(docs)
    
    elif technique == "Sentence-window":
        splitter = SentenceWindowNodeParser.from_defaults(
            window_size=3,
            window_metadata_key="window",
            original_text_metadata_key="original_sentence"
        )
        return splitter.get_nodes_from_documents(docs)
    
    else:
        raise ValueError(f"Unknown technique")


def run_retrieval_pipeline(query: str, technique: str, docs: List[Document], k: int = 3):
    
    #chunking and vector store index
    nodes = get_nodes(technique, docs)
    index = VectorStoreIndex(nodes)
    retriever = index.as_retriever(similarity_top_k=k)
    
    #query embedding
    query_embedding = embed_model.get_query_embedding(query)
    print(f"Query Embedding Dimension: {len(query_embedding)}")
    print(f"First 8 Query Embedding Values: {[round(x, 4) for x in query_embedding[:8]]}\n")
    
    #retrieve the nodes
    retrieved_nodes = retriever.retrieve(query)
    
    doc_embeddings = []
    results = []
    
    for rank, node_with_score in enumerate(retrieved_nodes, start=1):
        node = node_with_score.node
        store_score = node_with_score.score if node_with_score.score is not None else 0.0
        
        doc_emb = embed_model.get_text_embedding(node.get_content())
        doc_embeddings.append(doc_emb)
        
        cos_sim = cosine_similarity(query_embedding, doc_emb)
        preview = node.get_content().replace("\n", " ")[:160]
        
        results.append({
            "rank": rank,
            "store_score": round(store_score, 4),
            "cosine_sim": round(cos_sim, 4),
            "chunk_len": len(node.get_content()),
            "preview": preview
        })
    
    #output query vector and stacked document vectors
    query_v = np.array(query_embedding)
    stacked_document = np.array(doc_embeddings)
    print(f"Query Vector Shape: {query_v.shape}")
    print(f"Stacked Doc Vectors Shape: {stacked_document.shape}\n")
    
    df = pd.DataFrame(results)
    print(df.to_string(index=False))
    
    #save the data to json files
    os.makedirs("raw", exist_ok=True)
    filename = f"raw/retrieval_{technique.lower().replace('-', '_')}.json"
    
    raw_payload = {
        "technique": technique,
        "query": query,
        "query_vector_shape": list(query_v.shape),
        "doc_vectors_shape": list(stacked_document.shape),
        "results": results
    }
    
    with open(filename, "w") as f:
        json.dump(raw_payload, f, indent=2)
        
    print(f"\nSaved raw data to: {filename}")
    return df



if __name__ == "__main__":
    query_text = "What food recalls are related to contamination or undeclared allergens?"
    techniques = ["Token", "Semantic", "Sentence-window"]

    for tech in techniques:
        run_retrieval_pipeline(query=query_text, technique=tech, docs=documents, k=3)