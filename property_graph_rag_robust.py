# Complete Code for Property Graph RAG with Ollama Llama 3.1 8B and all-minilm:l6-v2
# ENHANCED VERSION WITH ROBUST TIMEOUT AND RETRY LOGIC
# Processes folder of PDFs, builds property graph with communities, evaluates using specified metrics

import os
import json
import pandas as pd
import logging
import matplotlib.pyplot as plt
from tqdm import tqdm
from rouge_score import rouge_scorer
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
from typing import List, Dict, Any, Tuple, Optional
import nltk
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import re
import asyncio
import nest_asyncio
from IPython.display import Markdown, display
from llama_index.core import Settings, PropertyGraphIndex, Document
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.async_utils import run_jobs
from llama_index.core.indices.property_graph.utils import default_parse_triplets_fn
from llama_index.core.graph_stores.types import EntityNode, KG_NODES_KEY, KG_RELATIONS_KEY, Relation
from llama_index.core.llms import LLM
from llama_index.core.prompts import PromptTemplate
from llama_index.core.schema import TransformComponent, BaseNode
from llama_index.core.llms import ChatMessage
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore
import pdfplumber
import networkx as nx
from graspologic.partition import hierarchical_leiden
from collections import defaultdict
from pydantic import Field, ConfigDict
import signal
import time

nest_asyncio.apply()

# NLTK downloads
try:
    nltk.download('punkt', quiet=True)
    nltk.download('punkt_tab', quiet=True)
except:
    pass

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Config
config = {
    "pdf_dir": "/home/871323/RAG/test/pdf",
    "neo4j_uri": "neo4j+s://cacc75f2.databases.neo4j.io",
    "neo4j_username": "neo4j",
    "neo4j_password": "oNVetJ9I2FiRGJAMWqh2ZTXySOel9_IM_YyUagHuaKk",
    "dataset_path": "/home/871323/RAG/one_file_dataset.jsonl",
    "ollama_base_url": "http://localhost:11434",
    "checkpoint_file": "/home/871323/RAG/checkpoint.json",  # NEW: Save progress
    "request_timeout": 300.0,  # 5 minutes per request
    "max_retries": 2,  # Retry stuck requests twice before skipping
    "skip_after_failures": 3  # Skip node after 3 total failures
}

# NEW: Checkpoint system to save progress
class CheckpointManager:
    def __init__(self, checkpoint_file):
        self.checkpoint_file = checkpoint_file
        self.data = self.load()
    
    def load(self):
        if os.path.exists(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, 'r') as f:
                    return json.load(f)
            except:
                return {"processed_nodes": [], "failed_nodes": [], "last_index": 0}
        return {"processed_nodes": [], "failed_nodes": [], "last_index": 0}
    
    def save(self):
        with open(self.checkpoint_file, 'w') as f:
            json.dump(self.data, f)
    
    def mark_processed(self, node_id, index):
        self.data["processed_nodes"].append(node_id)
        self.data["last_index"] = index
        self.save()
    
    def mark_failed(self, node_id):
        self.data["failed_nodes"].append(node_id)
        self.save()
    
    def is_processed(self, node_id):
        return node_id in self.data["processed_nodes"]
    
    def get_last_index(self):
        return self.data.get("last_index", 0)

checkpoint_manager = CheckpointManager(config["checkpoint_file"])

# NEW: Timeout handler using asyncio.wait_for
class TimeoutException(Exception):
    pass

async def call_with_timeout(coro, timeout, description="operation"):
    """Wrap async call with timeout and detailed logging"""
    try:
        logging.info(f"Starting {description} with {timeout}s timeout...")
        result = await asyncio.wait_for(coro, timeout=timeout)
        logging.info(f"Completed {description} successfully")
        return result
    except asyncio.TimeoutError:
        logging.error(f"TIMEOUT: {description} exceeded {timeout}s - SKIPPING")
        raise TimeoutException(f"Timeout after {timeout}s: {description}")
    except Exception as e:
        logging.error(f"Error in {description}: {e}")
        raise

# Initialize LLM and Embed Model with reduced timeout
llm = Ollama(
    model="llama3.1:8b-instruct-q4_K_M", 
    request_timeout=config["request_timeout"],  # 5 minutes instead of 27+ hours
    base_url=config["ollama_base_url"]
)
embed_model = OllamaEmbedding(
    model_name="all-minilm:l6-v2",
    base_url=config["ollama_base_url"],
    ollama_additional_kwargs={"mirostat": 0},
)
Settings.llm = llm
Settings.embed_model = embed_model

# --- Clear Neo4j Database ---
def clear_neo4j_database(uri: str, username: str, password: str):
    try:
        driver = GraphDatabase.driver(uri, auth=(username, password))
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        driver.close()
        logging.info("Neo4j database cleared successfully")
    except Exception as e:
        logging.error(f"Error clearing Neo4j database: {e}")

# Only clear if starting fresh (checkpoint doesn't exist or is empty)
if checkpoint_manager.get_last_index() == 0:
    clear_neo4j_database(config["neo4j_uri"], config["neo4j_username"], config["neo4j_password"])
    logging.info("Starting fresh - cleared Neo4j database")
else:
    logging.info(f"Resuming from checkpoint - last processed index: {checkpoint_manager.get_last_index()}")

