# Solution Guide: Handling Stuck Ollama Requests

## Problem Summary
Your Property Graph RAG script gets stuck at 56% during Ollama LLM requests. After 18+ hours of processing, killing Python or Ollama causes complete failure, forcing you to restart from scratch.

## Root Cause
The original code had `request_timeout=100000.0` (27+ hours), causing:
- Individual requests to hang indefinitely
- No way to skip problematic nodes
- No progress checkpointing
- Complete loss of work when killed

---

## ✅ SOLUTION 1: Enhanced Script with Timeouts & Checkpoints (RECOMMENDED)

### What I've Done
I created `property_graph_rag_robust.py` with the following enhancements:

### Key Features

#### 1. **Request-Level Timeouts**
```python
request_timeout: 300.0  # 5 minutes instead of 27+ hours
```
- Each Ollama request now times out after 5 minutes
- Prevents indefinite hangs
- Adjustable based on your needs

#### 2. **Automatic Retry Logic**
```python
max_retries: 2  # Retry stuck requests twice
skip_after_failures: 3  # Skip node after 3 total failures
```
- Retries failed requests with exponential backoff (10s, 20s, 30s)
- Skips permanently stuck nodes after 3 failures
- Continues processing remaining nodes

#### 3. **Checkpoint System**
```python
checkpoint_file: "/home/871323/RAG/checkpoint.json"
```
- Saves progress after each node
- Resume from last successful point if interrupted
- Tracks:
  - Processed nodes
  - Failed nodes
  - Current index

#### 4. **Detailed Logging**
```python
logging.info(f"Processing node {i+1}/{len(nodes)}")
logging.error(f"TIMEOUT: node {node_id} - SKIPPING")
```
- Real-time progress updates
- Timeout notifications
- Failure tracking

### Usage

```bash
# First run (or fresh start)
python property_graph_rag_robust.py

# If interrupted, just run again - it will resume!
python property_graph_rag_robust.py  # Resumes from checkpoint
```

### Configuration Options

Edit these in the `config` dict:

```python
config = {
    "request_timeout": 300.0,      # Increase if your queries need more time
    "max_retries": 2,              # Number of retry attempts
    "skip_after_failures": 3,      # When to give up on a node
    "checkpoint_file": "/path/to/checkpoint.json"
}
```

**Recommended Values:**
- **Fast documents (simple text):** `request_timeout=180.0` (3 min)
- **Complex documents:** `request_timeout=600.0` (10 min)
- **Very complex/large chunks:** `request_timeout=900.0` (15 min)

---

## ✅ SOLUTION 2: Manual Ollama Request Cancellation

If you need to manually cancel a stuck Ollama request while the script is running:

### Option A: Cancel via Ollama API
```bash
# In another terminal while script is running
curl -X DELETE http://localhost:11434/api/generate
```

### Option B: Restart Ollama Service (Gentler)
```bash
# This cancels all pending requests but Ollama restarts quickly
systemctl restart ollama

# Or if using Docker
docker restart ollama
```

### Option C: Find and Kill Specific Ollama Process
```bash
# Find the stuck process
ps aux | grep ollama

# Kill specific ollama worker (not main service)
kill -TERM <PID>
```

---

## ✅ SOLUTION 3: Rate Limiting & Request Queue

For even more control, you could add rate limiting:

```python
# Add to config
"requests_per_minute": 10,  # Max 10 requests per minute
"concurrent_requests": 1,   # Process one at a time
```

This prevents Ollama from being overwhelmed and reduces hangs.

---

## ✅ SOLUTION 4: Progress Monitoring Script

Create a monitoring script to track progress in real-time:

```bash
#!/bin/bash
# monitor_progress.sh

CHECKPOINT="/home/871323/RAG/checkpoint.json"

while true; do
    if [ -f "$CHECKPOINT" ]; then
        PROCESSED=$(jq '.processed_nodes | length' "$CHECKPOINT")
        FAILED=$(jq '.failed_nodes | length' "$CHECKPOINT")
        LAST_IDX=$(jq '.last_index' "$CHECKPOINT")
        
        echo "=== Progress Update ==="
        echo "Processed: $PROCESSED"
        echo "Failed: $FAILED"
        echo "Last Index: $LAST_IDX"
        echo "======================="
    fi
    sleep 60  # Update every minute
done
```

Run in separate terminal:
```bash
chmod +x monitor_progress.sh
./monitor_progress.sh
```

---

## 🔧 How to Use the Enhanced Script

### Step 1: Backup Your Data
```bash
# Backup Neo4j (optional)
# Your existing Neo4j will be preserved if checkpoint exists

# Backup existing checkpoint if any
cp /home/871323/RAG/checkpoint.json /home/871323/RAG/checkpoint.backup.json
```

### Step 2: Replace Your Script
```bash
# Copy the new robust version
cp /workspace/property_graph_rag_robust.py /home/871323/RAG/property_graph_rag_robust.py

# Or keep original and run new one
cd /home/871323/RAG
python /workspace/property_graph_rag_robust.py
```

### Step 3: Monitor Execution
```bash
# Watch logs in real-time
tail -f /path/to/logfile  # Or just watch console output

# Check checkpoint progress
watch -n 10 'cat /home/871323/RAG/checkpoint.json | jq'
```

### Step 4: Handle Interruptions
If the script gets stuck:

```bash
# Option 1: Wait for timeout (5 minutes)
# The script will automatically skip and continue

# Option 2: Kill script and restart (safe now!)
# Press Ctrl+C
# Then restart:
python property_graph_rag_robust.py  # Resumes automatically

# Option 3: Restart Ollama if truly stuck
systemctl restart ollama
# Then restart script
python property_graph_rag_robust.py
```

