# DeepAgents KBQA Data

This namespace currently stores only runtime assets required by the KBQA tools.

```text
runtime/freebase_env/              # Freebase indexes, embeddings, SQLite names, Virtuoso data
runtime/tools_impl/.subgraph_cache # Generated subgraph cache written by build_subgraph_schema
runtime/tools_impl/.sandbox        # Temporary execute_code sandbox files
```

Question datasets, training data, rewards, and training outputs are intentionally not migrated.