# --- PDF Processing ---
documents = []
if not os.path.exists(config["pdf_dir"]):
    logging.error(f"PDF directory not found: {config['pdf_dir']}")
    exit(1)

pdf_files = [f for f in os.listdir(config["pdf_dir"]) if f.endswith('.pdf')]
logging.info(f"Found {len(pdf_files)} PDF files")

for filename in tqdm(pdf_files, desc="Processing PDFs"):
    pdf_path = os.path.join(config["pdf_dir"], filename)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text and text.strip():
                    documents.append(Document(text=text))
                    logging.debug(f"Sample text from {filename} (page {page_num}): {text[:100]}...")
                else:
                    logging.warning(f"No text extracted from {filename} (page {page_num})")
    except Exception as e:
        logging.error(f"Error processing {filename}: {e}")

if not documents:
    logging.error("No documents extracted.")
    exit(1)

logging.info(f"Extracted {len(documents)} document chunks")

# --- GraphRAGExtractor ---
KG_TRIPLET_EXTRACT_TMPL = """
-Goal-
Given a text document, identify all entities and their entity types from the text and all relationships among the identified entities.
Given the text, extract up to {max_knowledge_triplets} entity-relation triplets in a structured format.

-Steps-
1. Identify all entities in the text. For each identified entity, extract:
- entity_name: Name of the entity, capitalized (e.g., "Type 1 Diabetes")
- entity_type: Type of the entity (e.g., "Disease", "Treatment", "Symptom", "Organization")
- entity_description: A brief description of the entity's role or characteristics in the text
Format each entity as: ("entity"$$$$entity_name$$$$entity_type$$$$entity_description)

2. Identify all pairs of entities (source_entity, target_entity) that are explicitly related in the text.
For each pair, extract:
- source_entity: Name of the source entity (must match an entity_name from step 1)
- target_entity: Name of the target entity (must match an entity_name from step 1)
- relation: A verb or phrase describing the relationship (e.g., "causes", "is treated by", "is associated with")
- relationship_description: A brief explanation of the relationship
Format each relationship as: ("relationship"$$$$source_entity$$$$target_entity$$$$relation$$$$relationship_description)

3. Ensure all outputs are in the exact format specified, with no extra spaces or characters.
If no entities or relationships are identified, output an empty string.
Return the output as a newline-separated list of formatted entities and relationships.

-Example Output-
("entity"$$$$"Type 1 Diabetes"$$$$"Disease"$$$$"An autoimmune condition where the body attacks insulin-producing cells")
("entity"$$$$"Insulin"$$$$"Treatment"$$$$"A hormone used to manage blood sugar levels")
("relationship"$$$$"Type 1 Diabetes"$$$$"Insulin"$$$$"is treated by"$$$$"Insulin is used to manage Type 1 Diabetes by regulating blood sugar")

-Real Data-
######################
text: {text}
######################
output:
"""

entity_pattern = r'\("entity"\$\$\$\$"(.+?)"\$\$\$\$"(.+?)"\$\$\$\$"(.+?)"\)'
relationship_pattern = r'\("relationship"\$\$\$\$"(.+?)"\$\$\$\$"(.+?)"\$\$\$\$"(.+?)"\$\$\$\$"(.+?)"\)'

def parse_fn(response_str: str) -> Any:
    entities = re.findall(entity_pattern, response_str, re.DOTALL)
    relationships = re.findall(relationship_pattern, response_str, re.DOTALL)
    logging.debug(f"Parsed entities: {entities}")
    logging.debug(f"Parsed relationships: {relationships}")
    return entities, relationships

