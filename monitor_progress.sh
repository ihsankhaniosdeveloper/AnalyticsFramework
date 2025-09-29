#!/bin/bash
# Progress Monitor for Property Graph RAG
# Usage: ./monitor_progress.sh

CHECKPOINT="/home/871323/RAG/checkpoint.json"
LOG_FILE="/home/871323/RAG/processing.log"  # Adjust if your log is elsewhere

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "⚠️  jq is not installed. Installing..."
    sudo apt-get install -y jq || sudo yum install -y jq || {
        echo "❌ Failed to install jq. Please install manually: sudo apt-get install jq"
        exit 1
    }
fi

echo "=========================================="
echo "  Property Graph RAG Progress Monitor"
echo "=========================================="
echo ""
echo "Checkpoint file: $CHECKPOINT"
echo "Press Ctrl+C to exit"
echo ""

LAST_PROCESSED=0
START_TIME=$(date +%s)

while true; do
    clear
    echo "=========================================="
    echo "  Property Graph RAG - Live Progress"
    echo "=========================================="
    echo ""
    
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))
    HOURS=$((ELAPSED / 3600))
    MINUTES=$(((ELAPSED % 3600) / 60))
    SECONDS=$((ELAPSED % 60))
    
    echo "Monitor Runtime: ${HOURS}h ${MINUTES}m ${SECONDS}s"
    echo "Current Time: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    
    if [ -f "$CHECKPOINT" ]; then
        echo -e "${GREEN}✓ Checkpoint found${NC}"
        echo ""
        
        # Parse checkpoint data
        PROCESSED=$(jq '.processed_nodes | length' "$CHECKPOINT" 2>/dev/null || echo "0")
        FAILED=$(jq '.failed_nodes | length' "$CHECKPOINT" 2>/dev/null || echo "0")
        LAST_IDX=$(jq '.last_index' "$CHECKPOINT" 2>/dev/null || echo "0")
        
        echo -e "${BLUE}Progress Statistics:${NC}"
        echo "  Processed Nodes:    $PROCESSED"
        echo "  Failed Nodes:       $FAILED"
        echo "  Last Index:         $LAST_IDX"
        
        # Calculate processing rate
        if [ $PROCESSED -gt $LAST_PROCESSED ]; then
            RATE=$((PROCESSED - LAST_PROCESSED))
            echo -e "  ${GREEN}Processing Rate:    +$RATE nodes/minute${NC}"
        fi
        LAST_PROCESSED=$PROCESSED
        
        echo ""
        
        # Success rate
        if [ $PROCESSED -gt 0 ]; then
            TOTAL=$((PROCESSED + FAILED))
            SUCCESS_RATE=$((PROCESSED * 100 / TOTAL))
            echo "  Success Rate:       ${SUCCESS_RATE}%"
        fi
        
        # Estimate completion (if we have rate data)
        if [ $PROCESSED -gt 10 ]; then
            # Assume typical RAG has ~1000-5000 nodes
            # Adjust this based on your dataset
            ESTIMATED_TOTAL=2000  # Change this to match your dataset
            REMAINING=$((ESTIMATED_TOTAL - PROCESSED))
            
            if [ $REMAINING -gt 0 ] && [ $PROCESSED -gt 0 ]; then
                AVG_TIME_PER_NODE=$((ELAPSED / PROCESSED))
                ETA_SECONDS=$((REMAINING * AVG_TIME_PER_NODE))
                ETA_HOURS=$((ETA_SECONDS / 3600))
                ETA_MINS=$(((ETA_SECONDS % 3600) / 60))
                
                echo ""
                echo -e "${YELLOW}Estimated Completion:${NC}"
                echo "  Estimated Total:    $ESTIMATED_TOTAL nodes"
                echo "  Remaining:          $REMAINING nodes"
                echo "  ETA:                ${ETA_HOURS}h ${ETA_MINS}m"
            fi
        fi
        
    else
        echo -e "${RED}❌ Checkpoint not found${NC}"
        echo ""
        echo "The script may not have started yet, or"
        echo "checkpoint file path may be incorrect."
    fi
    
    echo ""
    echo "=========================================="
    
    # Show recent log entries if log file exists
    if [ -f "$LOG_FILE" ]; then
        echo ""
        echo -e "${BLUE}Recent Activity (last 5 lines):${NC}"
        tail -n 5 "$LOG_FILE" 2>/dev/null || echo "No recent logs"
    fi
    
    echo ""
    echo "=========================================="
    echo "Updating every 60 seconds..."
    echo "Press Ctrl+C to exit"
    
    sleep 60
done