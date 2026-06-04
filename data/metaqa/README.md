# MetaQA

This directory contains the lightweight text-only MetaQA data used for KBQA testing.

Source mirror: https://huggingface.co/datasets/camazlucas/MetaQA
Official dataset page: https://github.com/yuyuz/MetaQA
Official download folder: https://drive.google.com/drive/folders/0B-36Uca2AvwhTWVFSUZqRXVtbUE?resourcekey=0-kdv6ho5KcpEXdI2aUdLn_g&usp=sharing

Included files:

- `kb/kb.txt`: movie knowledge graph, one triple per line: `subject|relation|object`.
- `1-hop/vanilla/qa_{train,dev,test}.txt`: one-hop natural-language questions.
- `2-hop/vanilla/qa_{train,dev,test}.txt`: two-hop natural-language questions.
- `3-hop/vanilla/qa_{train,dev,test}.txt`: three-hop natural-language questions.

Verified local stats:

- Knowledge graph: 134,741 triples, 43,234 distinct nodes, 9 relations.
- 1-hop QA: 96,106 train / 9,992 dev / 9,947 test.
- 2-hop QA: 118,980 train / 14,872 dev / 14,872 test.
- 3-hop QA: 114,196 train / 14,274 dev / 14,274 test.

Audio and paraphrased NTM data are intentionally not downloaded to keep this local test fixture small.
See `manifest.json` for source URLs, byte sizes, and SHA-256 checksums.