# NEW: Enhanced extractor with timeout and retry logic
class SimpleGraphExtractor:
    def __init__(self, llm, extract_prompt, parse_fn, max_paths_per_chunk=2, num_workers=4):
        self.llm = llm
        self.extract_prompt = PromptTemplate(extract_prompt) if isinstance(extract_prompt, str) else extract_prompt
        self.parse_fn = parse_fn
        self.max_paths_per_chunk = max_paths_per_chunk
        self.num_workers = num_workers
        self.failure_counts = defaultdict(int)

    async def _aextract(self, node: BaseNode) -> BaseNode:
        assert hasattr(node, "text")
        text = node.get_content(metadata_mode="llm")
        node_id = node.node_id
        
        # Check if already processed
        if checkpoint_manager.is_processed(node_id):
            logging.info(f"Skipping already processed node: {node_id}")
            # Load from checkpoint or return empty
            node.metadata[KG_NODES_KEY] = []
            node.metadata[KG_RELATIONS_KEY] = []
            return node
        
        # Check if failed too many times
        if self.failure_counts[node_id] >= config["skip_after_failures"]:
            logging.warning(f"Skipping node {node_id} after {config['skip_after_failures']} failures")
            checkpoint_manager.mark_failed(node_id)
            node.metadata[KG_NODES_KEY] = []
            node.metadata[KG_RELATIONS_KEY] = []
            return node
        
        # Try extraction with timeout
        for attempt in range(config["max_retries"] + 1):
            try:
                logging.info(f"Processing node {node_id} (attempt {attempt + 1}/{config['max_retries'] + 1})")
                
                # Wrap the LLM call with timeout
                llm_response = await call_with_timeout(
                    self.llm.apredict(
                        self.extract_prompt,
                        text=text,
                        max_knowledge_triplets=self.max_paths_per_chunk,
                    ),
                    timeout=config["request_timeout"],
                    description=f"LLM extraction for node {node_id[:8]}"
                )
                
                logging.debug(f"LLM response for node: {llm_response[:500]}...")
                entities, entities_relationship = self.parse_fn(str(llm_response))
                logging.info(f"Extracted {len(entities)} entities and {len(entities_relationship)} relationships")
                
                # Success! Break retry loop
                break
                
            except TimeoutException as e:
                self.failure_counts[node_id] += 1
                logging.error(f"Timeout on node {node_id} (attempt {attempt + 1}): {e}")
                
                if attempt < config["max_retries"]:
                    wait_time = 10 * (attempt + 1)
                    logging.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    logging.error(f"Max retries exceeded for node {node_id} - SKIPPING")
                    checkpoint_manager.mark_failed(node_id)
                    entities = []
                    entities_relationship = []
                    
            except Exception as e:
                self.failure_counts[node_id] += 1
                logging.error(f"Error extracting triplets from node {node_id}: {e}")
                
                if attempt < config["max_retries"]:
                    wait_time = 10 * (attempt + 1)
                    logging.info(f"Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    entities = []
                    entities_relationship = []

        existing_nodes = node.metadata.pop(KG_NODES_KEY, [])
        existing_relations = node.metadata.pop(KG_RELATIONS_KEY, [])
        entity_metadata = node.metadata.copy()

        for entity, entity_type, description in entities:
            entity_metadata["entity_description"] = description
            entity_node = EntityNode(
                name=entity, label=entity_type, properties=entity_metadata
            )
            existing_nodes.append(entity_node)

        relation_metadata = node.metadata.copy()
        for triple in entities_relationship:
            subj, obj, rel, description = triple
            relation_metadata["relationship_description"] = description if description else "No description provided"
            rel_node = Relation(
                label=rel,
                source_id=subj,
                target_id=obj,
                properties=relation_metadata,
            )
            existing_relations.append(rel_node)

        node.metadata[KG_NODES_KEY] = existing_nodes
        node.metadata[KG_RELATIONS_KEY] = existing_relations
        
        # Mark as processed in checkpoint
        checkpoint_manager.mark_processed(node_id, 0)
        
        return node

    async def acall(self, nodes: List[BaseNode], show_progress: bool = False, **kwargs: Any) -> List[BaseNode]:
        # Process nodes sequentially with detailed progress tracking
        results = []
        for i, node in enumerate(tqdm(nodes, desc="Extracting paths", disable=not show_progress)):
            logging.info(f"Processing node {i+1}/{len(nodes)}")
            try:
                result = await self._aextract(node)
                results.append(result)
                # Update checkpoint with current index
                checkpoint_manager.data["last_index"] = i
                checkpoint_manager.save()
            except Exception as e:
                logging.error(f"Failed to process node {i}: {e}")
                # Add empty node to maintain order
                node.metadata[KG_NODES_KEY] = []
                node.metadata[KG_RELATIONS_KEY] = []
                results.append(node)
        
        return results

    def __call__(self, nodes: List[BaseNode], show_progress: bool = False, **kwargs: Any) -> List[BaseNode]:
        return asyncio.run(self.acall(nodes, show_progress=show_progress, **kwargs))

# Create a wrapper that implements the TransformComponent interface
class GraphRAGExtractor(TransformComponent):
    def __init__(self, llm, extract_prompt, parse_fn, max_paths_per_chunk=2, num_workers=1):
        super().__init__()
        # Reduced workers to 1 for better control and debugging
        self._extractor = SimpleGraphExtractor(llm, extract_prompt, parse_fn, max_paths_per_chunk, num_workers)
    
    def __call__(self, nodes: List[BaseNode], show_progress: bool = False, **kwargs: Any) -> List[BaseNode]:
        return self._extractor(nodes, show_progress=show_progress, **kwargs)
    
    async def acall(self, nodes: List[BaseNode], show_progress: bool = False, **kwargs: Any) -> List[BaseNode]:
        return await self._extractor.acall(nodes, show_progress=show_progress, **kwargs)

kg_extractor = GraphRAGExtractor(
    llm=llm,
    extract_prompt=KG_TRIPLET_EXTRACT_TMPL,
    max_paths_per_chunk=2,
    parse_fn=parse_fn,
    num_workers=1  # Sequential processing for better control
)

# Node splitting
splitter = SentenceSplitter(chunk_size=2048, chunk_overlap=20)
nodes = splitter.get_nodes_from_documents(documents)
logging.info(f"Created {len(nodes)} nodes")

# --- GraphRAGStore ---
class GraphRAGStore(Neo4jPropertyGraphStore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.llm = llm
        self.entity_info = {}
        self.community_summary = {}
        self.max_cluster_size = 5

    def generate_community_summary(self, text: str) -> str:
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are provided with a set of relationships from a knowledge graph, each represented as "
                    "entity1->entity2->relation->relationship_description. Your task is to create a summary of these "
                    "relationships. The summary should include the names of the entities involved and a concise synthesis "
                    "of the relationship descriptions. The goal is to capture the most critical and relevant details that "
                    "highlight the nature and significance of each relationship. Ensure that the summary is coherent and "
                    "integrates the information in a way that emphasizes the key aspects of the relationships."
                ),
            ),
            ChatMessage(role="user", content=text),
        ]
        response = self.llm.chat(messages)
        clean_response = re.sub(r"^assistant:\s*", "", str(response)).strip()
        return clean_response

    def build_communities(self):
        nx_graph = self._create_nx_graph()
        triplets = self.get_triplets()
        logging.info(f"Retrieved {len(triplets)} triplets for community detection")
        if not triplets:
            logging.warning("No triplets found in the graph. Skipping community detection.")
            self.entity_info = {}
            self.community_summary = {}
            return
        try:
            community_hierarchical_clusters = hierarchical_leiden(
                nx_graph, max_cluster_size=self.max_cluster_size
            )
            self.entity_info, community_info = self._collect_community_info(
                nx_graph, community_hierarchical_clusters
            )
            self._summarize_communities(community_info)
        except Exception as e:
            logging.error(f"Error in community detection: {e}")
            self.entity_info = {}
            self.community_summary = {}

    def _create_nx_graph(self):
        nx_graph = nx.Graph()
        triplets = self.get_triplets()
        for entity1, relation, entity2 in triplets:
            nx_graph.add_node(entity1.name)
            nx_graph.add_node(entity2.name)
            nx_graph.add_edge(
                relation.source_id,
                relation.target_id,
                relationship=relation.label,
                description=relation.properties.get("relationship_description", "No description provided"),
            )
        logging.info(f"Created nx_graph with {nx_graph.number_of_nodes()} nodes and {nx_graph.number_of_edges()} edges")
        return nx_graph

    def _collect_community_info(self, nx_graph, clusters):
        entity_info = defaultdict(set)
        community_info = defaultdict(list)
        for item in clusters:
            node = item.node
            cluster_id = item.cluster
            entity_info[node].add(cluster_id)
            for neighbor in nx_graph.neighbors(node):
                edge_data = nx_graph.get_edge_data(node, neighbor)
                if edge_data:
                    detail = f"{node} -> {neighbor} -> {edge_data['relationship']} -> {edge_data['description']}"
                    community_info[cluster_id].append(detail)
        entity_info = {k: list(v) for k, v in entity_info.items()}
        return dict(entity_info), dict(community_info)

    def _summarize_communities(self, community_info):
        for community_id, details in community_info.items():
            details_text = "\n".join(details) + "."
            self.community_summary[community_id] = self.generate_community_summary(details_text)

    def get_community_summaries(self):
        if not self.community_summary:
            self.build_communities()
        return self.community_summary

