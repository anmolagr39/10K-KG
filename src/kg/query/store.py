"""Load the graph once and build lookup indexes (plain dicts) for the operators."""
import gzip
import json
from collections import defaultdict
from functools import lru_cache

import networkx as nx

from kg.config import GRAPH_DIR


class GraphStore:
    def __init__(self, g: nx.MultiDiGraph):
        self.g = g
        self.companies: dict[str, dict] = {}
        self.periods: dict[str, list[dict]] = defaultdict(list)      # ticker -> periods sorted by rank
        self.facts: dict[tuple, list[str]] = defaultdict(list)       # (ticker, metric) -> fact ids
        self.line_items: dict[str, list[str]] = defaultdict(list)    # ticker -> unmapped row facts
        self.rel_out: dict[tuple, list[tuple]] = defaultdict(list)   # (ticker, REL) -> [(target node, fact id)]
        self.rel_in: dict[tuple, list[tuple]] = defaultdict(list)    # (target node, REL) -> [(ticker, fact id)]
        self.metrics: dict[str, dict] = {}
        for n, a in g.nodes(data=True):
            t = a.get("type")
            if t == "company":
                self.companies[a["ticker"]] = a
            elif t == "period":
                self.periods[a["ticker"]].append(dict(a, id=n))
            elif t == "metric":
                self.metrics[n.split(":", 1)[1]] = a
            elif t == "fact" and a.get("kind") in ("number", "text"):
                if a.get("metric"):
                    self.facts[(a["ticker"], a["metric"])].append(n)
                else:
                    self.line_items[a["ticker"]].append(n)
        for p in self.periods.values():
            p.sort(key=lambda x: x["rank"])
        for u, v, a in g.edges(data=True):
            if u.startswith("company:") and "fact" in a:
                t = u.split(":", 1)[1]
                self.rel_out[(t, a["rel"])].append((v, a["fact"]))
                self.rel_in[(v, a["rel"])].append((t, a["fact"]))
        # canonical facts first (the primary statement), then corroborating copies
        for k, ids in self.facts.items():
            ids.sort(key=lambda f: (not g.nodes[f].get("canonical"), g.nodes[f].get("statement") == "note"))

    def node(self, nid: str) -> dict:
        return self.g.nodes[nid]

    def source_of(self, fid: str) -> dict:
        for _, v, a in self.g.out_edges(fid, data=True):
            if a.get("rel") == "SOURCED_FROM":
                return dict(self.g.nodes[v], id=v)
        return {}


@lru_cache(maxsize=1)
def store() -> GraphStore:
    with gzip.open(GRAPH_DIR / "graph.json.gz", "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    g = nx.node_link_graph(data, directed=True, multigraph=True, edges="edges")
    return GraphStore(g)
