"""Org-data adapter interface plus the shared node/relation vocabulary the
whole org graph is built from.

An adapter's only job is to turn some external system's view of "what this
organization is made of" into a version of that graph Xposure can store:
``OrgNodeSpec`` / ``OrgEdgeSpec`` values keyed by a stable, adapter-local
``key`` string. The adapter never touches the database — ``app.impact``'s
``persist_org_graph()`` resolves keys to real ``org_node.id`` values and
writes the rows. Keeping persistence out of the adapters is what lets the
same specs come from a YAML file, a spreadsheet, or a live ERP without
each source re-implementing insert/replace/idempotency logic (and what
makes every adapter unit-testable with no database at all).

Why ``key`` and not the database id: an adapter runs before anything is
written, so it cannot know the ids. ``key`` is whatever is stable and
unique WITHIN one adapter's output ("cm_2-5-3", "odoo:product.template:41")
— edges reference nodes by key, and the loader resolves them in one pass.
This also makes a missing edge endpoint a loud, specific error ("edge
references unknown node key ...") rather than a silently dropped edge.

Vocabulary (ORG_NODE_TYPES / ORG_RELATIONS) lives here rather than in
``db/models.py`` on purpose: models.py deliberately types both columns as
plain strings so that adding a node type or relation never needs an
Alembic migration (see its docstring), which means the validation has to
live in application code. This is that code — one list, imported by the
loader and by every adapter, so a typo'd relation fails at load time
instead of quietly producing a node nothing can traverse to.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

# ── Vocabulary ────────────────────────────────────────────────────────────

# Exactly the eight types the takeoff prompt's section 3 (M4) names. Kept
# closed: a ninth type would need M5's priority weighting and M6's action
# routing to agree on what it means, so adding one is a cross-milestone
# decision, not a local one.
ORG_NODE_TYPES: frozenset[str] = frozenset({
    "product", "process", "policy", "control_mapping",
    "evidence", "owner", "supplier", "site",
})

# Directed relations. Direction encodes MEANING ("this policy governs that
# process"), not traversal reachability — app.impact walks the graph
# undirected precisely so that the semantics can stay readable; see
# traverse_impacted_nodes()'s docstring for why.
ORG_RELATIONS: frozenset[str] = frozenset({
    # control_mapping -> the thing the control lands on
    "applies_to",      # control_mapping -> product | process | site | supplier
    "stated_in",       # control_mapping -> policy   (the document that carries the requirement)
    "evidenced_by",    # control_mapping -> evidence (the artifact that proves it)
    "implements",      # control_mapping -> product | process  (takeoff prompt's own example wording)
    # organization structure
    "owned_by",        # anything -> owner
    "governs",         # policy -> process
    "operates_at",     # process -> site
    "produces",        # process -> product
    "supplies",        # supplier -> product
    "belongs_to_line",  # product -> product  (an Odoo product.category modelled as a product-line node; see odoo.py)
})


# ── Specs ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OrgNodeSpec:
    """One org_node row, before it has an id.

    ``attrs`` becomes ``org_node.attrs_json`` verbatim. For
    ``type == "control_mapping"`` it MUST carry ``control_id`` — that is
    the field app.impact matches a Change's clause ids against, so a
    control_mapping without one is a node the impact engine can never
    reach and is rejected at load time rather than stored as dead weight.
    """

    key: str
    type: str
    name: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrgEdgeSpec:
    """One org_edge row, referencing its endpoints by OrgNodeSpec.key."""

    from_key: str
    to_key: str
    relation: str


@dataclass(frozen=True)
class OrgGraphFragment:
    """What an adapter returns: a partial graph.

    "Fragment", not "graph", because most real sources only know part of
    the picture — a self-assessment spreadsheet knows control mappings and
    owners but nothing about products; Odoo knows products and suppliers
    but nothing about controls. Fragments from several adapters are merged
    by key before persisting (see app.impact.merge_fragments()).
    """

    nodes: list[OrgNodeSpec] = field(default_factory=list)
    edges: list[OrgEdgeSpec] = field(default_factory=list)


class OrgDataAdapter(ABC):
    """Base class for every org-data source.

    Deliberately one method. An earlier sketch mirrored the source-adapter
    interface's four-stage ``discover()/fetch()/parse()/structure()`` shape
    (takeoff prompt section 8), but that split exists there because a
    regulation source genuinely has four separable stages (find the URL,
    download the PDF, extract text, cut it into clauses). An org source
    does not: a spreadsheet read and a JSON-RPC call each produce rows in
    one step, and splitting them would create three empty overrides per
    adapter. Symmetry for its own sake is not a reason to make every
    implementation worse.
    """

    #: Short stable identifier, recorded in each node's attrs_json["source"]
    #: so a mixed graph can say which system a node came from.
    name: ClassVar[str] = "base"

    @abstractmethod
    def fetch(self) -> OrgGraphFragment:
        """Pull the current state of this source into node/edge specs.

        Must raise (never return an empty/partial fragment silently) if
        the source is unreachable, misconfigured, or shaped differently
        than expected — docs/PLAN.md section 7: "No silent fallbacks:
        missing model, missing file, failed webhook -> visible error
        state." An empty fragment is a legitimate answer only when the
        source genuinely holds no rows.
        """
        raise NotImplementedError


def validate_fragment(fragment: OrgGraphFragment, *, source: str) -> None:
    """Fail loudly on anything the loader could not store correctly.

    Called by app.impact before persisting, but exposed here so an adapter
    (or its tests) can self-check without a database. Checks, in order:
    unknown node type, duplicate key, control_mapping missing control_id,
    unknown relation, edge endpoint that names no node in the fragment.
    """
    seen: set[str] = set()
    for node in fragment.nodes:
        if node.type not in ORG_NODE_TYPES:
            raise ValueError(
                f"[{source}] node {node.key!r} has unknown type {node.type!r}. "
                f"Known types: {sorted(ORG_NODE_TYPES)}"
            )
        if node.key in seen:
            raise ValueError(f"[{source}] duplicate node key {node.key!r}")
        seen.add(node.key)
        if node.type == "control_mapping" and not str(node.attrs.get("control_id", "")).strip():
            raise ValueError(
                f"[{source}] control_mapping node {node.key!r} has no attrs['control_id']. "
                f"Without it app.impact can never match a regulatory change to this node."
            )

    for edge in fragment.edges:
        if edge.relation not in ORG_RELATIONS:
            raise ValueError(
                f"[{source}] edge {edge.from_key} -> {edge.to_key} has unknown relation "
                f"{edge.relation!r}. Known relations: {sorted(ORG_RELATIONS)}"
            )
        for side, key in (("from", edge.from_key), ("to", edge.to_key)):
            if key not in seen:
                raise ValueError(
                    f"[{source}] edge {edge.from_key} -{edge.relation}-> {edge.to_key} "
                    f"references unknown node key {key!r} on its {side} side"
                )