graph_store = GraphRAGStore(
    username=config["neo4j_username"],
    password=config["neo4j_password"],
    url=config["neo4j_uri"]
)

# Validate Neo4j graph content
def validate_neo4j_graph(graph_store):
    try:
        triplets = graph_store.get_triplets()
        logging.info(f"Neo4j contains {len(triplets)} triplets")
        if triplets:
            logging.debug(f"Sample triplets: {triplets[:5]}")
        return len(triplets) > 0
    except Exception as e:
        logging.error(f"Error validating Neo4j graph: {e}")
        return False

# Build PropertyGraphIndex
logging.info("Building property graph index...")
index = PropertyGraphIndex(
    nodes=nodes,
    kg_extractors=[kg_extractor],
    property_graph_store=graph_store,
    show_progress=True,
)

# Build communities if graph is not empty
if validate_neo4j_graph(graph_store):
    graph_store.build_communities()
    logging.info("Property graph and communities built!")
else:
    logging.warning("Empty graph detected. Proceeding without communities.")

# --- GraphRAGQueryEngine ---
class GraphRAGQueryEngine:
    def __init__(self, graph_store, index, llm, similarity_top_k=20):
        self.graph_store = graph_store
        self.index = index
        self.llm = llm
        self.similarity_top_k = similarity_top_k

    def custom_query(self, query_str: str) -> Dict[str, Any]:
        entities = self.get_entities(query_str, self.similarity_top_k)
        community_ids = self.retrieve_entity_communities(self.graph_store.entity_info, entities)
        community_summaries = self.graph_store.get_community_summaries()
        selected_communities = {id: summary for id, summary in community_summaries.items() if id in community_ids}
        community_answers = [
            self.generate_answer_from_summary(summary, query_str)
            for summary in selected_communities.values()
        ]
        final_answer = self.aggregate_answers(community_answers) if community_answers else "No relevant information found."

        hierarchical_info = {
            0: [
                {
                    "type": "community",
                    "content": {
                        "id": cid,
                        "summary": summary,
                        "entities": self.get_entities_in_community(cid)
                    }
                }
                for cid, summary in selected_communities.items()
            ]
        }

        return {
            "query": query_str,
            "response": final_answer,
            "hierarchical_info": hierarchical_info,
            "layers_searched": [0],
            "communities_covered": len(selected_communities)
        }

    def get_entities(self, query_str, similarity_top_k):
        nodes_retrieved = self.index.as_retriever(similarity_top_k=similarity_top_k).retrieve(query_str)
        entities = set()
        pattern = r"^(\w+(?:\s+\w+)*)\s*->\s*([a-zA-Z\s]+?)\s*->\s*(\w+(?:\s+\w+)*)$"
        for node in nodes_retrieved:
            matches = re.findall(pattern, node.text, re.MULTILINE | re.IGNORECASE)
            for match in matches:
                subject = match[0]
                obj = match[2]
                entities.add(subject)
                entities.add(obj)
        logging.debug(f"Retrieved entities for query '{query_str}': {entities}")
        return list(entities)

    def retrieve_entity_communities(self, entity_info, entities):
        community_ids = []
        for entity in entities:
            if entity in entity_info:
                community_ids.extend(entity_info[entity])
        return list(set(community_ids))

    def generate_answer_from_summary(self, community_summary, query):
        prompt = f"Given the community summary: {community_summary}, how would you answer the following query? Query: {query}"
        messages = [
            ChatMessage(role="system", content=prompt),
            ChatMessage(role="user", content="I need an answer based on the above information."),
        ]
        response = self.llm.chat(messages)
        cleaned_response = re.sub(r"^assistant:\s*", "", str(response)).strip()
        return cleaned_response

    def aggregate_answers(self, community_answers):
        prompt = "Combine the following intermediate answers into a final, concise response."
        messages = [
            ChatMessage(role="system", content=prompt),
            ChatMessage(role="user", content=f"Intermediate answers: {community_answers}"),
        ]
        final_response = self.llm.chat(messages)
        cleaned_final_response = re.sub(r"^assistant:\s*", "", str(final_response)).strip()
        return cleaned_final_response

    def get_entities_in_community(self, community_id):
        return [entity for entity, communities in self.graph_store.entity_info.items() if community_id in communities]

