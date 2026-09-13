"""
HNSW -- Hierarchical Navigable Small World graphs, by hand.

The idea, in one paragraph. Put every vector in a graph where each node links to
a few near neighbours, and search by greedy walk: from wherever you are, step to
the neighbour closest to the query, repeat until no neighbour is closer. A flat
such graph gets stuck in local minima, so HNSW stacks several: a sparse top layer
of long hops to cross the space fast, progressively denser layers below for local
refinement, and a full-resolution bottom layer where the answer actually lives.
A search drops down through the layers, using each to place a good entry point
for the next. That is the whole trick -- coarse-to-fine navigation over a graph
that is cheap to store and cheap to walk.

Why implement it rather than import hnswlib. Because the comparison this is for
is a comparison of *behaviour under parameters*, and the parameters -- M,
efConstruction, efSearch -- only teach you anything if you can see what they do.
M is how many neighbours a node keeps: the graph's degree, and so its memory and
its connectivity. efConstruction is how hard build-time search looks for good
neighbours to link; efSearch the same at query time. The recall/latency curve the
frontend plots *is* the efSearch sweep, and the memory number *is* M times the
node count. None of that is visible through a black box.

Distances are squared Euclidean over unit vectors, which ranks identically to
cosine (see base.py) and lets the hot loop stay a single BLAS call.

This is the reference algorithm (Malkov & Yashunin, 2016), including the
neighbour-selection heuristic from the paper -- the part that keeps the graph
navigable by preferring a *diverse* neighbourhood over merely the closest points,
so a node has links that actually reach different regions rather than a cluster
of near-duplicates. The one thing it is not is fast in the constant factors: it
is Python and per-node, where the real libraries are vectorised C++. Absolute
build time will look bad; the *shape* of the tradeoff is real, and the shape is
the point.
"""

from __future__ import annotations

import heapq
import math
import time
from typing import Any

import numpy as np

from tools.vector_db.ann.base import (
    AnnIndex,
    IndexStats,
    as_matrix,
    normalise,
    similarity,
)


