"""
Approximate nearest-neighbour indexes, hand-written for comparison.

Three implementations of one interface (`base.AnnIndex`), so the retrieval
pipeline can be run over each and the tradeoffs measured rather than assumed:

* `flat.FlatIndex`   -- exact, the ground truth and the memory baseline
* `hnsw.HnswIndex`   -- a navigable small-world graph: fast, accurate, large
* `ivfpq.IvfPqIndex` -- inverted lists over product-quantized codes: tiny, tunable

and one composition over the above:

* `rerank.RerankIndex` -- wraps a base index with an exact re-scoring pass, the
  two-stage pattern that recovers IVF-PQ's recall while keeping its memory

None wraps FAISS or hnswlib. The point is to see the algorithms, so the algorithms
are in the files.
"""

from tools.vector_db.ann.base import AnnIndex, IndexStats
from tools.vector_db.ann.faiss_ref import (
    HAVE_FAISS,
    FaissHnswIndex,
    FaissIvfPqIndex,
)
from tools.vector_db.ann.flat import FlatIndex
from tools.vector_db.ann.hnsw import HnswIndex
from tools.vector_db.ann.ivfpq import IvfPqIndex
from tools.vector_db.ann.rerank import RerankIndex

#: name -> constructor, for the API and benchmark to build by string. RerankIndex
#: is not here: it wraps a base index rather than building from defaults, so it is
#: constructed explicitly (see benchmark.sweep). The FAISS references are opt-in
#: and only meaningful when faiss is installed, so they are kept out too.
INDEX_TYPES = {"flat": FlatIndex, "hnsw": HnswIndex, "ivfpq": IvfPqIndex}

__all__ = [
    "AnnIndex",
    "IndexStats",
    "FlatIndex",
    "HnswIndex",
    "IvfPqIndex",
    "RerankIndex",
    "FaissHnswIndex",
    "FaissIvfPqIndex",
    "HAVE_FAISS",
    "INDEX_TYPES",
]