# Initialize query engine
query_engine = GraphRAGQueryEngine(
    graph_store=graph_store,
    index=index,
    llm=llm,
    similarity_top_k=10
)

# --- Evaluation (keeping original code) ---
class PropertyGraphEvaluator:
    def __init__(self):
        self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
        logging.info("Initialized Property Graph evaluator")

class FaithfulnessEvaluator:
    def __init__(self, evaluator: PropertyGraphEvaluator):
        self.evaluator = evaluator

    def evaluate(self, query: str, response: str, contexts: List[str]):
        try:
            if not response or not contexts:
                return type('Result', (), {'passing': False, 'feedback': 'Empty response or contexts'})()

            response_embedding = self.evaluator.sentence_model.encode([response])
            context_embeddings = self.evaluator.sentence_model.encode(contexts)
            similarities = cosine_similarity(response_embedding, context_embeddings)[0]
            max_similarity = np.max(similarities)
            threshold = 0.3
            passing = max_similarity > threshold
            feedback = f"Max similarity: {max_similarity:.3f}, Threshold: {threshold}"
            return type('Result', (), {'passing': passing, 'feedback': feedback})()
        except Exception as e:
            logging.error(f"Error in faithfulness evaluation: {e}")
            return type('Result', (), {'passing': False, 'feedback': f'Error: {e}'})()

class RelevancyEvaluator:
    def __init__(self, evaluator: PropertyGraphEvaluator):
        self.evaluator = evaluator

    def evaluate(self, query: str, response: str, contexts: List[str]):
        try:
            if not response or not query:
                return type('Result', (), {'passing': False, 'feedback': 'Empty response or query'})()

            query_embedding = self.evaluator.sentence_model.encode([query])
            response_embedding = self.evaluator.sentence_model.encode([response])
            similarity = cosine_similarity(query_embedding, response_embedding)[0][0]
            threshold = 0.4
            passing = similarity > threshold
            feedback = f"Query-response similarity: {similarity:.3f}, Threshold: {threshold}"
            return type('Result', (), {'passing': passing, 'feedback': feedback})()
        except Exception as e:
            logging.error(f"Error in relevancy evaluation: {e}")
            return type('Result', (), {'passing': False, 'feedback': f'Error: {e}'})()

class CorrectnessEvaluator:
    def __init__(self, evaluator: PropertyGraphEvaluator):
        self.evaluator = evaluator

    def evaluate(self, query: str, response: str, reference: str):
        try:
            if not response or not reference:
                return type('Result', (), {'passing': False, 'score': 0.0, 'feedback': 'Empty response or reference'})()

            response_embedding = self.evaluator.sentence_model.encode([response])
            reference_embedding = self.evaluator.sentence_model.encode([reference])
            semantic_sim = cosine_similarity(response_embedding, reference_embedding)[0][0]

            scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=True)
            rouge_scores = scorer.score(reference, response)
            rouge_l = rouge_scores['rougeL'].fmeasure

            combined_score = (semantic_sim + rouge_l) / 2
            threshold = 0.3
            passing = combined_score > threshold
            feedback = f"Semantic sim: {semantic_sim:.3f}, ROUGE-L: {rouge_l:.3f}, Combined: {combined_score:.3f}"
            return type('Result', (), {'passing': passing, 'score': combined_score, 'feedback': feedback})()
        except Exception as e:
            logging.error(f"Error in correctness evaluation: {e}")
            return type('Result', (), {'passing': False, 'score': 0.0, 'feedback': f'Error: {e}'})()

def compute_rouge_bleu(response: str, reference: str) -> Dict[str, float]:
    try:
        scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=True)
        rouge_scores = scorer.score(reference, response)
        rouge_l = rouge_scores['rougeL'].fmeasure

        reference_tokens = [nltk.word_tokenize(reference.lower())]
        response_tokens = nltk.word_tokenize(response.lower())
        bleu_score = sentence_bleu(reference_tokens, response_tokens, weights=(0.25, 0.25, 0.25, 0.25),
                                  smoothing_function=SmoothingFunction().method1)
        return {"rouge_l": rouge_l, "bleu_4": bleu_score}
    except Exception as e:
        logging.warning(f"Error computing ROUGE/BLEU: {e}")
        return {"rouge_l": 0.0, "bleu_4": 0.0}

