"""AS-23: Performance baseline & optimization harness.

Benchmark suite covering:
  - Write throughput: entity batch insert, link batch insert
  - Query latency: single lookup, neighbor traversal, full graph export

CPU/RAM budget targets (to be confirmed against actual modest-hardware spec):
  - 10k entity import: < 5s
  - Full graph JSON for 10k nodes: < 2s
  - Single entity lookup: < 50ms

Usage:
    python -m benchmarks.graph_perf [--entities N] [--links N]
"""

from __future__ import annotations

import argparse
import sys
import time
import tempfile
import statistics
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mdiscovery.graph.database import GraphDatabase
from mdiscovery.graph.models import Entity, Link, SemanticType
from mdiscovery.graph.repository import GraphRepository


# ── Budget constants ──────────────────────────────────────────────────
BUDGET_ENTITY_IMPORT_10K_S  = 5.0   # seconds for 10k entity upserts
BUDGET_GRAPH_JSON_10K_S     = 2.0   # seconds for get_graph_json on 10k nodes
BUDGET_SINGLE_LOOKUP_MS     = 50.0  # ms for single entity get()


def time_it(fn, *args, **kwargs) -> tuple[float, any]:
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    return time.perf_counter() - t0, result


def bench_entity_write(repo: GraphRepository, n: int) -> float:
    entities = [
        Entity(label=f"Entity_{i}", semantic_type=SemanticType.PERSON)
        for i in range(n)
    ]
    elapsed, _ = time_it(repo.entities.upsert_batch, entities)
    return elapsed


def bench_link_write(repo: GraphRepository, entities: list[Entity]) -> float:
    n = min(len(entities) - 1, len(entities))
    links = [
        Link(source_id=entities[i].id, target_id=entities[i + 1].id)
        for i in range(0, n - 1, 2)
    ]
    elapsed, _ = time_it(repo.links.upsert_batch, links)
    return elapsed


def bench_single_lookup(repo: GraphRepository, entity_id: str) -> float:
    elapsed, _ = time_it(repo.entities.get, entity_id)
    return elapsed * 1000  # ms


def bench_graph_json(repo: GraphRepository) -> float:
    elapsed, _ = time_it(repo.get_graph_json)
    return elapsed


def run(n_entities: int = 1000) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        # Kuzu owns the DB path; give it a fresh sub-path, not the temp dir itself.
        db = GraphDatabase(Path(tmpdir) / "bench_db")
        repo = GraphRepository(db)

        print(f"\n{'─' * 60}")
        print(f"  mDiscovery performance benchmark  ({n_entities:,} entities)")
        print(f"{'─' * 60}")

        # Entity write
        elapsed_write = bench_entity_write(repo, n_entities)
        status = "✓" if elapsed_write < BUDGET_ENTITY_IMPORT_10K_S * (n_entities / 10000) else "✗"
        print(f"[{status}] Entity batch write ({n_entities:,}): {elapsed_write:.3f}s")

        # Get all for link bench
        all_entities = repo.entities.all()

        # Link write
        elapsed_links = bench_link_write(repo, all_entities)
        print(f"    Link batch write ({len(all_entities)//2:,}): {elapsed_links:.3f}s")

        # Single lookup
        sample_id = all_entities[0].id if all_entities else ""
        if sample_id:
            # Warm-up
            repo.entities.get(sample_id)
            latencies = [bench_single_lookup(repo, sample_id) for _ in range(10)]
            p50 = statistics.median(latencies)
            status = "✓" if p50 < BUDGET_SINGLE_LOOKUP_MS else "✗"
            print(f"[{status}] Single entity lookup p50: {p50:.1f}ms")

        # Graph JSON export
        elapsed_json = bench_graph_json(repo)
        expected_budget = BUDGET_GRAPH_JSON_10K_S * (n_entities / 10000)
        status = "✓" if elapsed_json < expected_budget else "✗"
        print(f"[{status}] get_graph_json ({n_entities:,} nodes): {elapsed_json:.3f}s")

        stats = repo.stats()
        print(f"\n    Final: {stats['entity_count']:,} entities, {stats['link_count']:,} links")
        print(f"{'─' * 60}\n")

        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="mDiscovery performance benchmark")
    parser.add_argument("--entities", type=int, default=1000)
    args = parser.parse_args()
    run(n_entities=args.entities)
