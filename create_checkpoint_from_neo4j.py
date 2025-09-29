#!/usr/bin/env python3
"""
Recovery Script: Create Checkpoint from Existing Neo4j Data

This script helps you avoid losing your 18 hours of work by creating
a checkpoint file based on what's already in Neo4j.

Usage:
    python create_checkpoint_from_neo4j.py
"""

import json
from neo4j import GraphDatabase
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Config - Update these to match your setup
CONFIG = {
    "neo4j_uri": "neo4j+s://cacc75f2.databases.neo4j.io",
    "neo4j_username": "neo4j",
    "neo4j_password": "oNVetJ9I2FiRGJAMWqh2ZTXySOel9_IM_YyUagHuaKk",
    "checkpoint_file": "/home/871323/RAG/checkpoint.json",
}


def get_processed_nodes_from_neo4j(uri, username, password):
    """
    Query Neo4j to get all nodes that have already been processed.
    Returns list of node IDs that have contributed entities/relationships.
    """
    driver = GraphDatabase.driver(uri, auth=(username, password))
    processed_nodes = set()
    
    try:
        with driver.session() as session:
            # Get all entity nodes - they contain source node info in properties
            result = session.run("""
                MATCH (n)
                WHERE n.document_id IS NOT NULL OR n.ref_doc_id IS NOT NULL
                RETURN DISTINCT 
                    coalesce(n.document_id, n.ref_doc_id) as node_id
            """)
            
            for record in result:
                node_id = record["node_id"]
                if node_id:
                    processed_nodes.add(node_id)
            
            # Also get nodes from relationships
            result = session.run("""
                MATCH ()-[r]->()
                WHERE r.document_id IS NOT NULL OR r.ref_doc_id IS NOT NULL
                RETURN DISTINCT 
                    coalesce(r.document_id, r.ref_doc_id) as node_id
            """)
            
            for record in result:
                node_id = record["node_id"]
                if node_id:
                    processed_nodes.add(node_id)
            
            # Get total counts for reporting
            entity_count = session.run("MATCH (n) RETURN count(n) as count").single()["count"]
            relationship_count = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()["count"]
            
            logging.info(f"Found {entity_count} entities and {relationship_count} relationships in Neo4j")
            logging.info(f"Identified {len(processed_nodes)} unique processed nodes")
            
    except Exception as e:
        logging.error(f"Error querying Neo4j: {e}")
        logging.info("Will create checkpoint assuming work needs to be preserved")
        # If we can't query, assume we want to keep existing data
        # Return empty set to avoid clearing the database
        processed_nodes = set()
    finally:
        driver.close()
    
    return list(processed_nodes)


def create_checkpoint(processed_nodes, checkpoint_file):
    """
    Create a checkpoint file with the list of processed nodes.
    """
    checkpoint_data = {
        "processed_nodes": processed_nodes,
        "failed_nodes": [],
        "last_index": len(processed_nodes) - 1 if processed_nodes else 0,
        "note": "Generated from existing Neo4j data to preserve progress"
    }
    
    try:
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint_data, f, indent=2)
        logging.info(f"✓ Checkpoint created: {checkpoint_file}")
        logging.info(f"  - Processed nodes: {len(processed_nodes)}")
        logging.info(f"  - Last index: {checkpoint_data['last_index']}")
        return True
    except Exception as e:
        logging.error(f"Error creating checkpoint file: {e}")
        return False


def estimate_progress(processed_count, total_pdfs=None):
    """
    Estimate progress based on processed nodes.
    """
    if processed_count == 0:
        logging.warning("No processed nodes found. You may be starting fresh.")
        return
    
    logging.info(f"\n{'='*50}")
    logging.info("PROGRESS ESTIMATION")
    logging.info(f"{'='*50}")
    logging.info(f"Processed source nodes: {processed_count}")
    
    if total_pdfs:
        pages_per_pdf = 10  # Estimate
        estimated_total_nodes = total_pdfs * pages_per_pdf
        progress_pct = (processed_count / estimated_total_nodes) * 100
        logging.info(f"Estimated total nodes: ~{estimated_total_nodes}")
        logging.info(f"Estimated progress: ~{progress_pct:.1f}%")
    
    logging.info(f"{'='*50}\n")


def main():
    print("\n" + "="*70)
    print("CHECKPOINT RECOVERY TOOL")
    print("="*70)
    print("This tool creates a checkpoint from your existing Neo4j data")
    print("to preserve your 18 hours of work.")
    print("="*70 + "\n")
    
    # Get processed nodes from Neo4j
    logging.info("Connecting to Neo4j...")
    processed_nodes = get_processed_nodes_from_neo4j(
        CONFIG["neo4j_uri"],
        CONFIG["neo4j_username"],
        CONFIG["neo4j_password"]
    )
    
    if not processed_nodes:
        logging.warning("\n⚠️  No processed nodes found in Neo4j!")
        logging.warning("This could mean:")
        logging.warning("  1. Your data is stored differently than expected")
        logging.warning("  2. Neo4j is empty")
        logging.warning("  3. There was an error querying Neo4j")
        
        response = input("\nDo you want to create an empty checkpoint anyway? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            logging.info("Aborted. No checkpoint created.")
            return
    
    # Estimate progress
    estimate_progress(len(processed_nodes))
    
    # Create checkpoint
    logging.info("Creating checkpoint file...")
    success = create_checkpoint(processed_nodes, CONFIG["checkpoint_file"])
    
    if success:
        print("\n" + "="*70)
        print("✓ SUCCESS!")
        print("="*70)
        print(f"Checkpoint created at: {CONFIG['checkpoint_file']}")
        print(f"Preserved: {len(processed_nodes)} processed nodes")
        print("\nNext steps:")
        print("1. Run the enhanced script: python property_graph_rag_robust.py")
        print("2. It will skip already-processed nodes")
        print("3. Continue from where you left off")
        print("="*70 + "\n")
    else:
        print("\n❌ Failed to create checkpoint. Check the logs above.")


if __name__ == "__main__":
    main()