def evaluate_node_relevance_opensource(query: str, hierarchical_info: Dict[int, List[Dict]], sentence_model) -> float:
    try:
        relevant_nodes = 0
        total_nodes = 0
        query_embedding = sentence_model.encode([query])

        for layer, nodes in hierarchical_info.items():
            for node in nodes:
                total_nodes += 1
                content = node.get('content', {}).get('summary', '')
                if not content:
                    continue
                content_embedding = sentence_model.encode([content])
                similarity = cosine_similarity(query_embedding, content_embedding)[0][0]
                if similarity > 0.3:
                    relevant_nodes += 1
        return relevant_nodes / total_nodes if total_nodes > 0 else 0.0
    except Exception as e:
        logging.warning(f"Error evaluating node relevance: {e}")
        return 0.0

def load_eval_dataset(json_file_path: str) -> List[Dict]:
    try:
        if not os.path.exists(json_file_path):
            logging.error(f"Dataset file not found: {json_file_path}")
            return []

        with open(json_file_path, 'r') as f:
            data = [json.loads(line) for line in f]
        logging.info(f"Loaded {len(data)} evaluation samples")
        return data
    except Exception as e:
        logging.error(f"Error loading dataset: {e}")
        return []

def evaluate_query(query_engine, query_data: Dict, evaluators, sentence_model) -> Dict[str, Any]:
    query = query_data["question"]
    reference = query_data["answer"]
    context = query_data.get("context", "")

    try:
        result = query_engine.custom_query(query)
        response_text = result.get("response", "")
        hierarchical_info = result.get("hierarchical_info", {})

        if not response_text:
            logging.warning(f"Empty response for query: {query}")
            response_text = ""

        faithfulness_evaluator, relevancy_evaluator, correctness_evaluator = evaluators

        eval_contexts = []
        if hierarchical_info:
            for layer, nodes in hierarchical_info.items():
                for node in nodes:
                    content = node.get('content', {})
                    summary = content.get('summary', str(content))
                    if summary:
                        eval_contexts.append(summary)
        if not eval_contexts:
            eval_contexts = [context] if context else ["No context available"]

        faithfulness_result = faithfulness_evaluator.evaluate(query=query, response=response_text, contexts=eval_contexts)
        relevancy_result = relevancy_evaluator.evaluate(query=query, response=response_text, contexts=eval_contexts)

        source_relevancy_results = []
        if hierarchical_info:
            for layer, nodes in hierarchical_info.items():
                for node in nodes:
                    content = node.get('content', {}).get('summary', str(node.get('content', '')))
                    if not content:
                        continue
                    try:
                        node_result = relevancy_evaluator.evaluate(query=query, response=response_text, contexts=[content])
                        source_relevancy_results.append(node_result.passing)
                    except Exception as e:
                        logging.warning(f"Error evaluating node relevancy: {e}")

        source_relevancy_score = (sum(source_relevancy_results) / len(source_relevancy_results)
                                 if source_relevancy_results else 0.0)

        correctness_result = correctness_evaluator.evaluate(query=query, response=response_text, reference=reference)
        rouge_bleu_scores = compute_rouge_bleu(response_text, reference)
        node_precision = evaluate_node_relevance_opensource(query, hierarchical_info, sentence_model) if hierarchical_info else 0.0
        total_communities = len(graph_store.get_community_summaries())
        communities_covered = result.get("communities_covered", 0)
        community_coverage = communities_covered / total_communities if total_communities > 0 else 0.0

        return {
            "query": query,
            "response": response_text,
            "reference": reference,
            "faithfulness_score": 1 if faithfulness_result.passing else 0,
            "faithfulness_feedback": faithfulness_result.feedback or "No feedback",
            "relevancy_score": 1 if relevancy_result.passing else 0,
            "relevancy_feedback": relevancy_result.feedback or "No feedback",
            "source_relevancy_score": source_relevancy_score,
            "correctness_score": correctness_result.score if hasattr(correctness_result, 'score') else 0.0,
            "correctness_passing": 1 if correctness_result.passing else 0,
            "correctness_feedback": correctness_result.feedback or "No feedback",
            "rouge_l": rouge_bleu_scores["rouge_l"],
            "bleu_4": rouge_bleu_scores["bleu_4"],
            "node_precision": node_precision,
            "community_coverage": community_coverage,
            "total_communities": total_communities,
            "communities_covered": communities_covered,
            "layers_searched": result.get("layers_searched", []),
            "hierarchical_info": hierarchical_info
        }
    except Exception as e:
        logging.error(f"Error evaluating query '{query}': {e}")
        return {
            "query": query,
            "response": "",
            "reference": reference,
            "faithfulness_score": 0,
            "faithfulness_feedback": f"Error: {e}",
            "relevancy_score": 0,
            "relevancy_feedback": f"Error: {e}",
            "source_relevancy_score": 0.0,
            "correctness_score": 0.0,
            "correctness_passing": 0,
            "correctness_feedback": f"Error: {e}",
            "rouge_l": 0.0,
            "bleu_4": 0.0,
            "node_precision": 0.0,
            "community_coverage": 0.0,
            "total_communities": 0,
            "communities_covered": 0,
            "layers_searched": [],
            "hierarchical_info": {}
        }