---

## 📊 Expected Behavior

### Normal Operation
```
INFO - Processing node 1234/5000
INFO - Starting LLM extraction for node abc123 with 300s timeout...
INFO - Completed LLM extraction for node abc123 successfully
INFO - Extracted 5 entities and 8 relationships
```

### Timeout Scenario
```
INFO - Processing node 1234/5000
INFO - Starting LLM extraction for node abc123 with 300s timeout...
ERROR - TIMEOUT: LLM extraction for node abc123 exceeded 300s - SKIPPING
INFO - Retrying in 10 seconds...
INFO - Processing node 1234/5000 (attempt 2/3)
```

### Resume Scenario
```
INFO - Resuming from checkpoint - last processed index: 2800
INFO - Skipping already processed node: abc123
INFO - Processing node 2801/5000
```

---

## 🎯 Key Improvements Over Original

| Feature | Original | Enhanced |
|---------|----------|----------|
| Timeout | 27+ hours | 5 minutes |
| Retry Logic | None | 2 retries with backoff |
| Checkpointing | None | After each node |
| Resume Capability | None | Full resume support |
| Stuck Request Handling | Kill entire process | Auto-skip after timeout |
| Progress Loss | 100% on crash | 0% - resumes from checkpoint |
| Processing Mode | Parallel (uncontrolled) | Sequential (controllable) |
| Logging | Basic | Detailed with timestamps |

---

## 🚨 Troubleshooting

### Issue: Timeout is too short
**Solution:** Increase `request_timeout` in config
```python
"request_timeout": 600.0  # 10 minutes
```

### Issue: Too many nodes being skipped
**Solution:** Increase retries and timeout
```python
"max_retries": 5,
"request_timeout": 900.0,  # 15 minutes
```

### Issue: Checkpoint not updating
**Solution:** Check file permissions
```bash
chmod 666 /home/871323/RAG/checkpoint.json
```

### Issue: Ollama still hanging
**Solution:** Restart Ollama with better settings
```bash
# Stop Ollama
systemctl stop ollama

# Edit Ollama config to limit concurrent requests
# Then restart
systemctl start ollama
```

### Issue: Want to start fresh
**Solution:** Delete checkpoint
```bash
rm /home/871323/RAG/checkpoint.json
# Script will start from beginning
```

---

## 📈 Performance Comparison

### Original Script
- Runtime: 18+ hours to reach 56% → Est. 32+ hours total
- Risk: 100% failure on any issue
- Recovery: Start from 0%

### Enhanced Script
- Runtime: Similar, but **resilient**
- Risk: Only loses current request (< 5 min work)
- Recovery: Instant resume from checkpoint
- Skips: Bad nodes don't block progress

### Example Timeline
```
Hour 0-10:  Process 2000 nodes → checkpoint saved
Hour 10:    Ollama hangs on node 2001
Hour 10.08: Timeout triggered, skip node 2001
Hour 10.09: Continue with node 2002
Hour 15:    Power failure
Hour 15.01: Restart script → Resume from node 2000
Hour 28:    Complete all 5000 nodes
```

---

## 🔐 Safety Features

1. **Neo4j Protection**: Doesn't clear DB if checkpoint exists
2. **Idempotent**: Safe to run multiple times
3. **Atomic Writes**: Checkpoint saves are atomic
4. **Error Isolation**: One bad node doesn't affect others
5. **Graceful Degradation**: Skips bad nodes, continues processing

---

## 💡 Additional Recommendations

### 1. Use tmux/screen
```bash
# Run in persistent session
tmux new -s rag_processing
python property_graph_rag_robust.py

# Detach: Ctrl+B then D
# Reattach: tmux attach -t rag_processing
```

### 2. Set up Alerts
```bash
# Send email when complete
python property_graph_rag_robust.py && echo "RAG Complete" | mail -s "Done" you@email.com
```

### 3. Monitor System Resources
```bash
# Watch GPU/CPU
watch -n 5 nvidia-smi  # For GPU
htop  # For CPU/RAM
```

### 4. Optimize Ollama
```bash
# Edit /etc/systemd/system/ollama.service
[Service]
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
```

---

## 📝 Summary

**The enhanced script (`property_graph_rag_robust.py`) solves your problem by:**

✅ **Preventing indefinite hangs** (5-minute timeouts)  
✅ **Auto-retrying** failed requests (2 retries)  
✅ **Saving progress** continuously (checkpoint system)  
✅ **Resuming automatically** after interruptions  
✅ **Skipping bad nodes** instead of blocking  
✅ **Preserving your 18 hours of work** (if you create checkpoint from current state)  

**You can now:**
- Kill Python/Ollama anytime → Resume instantly
- Skip stuck requests automatically
- Monitor progress in real-time
- Lose at most 5 minutes of work (one request)

**Next Steps:**
1. Review the config settings in `property_graph_rag_robust.py`
2. Adjust timeout values based on your needs
3. Run the script
4. If it gets stuck, just wait 5 minutes or restart - it will continue!

---

## 🆘 Need Help?

If you encounter issues:

1. Check the logs for specific error messages
2. Review the checkpoint file: `cat checkpoint.json | jq`
3. Verify Ollama is responding: `curl http://localhost:11434/api/tags`
4. Test with a single node first (reduce dataset temporarily)
5. Increase timeout if requests are legitimately slow

---

**Your 80-hour task is now resilient and resumable! 🎉**