class HnswIndex(AnnIndex):
    """A navigable small-world graph with a hand-written builder and searcher."""

    name = "hnsw"

    def __init__(
        self,
        m: int = 16,
        ef_construction: int = 200,
        ef_search: int = 50,
        seed: int = 42,
    ) -> None:
        # M: neighbours per node on the upper layers. The bottom layer gets 2M,
        # because it carries the most traffic and the paper found the base layer
        # benefits from the extra connectivity where the others do not.
        self.m = m
        self.m0 = 2 * m
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.seed = seed

        # Level generation constant. 1/ln(M) is the paper's choice: it makes the
        # expected number of layers ~ln(N) and each layer geometrically sparser,
        # which is what balances the descent cost against the graph height.
        self._level_mult = 1.0 / math.log(m) if m > 1 else 1.0

        self.ids: list[str] = []
        self._vectors: np.ndarray | None = None
        # One dict of {neighbour: None as an ordered set} per node per layer.
        # graph[layer][node] -> list[int]. Layer 0 holds every node; higher
        # layers hold progressively fewer.
        self._graph: list[dict[int, list[int]]] = []
        self._entry: int | None = None
        self._max_level = -1
        self._build_seconds = 0.0

    # -- distances ---------------------------------------------------------

    def _distance(self, a: int, b: int) -> float:
        assert self._vectors is not None
        diff = self._vectors[a] - self._vectors[b]
        return float(diff @ diff)

    def _distances_to(self, query: np.ndarray, nodes: list[int]) -> np.ndarray:
        """Squared L2 from `query` to each node, in one vectorised pass."""
        assert self._vectors is not None
        block = self._vectors[nodes]
        diff = block - query
        return np.einsum("ij,ij->i", diff, diff)

    # -- build -------------------------------------------------------------

    def _random_level(self, rng: np.random.Generator) -> int:
        # -ln(U) * mult, floored: an exponential that puts most nodes on layer 0
        # and a vanishing few on the high layers.
        return int(-math.log(rng.random() + 1e-12) * self._level_mult)

    def build(self, ids: list[str], vectors: Any) -> None:
        start = time.perf_counter()
        matrix = normalise(as_matrix(vectors))
        if len(ids) != matrix.shape[0]:
            raise ValueError(
                f"{len(ids)} ids for {matrix.shape[0]} vectors -- they must correspond"
            )

        self.ids = list(ids)
        self._vectors = matrix
        self._graph = []
        self._entry = None
        self._max_level = -1

        rng = np.random.default_rng(self.seed)
        for node in range(len(ids)):
            self._insert(node, self._random_level(rng))

        self._build_seconds = time.perf_counter() - start

    def _insert(self, node: int, level: int) -> None:
        while len(self._graph) <= level:
            self._graph.append({})

        if self._entry is None:
            for lc in range(level + 1):
                self._graph[lc][node] = []
            self._entry = node
            self._max_level = level
            return

        assert self._vectors is not None
        query = self._vectors[node]
        entry = self._entry

        # Descend the layers above this node's top level using pure greedy
        # search (ef=1): each layer just repositions the entry point for the
        # next, so one best node is all that is needed.
        for lc in range(self._max_level, level, -1):
            entry = self._greedy_descend(query, entry, lc)

        # From this node's top level down to 0, do the wider ef-search and wire
        # in the chosen neighbours.
        for lc in range(min(level, self._max_level), -1, -1):
            candidates = self._search_layer(query, [entry], lc, self.ef_construction)
            max_conn = self.m0 if lc == 0 else self.m
            neighbours = self._select_neighbours(node, candidates, max_conn)

            self._graph[lc].setdefault(node, [])
            self._graph[lc][node] = neighbours
            for neighbour in neighbours:
                self._link(neighbour, node, lc, max_conn)

            entry = candidates[0][1] if candidates else entry

        if level > self._max_level:
            self._max_level = level
            self._entry = node

    def _link(self, node: int, new: int, layer: int, max_conn: int) -> None:
        """Add `new` to `node`'s neighbours, pruning back to `max_conn` if full."""
        neighbours = self._graph[layer].setdefault(node, [])
        if new in neighbours:
            return
        neighbours.append(new)
        if len(neighbours) <= max_conn:
            return
        # Over capacity: re-select which links this node keeps, by the same
        # diversity heuristic used on insert, so pruning cannot collapse a hub
        # into a tight cluster and disconnect a region.
        scored = [(self._distance(node, other), other) for other in neighbours]
        self._graph[layer][node] = self._select_neighbours(node, scored, max_conn)

    # -- layer search ------------------------------------------------------

    def _greedy_descend(self, query: np.ndarray, entry: int, layer: int) -> int:
        """Walk to the local minimum on one layer (ef=1)."""
        best = entry
        best_dist = float(self._distances_to(query, [entry])[0])
        improved = True
        while improved:
            improved = False
            neighbours = self._graph[layer].get(best, [])
            if not neighbours:
                break
            dists = self._distances_to(query, neighbours)
            j = int(np.argmin(dists))
            if dists[j] < best_dist:
                best_dist = float(dists[j])
                best = neighbours[j]
                improved = True
        return best

    def _search_layer(
        self, query: np.ndarray, entries: list[int], layer: int, ef: int
    ) -> list[tuple[float, int]]:
        """Best-first beam search on one layer.

        Returns up to `ef` (distance, node) pairs, nearest first. This is the
        heart of both build and query: a frontier ordered by distance, expanded
        nearest-first, stopping once the closest unexpanded candidate is further
        than the worst result kept so far.
        """
        visited: set[int] = set(entries)
        start = self._distances_to(query, entries)
        # `frontier` is a min-heap of what to explore; `results` a max-heap
        # (negated) of the best ef found. Two heaps because we pop the nearest
        # to explore but evict the farthest to stay within ef.
        frontier: list[tuple[float, int]] = []
        results: list[tuple[float, int]] = []
        for dist, node in zip(start.tolist(), entries, strict=True):
            heapq.heappush(frontier, (dist, node))
            heapq.heappush(results, (-dist, node))

        while frontier:
            dist, node = heapq.heappop(frontier)
            worst = -results[0][0]
            if dist > worst and len(results) >= ef:
                break

            neighbours = [n for n in self._graph[layer].get(node, []) if n not in visited]
            if not neighbours:
                continue
            visited.update(neighbours)
            dists = self._distances_to(query, neighbours)
            for d, neighbour in zip(dists.tolist(), neighbours, strict=True):
                worst = -results[0][0]
                if len(results) < ef or d < worst:
                    heapq.heappush(frontier, (d, neighbour))
                    heapq.heappush(results, (-d, neighbour))
                    if len(results) > ef:
                        heapq.heappop(results)

        return sorted((-nd, n) for nd, n in results)

    def _select_neighbours(
        self, node: int, candidates: list[tuple[float, int]], max_conn: int
    ) -> list[int]:
        """The paper's heuristic: keep near *and* diverse neighbours.

        A candidate is kept only if it is closer to the query node than it is to
        any neighbour already kept. That rejects a cluster of mutually-close
        points -- which would all link to roughly the same region -- in favour of
        links that fan out, which is what keeps later greedy walks from dead-ending.
        Falls back to plain nearest if the heuristic leaves slots unfilled.
        """
        ordered = sorted(candidates)  # nearest first
        kept: list[int] = []
        for dist, candidate in ordered:
            if candidate == node:
                continue
            if len(kept) >= max_conn:
                break
            diverse = all(self._distance(candidate, chosen) >= dist for chosen in kept)
            if diverse:
                kept.append(candidate)

        if len(kept) < max_conn:
            for _, candidate in ordered:
                if candidate == node or candidate in kept:
                    continue
                kept.append(candidate)
                if len(kept) >= max_conn:
                    break
        return kept

    # -- query -------------------------------------------------------------

    def search(self, query: Any, k: int) -> list[tuple[str, float]]:
        if self._vectors is None or not self.ids or self._entry is None:
            return []

        vector = normalise(as_matrix(query))[0]
        entry = self._entry
        for layer in range(self._max_level, 0, -1):
            entry = self._greedy_descend(vector, entry, layer)

        # ef must be at least k, or the beam is narrower than the answer.
        ef = max(self.ef_search, k)
        found = self._search_layer(vector, [entry], 0, ef)

        hits = []
        for dist, node in found[:k]:
            hits.append((self.ids[node], float(similarity(dist))))
        return hits

    # -- stats -------------------------------------------------------------

    def stats(self) -> IndexStats:
        vectors, dim = self._vectors.shape if self._vectors is not None else (0, 0)
        # Memory is the vectors plus the graph. The graph is what M buys and
        # costs: every directed link is one int32, counted across all layers.
        links = sum(len(nbrs) for layer in self._graph for nbrs in layer.values())
        vector_bytes = int(self._vectors.nbytes) if self._vectors is not None else 0
        graph_bytes = links * 4
        return IndexStats(
            name=self.name,
            vectors=vectors,
            dim=dim,
            build_seconds=self._build_seconds,
            bytes=vector_bytes + graph_bytes,
            params={
                "M": self.m,
                "efConstruction": self.ef_construction,
                "efSearch": self.ef_search,
                "links": links,
                "layers": len(self._graph),
            },
        )