def run_evaluation(query_engine, dataset_path: str, output_path: str = "evaluation_results.json"):
    """Run comprehensive evaluation on the dataset"""
    dataset = load_eval_dataset(dataset_path)
    if not dataset:
        logging.error("No evaluation dataset loaded. Exiting evaluation.")
        return

    evaluator = PropertyGraphEvaluator()
    faithfulness_evaluator = FaithfulnessEvaluator(evaluator)
    relevancy_evaluator = RelevancyEvaluator(evaluator)
    correctness_evaluator = CorrectnessEvaluator(evaluator)
    evaluators = (faithfulness_evaluator, relevancy_evaluator, correctness_evaluator)

    results = []
    for i, query_data in enumerate(tqdm(dataset, desc="Evaluating queries")):
        logging.info(f"Evaluating query {i+1}/{len(dataset)}: {query_data.get('question', '')[:100]}...")
        result = evaluate_query(query_engine, query_data, evaluators, evaluator.sentence_model)
        results.append(result)

    metrics = calculate_aggregate_metrics(results)
    
    output_data = {
        "individual_results": results,
        "aggregate_metrics": metrics,
        "evaluation_summary": {
            "total_queries": len(results),
            "successful_queries": sum(1 for r in results if r["response"]),
            "average_communities_covered": np.mean([r["communities_covered"] for r in results]),
            "total_communities": results[0]["total_communities"] if results else 0
        }
    }
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    logging.info(f"Evaluation completed. Results saved to {output_path}")
    print_evaluation_summary(metrics)
    
    return output_data

