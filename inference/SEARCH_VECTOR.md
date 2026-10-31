# Search evidence vectors

The embedding-backed setup uses Qwen3-Embedding-8B, a single Qdrant local-mode
service, and per-trajectory scope filtering. Qdrant local mode is embedded in
one service process; it is not the standalone Qdrant server. Keep its storage
on persistent local disk, and do not open the same directory in another process.

Install `workspace/env/bin/pip install -r inference/requirements-vector.txt`.
Launch on an available GPU, then start the two loopback services:

```bash
inference/scripts/serve_single_gpu.sh embedding 0 19004
workspace/env/bin/python inference/retrieval_vllm_adapter.py --role embedding --model QWEN3-EMBEDDING-8B --upstream http://127.0.0.1:19004 --port 18213
workspace/env/bin/python inference/search_vector_service.py --path workspace/vector-store/qdrant --embedding-base http://127.0.0.1:19004 --model QWEN3-EMBEDDING-8B --port 18216
```

For newly launched Agents, configure:

```bash
export QUEST_SEARCH_VECTOR_URL=http://127.0.0.1:18216
export VISIT_EXPERIMENT_METHOD=bm25_embedding
export VISIT_EMBEDDING_URL=http://127.0.0.1:18213
export VISIT_RETRIEVAL_CANDIDATES=64
export VISIT_RETRIEVAL_TOP_K=16
```

When explicitly configured, new Agents can index search results and append
local search hits to a later search response within the same trajectory.
Responses do not include archive IDs. Automatic file archiving, `read_evidence`,
and the old pointer-based search/visit compaction were removed. Visit results
are not automatically added to the vector store by this Agent path. Indexing
failures leave the original search result in context; no durable outbox is
used by the Agent. Existing processes retain their old code and environment.

The local vector store uses the embedding model's served name to namespace the
collection. If the weights change under the same name, start a fresh store or use
a distinct served model name to avoid mixing incompatible embedding spaces.