def calculate_aggregate_metrics(results: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate aggregate metrics from individual results"""
    if not results:
        return {}
    
    metrics = {}
    metrics["avg_faithfulness"] = np.mean([r["faithfulness_score"] for r in results])
    metrics["avg_relevancy"] = np.mean([r["relevancy_score"] for r in results])
    metrics["avg_source_relevancy"] = np.mean([r["source_relevancy_score"] for r in results])
    metrics["avg_correctness"] = np.mean([r["correctness_score"] for r in results])
    metrics["avg_correctness_passing"] = np.mean([r["correctness_passing"] for r in results])
    metrics["avg_rouge_l"] = np.mean([r["rouge_l"] for r in results])
    metrics["avg_bleu_4"] = np.mean([r["bleu_4"] for r in results])
    metrics["avg_node_precision"] = np.mean([r["node_precision"] for r in results])
    metrics["avg_community_coverage"] = np.mean([r["community_coverage"] for r in results])
    
    non_empty_responses = [r for r in results if r["response"]]
    metrics["response_rate"] = len(non_empty_responses) / len(results)
    
    if non_empty_responses:
        metrics["avg_response_length"] = np.mean([len(r["response"]) for r in non_empty_responses])
    else:
        metrics["avg_response_length"] = 0
    
    metrics["avg_communities_covered"] = np.mean([r["communities_covered"] for r in results])
    metrics["total_communities"] = results[0]["total_communities"] if results else 0
    
    return metrics

def print_evaluation_summary(metrics: Dict[str, float]):
    """Print a formatted summary of evaluation metrics"""
    print("\n" + "="*50)
    print("EVALUATION SUMMARY")
    print("="*50)
    
    print(f"Response Rate: {metrics.get('response_rate', 0):.3f}")
    print(f"Average Response Length: {metrics.get('avg_response_length', 0):.1f} characters")
    
    print(f"\nCore Metrics:")
    print(f"  Faithfulness: {metrics.get('avg_faithfulness', 0):.3f}")
    print(f"  Relevancy: {metrics.get('avg_relevancy', 0):.3f}")
    print(f"  Source Relevancy: {metrics.get('avg_source_relevancy', 0):.3f}")
    print(f"  Correctness Score: {metrics.get('avg_correctness', 0):.3f}")
    print(f"  Correctness Passing: {metrics.get('avg_correctness_passing', 0):.3f}")
    
    print(f"\nText Metrics:")
    print(f"  ROUGE-L: {metrics.get('avg_rouge_l', 0):.3f}")
    print(f"  BLEU-4: {metrics.get('avg_bleu_4', 0):.3f}")
    
    print(f"\nGraph Metrics:")
    print(f"  Node Precision: {metrics.get('avg_node_precision', 0):.3f}")
    print(f"  Community Coverage: {metrics.get('avg_community_coverage', 0):.3f}")
    print(f"  Avg Communities Covered: {metrics.get('avg_communities_covered', 0):.1f}")
    print(f"  Total Communities: {metrics.get('total_communities', 0)}")
    
    print("="*50)

def create_evaluation_plots(results_file: str):
    """Create visualization plots from evaluation results"""
    try:
        with open(results_file, 'r') as f:
            data = json.load(f)
        
        results = data["individual_results"]
        metrics = data["aggregate_metrics"]
        
        fig, axes = plt.subplots(2, 3, figsize=(15, 10))
        fig.suptitle('Property Graph RAG Evaluation Results', fontsize=16)
        
        scores = ['Faithfulness', 'Relevancy', 'Correctness', 'ROUGE-L', 'BLEU-4', 'Node Precision']
        values = [
            metrics.get('avg_faithfulness', 0),
            metrics.get('avg_relevancy', 0),
            metrics.get('avg_correctness', 0),
            metrics.get('avg_rouge_l', 0),
            metrics.get('avg_bleu_4', 0),
            metrics.get('avg_node_precision', 0)
        ]
        
        axes[0, 0].bar(scores, values)
        axes[0, 0].set_title('Average Scores')
        axes[0, 0].set_ylim(0, 1)
        axes[0, 0].tick_params(axis='x', rotation=45)
        
        community_coverage = [r["community_coverage"] for r in results]
        axes[0, 1].hist(community_coverage, bins=20, alpha=0.7)
        axes[0, 1].set_title('Community Coverage Distribution')
        axes[0, 1].set_xlabel('Coverage Ratio')
        axes[0, 1].set_ylabel('Frequency')
        
        response_lengths = [len(r["response"]) for r in results if r["response"]]
        axes[0, 2].hist(response_lengths, bins=20, alpha=0.7)
        axes[0, 2].set_title('Response Length Distribution')
        axes[0, 2].set_xlabel('Characters')
        axes[0, 2].set_ylabel('Frequency')
        
        correctness_scores = [r["correctness_score"] for r in results]
        axes[1, 0].scatter(community_coverage, correctness_scores, alpha=0.6)
        axes[1, 0].set_title('Correctness vs Community Coverage')
        axes[1, 0].set_xlabel('Community Coverage')
        axes[1, 0].set_ylabel('Correctness Score')
        
        rouge_scores = [r["rouge_l"] for r in results]
        bleu_scores = [r["bleu_4"] for r in results]
        axes[1, 1].scatter(rouge_scores, bleu_scores, alpha=0.6)
        axes[1, 1].set_title('ROUGE-L vs BLEU-4')
        axes[1, 1].set_xlabel('ROUGE-L')
        axes[1, 1].set_ylabel('BLEU-4')
        
        communities_covered = [r["communities_covered"] for r in results]
        axes[1, 2].hist(communities_covered, bins=range(max(communities_covered)+2), alpha=0.7)
        axes[1, 2].set_title('Communities Covered Distribution')
        axes[1, 2].set_xlabel('Number of Communities')
        axes[1, 2].set_ylabel('Frequency')
        
        plt.tight_layout()
        
        plot_filename = results_file.replace('.json', '_plots.png')
        plt.savefig(plot_filename, dpi=300, bbox_inches='tight')
        plt.show()
        
        logging.info(f"Evaluation plots saved to {plot_filename}")
        
    except Exception as e:
        logging.error(f"Error creating evaluation plots: {e}")

def test_query(query_str: str):
    """Test a single query and display results"""
    print(f"\nTesting query: {query_str}")
    print("-" * 50)
    
    try:
        result = query_engine.custom_query(query_str)
        
        print(f"Response: {result['response']}")
        print(f"Communities covered: {result['communities_covered']}")
        print(f"Layers searched: {result['layers_searched']}")
        
        if result['hierarchical_info']:
            print("\nHierarchical Information:")
            for layer, nodes in result['hierarchical_info'].items():
                print(f"  Layer {layer}: {len(nodes)} communities")
                for i, node in enumerate(nodes[:3]):
                    content = node.get('content', {})
                    print(f"    Community {content.get('id', 'N/A')}: {content.get('summary', '')[:100]}...")
    
    except Exception as e:
        print(f"Error testing query: {e}")

# Main execution
if __name__ == "__main__":
    print("\n" + "="*70)
    print("PROPERTY GRAPH RAG WITH ROBUST TIMEOUT & CHECKPOINT SYSTEM")
    print("="*70)
    print(f"✓ Request timeout: {config['request_timeout']}s (5 minutes)")
    print(f"✓ Max retries per request: {config['max_retries']}")
    print(f"✓ Checkpoint file: {config['checkpoint_file']}")
    print(f"✓ Progress will be saved continuously")
    print("="*70 + "\n")
    
    # Test a sample query
    test_query("What are the main symptoms of diabetes?")
    
    # Run full evaluation if dataset exists
    if os.path.exists(config["dataset_path"]):
        print("\nRunning full evaluation...")
        evaluation_results = run_evaluation(
            query_engine=query_engine,
            dataset_path=config["dataset_path"],
            output_path="property_graph_evaluation_results.json"
        )
        
        create_evaluation_plots("property_graph_evaluation_results.json")
    else:
        print(f"\nDataset not found at {config['dataset_path']}. Skipping evaluation.")
        print("You can still test individual queries using the test_query() function.")

print("\n✓ Property Graph RAG system initialized successfully!")
print("\nAvailable functions:")
print("- test_query(query_str): Test a single query")
print("- run_evaluation(query_engine, dataset_path, output_path): Run full evaluation")
print("- create_evaluation_plots(results_file): Create visualization plots")
print("\nCheckpoint info:")
print(f"- Processed nodes: {len(checkpoint_manager.data['processed_nodes'])}")
print(f"- Failed nodes: {len(checkpoint_manager.data['failed_nodes'])}")
print(f"- Last index: {checkpoint_manager.get_last_index()}")