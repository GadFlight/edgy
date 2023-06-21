# This code is licensed under CC0 (Public Domain). You may freely use or modify it for any purpose.
# The original code was written by GadFlight and can be found at his GitHub repository: (https://github.com/GadFlight)

from asyncore import loop
from collections import defaultdict, deque
from dataclasses import dataclass, field
from types import NoneType
from typing import Any, Mapping, Optional, Type, cast

import bmesh
import bpy
from bmesh.types import BMEdge, BMesh, BMFace, BMVert
from bpy.props import (EnumProperty, BoolProperty)
from bpy.types import Context, Event, Mesh, Operator, AnyType
from heapq import heappush, heappop

from . import util
from .util import OPTIONS_REDO, BlenderOperator, make_enum, report_finished

def is_pole(vert: BMVert) -> bool:
    """Return True if vert is a pole, accounting for non-manifold geometry."""
    return len(vert.link_edges) + int(vert.is_boundary) + int(vert.is_wire) != 4

@dataclass(frozen=True, slots=True)
class PureEdgeLoop:
    """Mesh-independent information about a "pure" edge loop.
    
    A pure edge loop is an ordered sequence of edges which 
      (1) are connected to each other; 
      (2) don't share any faces between edges; 
      (3) don't pass through any poles; 
      (4) are as long as possible."""
    vertices: tuple[int, ...]
    edges: tuple[int, ...]
    edge_set: frozenset[int]

    @property
    def is_closed(self) -> bool:
        """Return True if the loop is closed."""
        return self.vertices[0] == self.vertices[-1]

    def reverse(self) -> 'PureEdgeLoop':
        """Return a new PureEdgeLoop with reversed vertices and edges."""
        return PureEdgeLoop(self.vertices[::-1], self.edges[::-1], self.edge_set)

    def __eq__(self, other: 'PureEdgeLoop') -> bool:
        """Return True if the edge sets of the two loops are equal."""
        if isinstance(other, self.__class__):
            return self.edge_set == other.edge_set
        return False

    def __repr__(self):
        """Return a compact string representation of the edges."""
        return f"PureEdgeLoop(edges=({', '.join(map(str, self.edges))})"

def find_loop(edge: BMEdge, start: BMVert, stop_set: Optional[set[int]] = None) -> PureEdgeLoop:
    """Return a PureEdgeLoop starting at start and ending at a pole or boundary, or back at the start point. 
    If stop_set is not None, then the loop will end at a vertex in stop_set.
    
    Note: since this function doesn't search in both directions, the 'PureEdgeLoop' result will not necessarily
    be 'pure' if the loop is not closed."""
    stop_set = stop_set or set()
    last_edge, tail, head = edge, start, edge.other_vert(start)
    vertices, edges = [tail.index, head.index], [last_edge.index]
    while True:
        if is_pole(head) or head.index in stop_set:
            return PureEdgeLoop(tuple(vertices), tuple(edges), frozenset(edges))
        for next_edge in head.link_edges:
            if not any(face in next_edge.link_faces for face in last_edge.link_faces):
                if next_edge == edge:
                    return PureEdgeLoop(tuple(vertices), tuple(edges), frozenset(edges))
                last_edge, tail, head = next_edge, head, next_edge.other_vert(head)
                vertices.append(head.index)
                edges.append(last_edge.index)
                break
        else:
            # Special case for non-manifold geometry. There may be no edges that don't share a face. Just
            # punt and treat it like a pole.
            return PureEdgeLoop(tuple(vertices), tuple(edges), frozenset(edges))

def pure_edge_loops(bm: BMesh) -> list[PureEdgeLoop]:
    """Return a list of all "pure" edge loops in the mesh."""
    poles = {vert for vert in bm.verts if is_pole(vert)}
    result: list[PureEdgeLoop] = []
    visited: set[int] = set()
    # Find incomplete loops based at poles. We do these first because we want to ensure that they
    # start at a pole rather than the middle of the loop.
    for pole in poles:
        for edge in pole.link_edges:
            if edge.index in visited:
                continue
            loop = find_loop(edge, pole)
            result.append(loop)
            visited.update(loop.edge_set)
    # Find all other loops
    for edge in bm.edges:
        if edge.index in visited:
            continue
        loop = find_loop(edge, edge.verts[0])
        result.append(loop)
        visited.update(loop.edge_set)
    return result

def pure_edge_loop(bm: BMesh, edge: BMEdge) -> PureEdgeLoop:
    """Return the pure edge loop containing edge. The first edge in the loop will either be a pole or
    the edge itself."""
    # This could be faster, but should be good enough, while maintaining simplicity.
    tail = edge.verts[0]
    partial = find_loop(edge, tail)
    if partial.vertices[0] == partial.vertices[-1]:
        # A closed loop. We're done.
        return partial
    result = find_loop(bm.edges[partial.edges[-1]], bm.verts[partial.vertices[-1]])
    if result.edges[-1] == edge.index:
        # It's handy if the supplied edge can be first.
        return PureEdgeLoop(tuple(reversed(result.vertices)), tuple(reversed(result.edges)),
                            frozenset(result.edges))
    return result

@dataclass(frozen=True, slots=True)
class EdgeSelectionInfo:
    """Mesh-independent information about the selected edges in a mesh.
    
    This allows us to reason about whether the selection is composed of loops, and to distinguish between 
    multiple distinct loops."""
    edge_islands: tuple[tuple[int, ...], ...]
    endpoints: tuple[int, ...]
    branching: tuple[int, ...]
    all_selected_verts: tuple[int, ...]

    @classmethod
    def from_bmesh(cls, bm: BMesh) -> 'EdgeSelectionInfo':
        all_verts = tuple(vert.index for vert in bm.verts if vert.select)
        selected_edges = [edge for edge in bm.edges if edge.select]
        if not selected_edges:
            return EdgeSelectionInfo(tuple(), tuple(), tuple(), all_verts)
        # Map selected vertices to their connecting selected edges
        selected_verts_to_edges: Mapping[BMVert, list[BMEdge]] = defaultdict(list)
        for edge in selected_edges:
            for vert in edge.verts:
                selected_verts_to_edges[vert].append(edge)

        endpoints = tuple(
            vert.index for vert, edges in selected_verts_to_edges.items() if len(edges) == 1)
        branches = tuple(
            vert.index for vert, edges in selected_verts_to_edges.items() if len(edges) > 2)

        # Find connected edge groups (islands)
        edge_islands: list[tuple[int, ...]] = []
        searched_edges: set[BMEdge] = set()
        for edge in selected_edges:
            if edge in searched_edges:
                continue

            # Search connected edges
            island: list[int] = []
            edges_to_search = {edge}

            while edges_to_search:
                current_edge = edges_to_search.pop()
                island.append(current_edge.index)
                searched_edges.add(current_edge)
                # Add connected edges to search list
                for vert in current_edge.verts:
                    edges_to_search.update(edge for edge in selected_verts_to_edges[vert]
                                           if edge not in searched_edges)

            edge_islands.append(tuple(island))

        return EdgeSelectionInfo(tuple(edge_islands), endpoints, branches, all_verts)

@dataclass(frozen=True, slots=True)
class SavedSelectionState:
    """Mesh-independent information about the selection state of a mesh. This can be used to restore the
    selection state after a mesh has been modified, or to quickly query selection status."""
    mode: tuple[bool, bool, bool]
    selected_verts: frozenset[int]
    selected_edges: frozenset[int]
    selected_faces: frozenset[int]
    active_type: Type[Any] = NoneType
    active: int = -1

    @classmethod
    def from_context(cls, context: Context):
        """Create a SavedSelectionState from the current selection state of the active object."""
        bm = bmesh.from_edit_mesh(cast(Mesh, context.active_object.data))
        active_type = type(bm.select_history.active)
        active = bm.select_history.active.index if bm.select_history.active else -1
        return cls(tuple(context.tool_settings.mesh_select_mode),
                   frozenset(v.index for v in bm.verts if v.select),
                   frozenset(e.index for e in bm.edges if e.select),
                   frozenset(f.index for f in bm.faces if f.select), active_type, active)

    def restore(self, context: Context):
        """Restore the selections status of the active object to the exact state as of the time
        the SavedSelectionState was created."""

        # The devil is in the details on this one. If there are multiple simultaneous selection
        # modes, we need to restore the *right* active element, and we can't just save it directly
        # because it might not be valid when we restore it. This formulation is the result of a
        # lot of trial and error.
        context.tool_settings.mesh_select_mode = list(self.mode)
        bm = bmesh.from_edit_mesh(cast(Mesh, context.active_object.data))
        if self.mode[0]:
            for v in bm.verts:
                v.select = v.index in self.selected_verts
        elif self.mode[1]:
            for e in bm.edges:
                e.select = e.index in self.selected_edges
        else:
            for f in bm.faces:
                f.select = f.index in self.selected_faces
        bm.select_flush_mode()
        if self.active != -1:
            type_to_items = {BMVert: bm.verts, BMEdge: bm.edges, BMFace: bm.faces}
            items = type_to_items.get(self.active_type, [])
            bm.select_history.add(items[self.active])

def find_shortest_path(bm: BMesh, start: BMVert, end: BMVert,
                       exclude_indices: set[int]) -> Optional[tuple[int, ...]]:
    """Find the shortest path between two vertices, while avoiding edges in the provided exclusion set. We define
    'shortest' as the path with the fewest number of edges."""
    vert_to_verts: Mapping[int, list[int]] = defaultdict(list)
    for edge in bm.edges:
        if edge.index in exclude_indices:
            continue
        for vert in edge.verts:
            vert_to_verts[vert.index].append(edge.other_vert(vert).index)

    # Perform a breadth-first search to find the shortest path
    queue: deque[tuple[int, tuple[int, ...]]] = deque([(start.index, ())])
    searched_verts = set[int]()
    while queue:
        current_vert, path = queue.popleft()
        if current_vert in searched_verts:
            continue
        searched_verts.add(current_vert)
        if current_vert == end.index:
            return path + (current_vert,)
        # we prioritize verts that don't share a face with the last vert in the path.
        # this yields more natural-looking results.
        non_sharing = {
            vert for vert in vert_to_verts[current_vert]
            if path and not any(face in bm.verts[vert].link_faces
                                for face in bm.verts[path[-1]].link_faces)
        }
        queue.extend((vert, path + (current_vert,)) for vert in non_sharing)
        queue.extend((vert, path + (current_vert,))
                     for vert in vert_to_verts[current_vert]
                     if vert not in non_sharing)
    return None

@BlenderOperator("mesh.edgy_close_loop", OPTIONS_REDO, "Close Loop",
                 "Close an open edge-loop via the shortest 'clean' path")
class CloseLoop(Operator):
    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        bm = bmesh.from_edit_mesh(cast(Mesh, context.object.data))
        info = EdgeSelectionInfo.from_bmesh(bm)
        if (not info.endpoints) or info.branching:
            self.report({"WARNING"}, "Cannot close loop: not an open loop")
            return {"CANCELLED"}
        if not info.edge_islands:
            self.report({"WARNING"}, "No edges selected")
            return {"CANCELLED"}
        saved_state = SavedSelectionState.from_context(context)
        # find pairs of endpoints that share an island
        for i, island in enumerate(info.edge_islands):
            verts = {v.index for e in island for v in bm.edges[e].verts}
            ends = [v for v in info.endpoints if v in verts]
            if len(ends) != 2:
                continue
            path = find_shortest_path(bm, bm.verts[ends[0]], bm.verts[ends[1]], set(island))
            if not path:
                saved_state.restore(context)
                self.report({"WARNING"}, "Could not find clean closures")
                return {"CANCELLED"}
            if 'VERT' in bm.select_mode:
                for v in path:
                    bm.verts[v].select = True
            else:
                for pair in zip(path, path[1:]):
                    for edge in (e for e in bm.verts[pair[0]].link_edges
                                 if e.verts[0].index == pair[1] or e.verts[1].index == pair[1]):
                        edge.select = True
            bm.select_flush_mode()
            bmesh.update_edit_mesh(cast(Mesh, context.object.data))
        return {"FINISHED"}

@BlenderOperator("mesh.edgy_resize_selection", OPTIONS_REDO, "Grow/Shrink Selection",
                 "Grow or shrink either edge boundary loops or face selections")
class EdgyResizeSelection(Operator):
    direction: EnumProperty(name="Direction", items=make_enum(GROW="Grow", SHRINK="Shrink"),
                            default="GROW")  # type: ignore
    mode: EnumProperty(name="Mode",
                       items=make_enum(AUTOMATIC="Automatic", BOUNDARIES="Boundaries", FACES="Faces",
                                       BLENDER_FACE="Blender default (Faces)",
                                       BLENDER_EDGE="Blender default (Edges)"),
                       default="AUTOMATIC")  # type: ignore

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(cast(AnyType, self), "direction", expand=True)
        layout.prop(cast(AnyType, self), "mode")

    def execute(self, context):
        bm = bmesh.from_edit_mesh(cast(Mesh, context.object.data))
        info = EdgeSelectionInfo.from_bmesh(bm)
        if self.direction == "GROW":
            match self.mode:
                case "BLENDER_FACE":
                    bpy.ops.mesh.select_more(use_face_step=True)
                    return report_finished(self, "Grew face selection (Blender default)")
                case "BLENDER_EDGE":
                    bpy.ops.mesh.select_more(use_face_step=False)
                    return report_finished(self, "Grew edge selection (Blender default)")
                case "AUTOMATIC":
                    face_mode = context.tool_settings.mesh_select_mode[2]
                case _:
                    face_mode = self.mode == "FACES"
            if not info.all_selected_verts:
                return report_finished(self, "No vertices selected", True)
            sel = SavedSelectionState.from_context(context)
            if face_mode:
                bpy.ops.mesh.select_more(use_face_step=True)
                return report_finished(self, "Grew face selection")
            else:
                if not (info.branching or info.endpoints):
                    bpy.ops.mesh.loop_to_region()
                bpy.ops.mesh.select_more(use_face_step=True)
                bpy.ops.mesh.region_to_loop()
                final_edges = {e.index for e in bm.edges if e.select}
                if final_edges == sel.selected_edges:
                    return report_finished(self, "Can't grow boundary selection", True)
                else:
                    return report_finished(self, "Grew boundary selection")
        else:
            match self.mode:
                case "BLENDER_FACE":
                    bpy.ops.mesh.select_less(use_face_step=True)
                    return report_finished(self, "Shrank face selection (Blender default)")
                case "BLENDER_EDGE":
                    bpy.ops.mesh.select_less(use_face_step=False)
                    return report_finished(self, "Shrank edge selection (Blender default)")
                case "AUTOMATIC":
                    face_mode = context.tool_settings.mesh_select_mode[2] or info.branching or info.endpoints
                case _:
                    face_mode = self.mode == "FACES"
            if not info.all_selected_verts:
                return report_finished(self, "No vertices selected", True)
            sel = SavedSelectionState.from_context(context)
            if face_mode:
                bpy.ops.mesh.select_less(use_face_step=True)
            else:
                if info.branching or info.endpoints:
                    return report_finished(self, "Can't shrink boundary selection", True)
                bpy.ops.mesh.loop_to_region()
                bpy.ops.mesh.select_less(use_face_step=True)
                bpy.ops.mesh.region_to_loop()
            if not any(v.select for v in bm.verts):
                sel.restore(context)
                return report_finished(self, "Can't shrink selection (no vertices would remain)", True)
            else:
                return report_finished(self, f"Shrank {'face' if face_mode else 'boundary'} selection")

def edge_under_mouse(context: Context, mouse_x: int, mouse_y: int):
    """Return the index of the edge under the mouse, or -1 if there is none.
    
    For maximum compatibility, this calls blender's native "edge select mode" selection operator, and then
    cleans up so that the selection state is unchanged."""
    mesh = cast(Mesh, context.active_object.data)
    bm = bmesh.from_edit_mesh(mesh)
    sel = SavedSelectionState.from_context(context)
    region = context.region
    coord = mouse_x - region.x, mouse_y - region.y
    context.tool_settings.mesh_select_mode = [False, True, False]
    bpy.ops.view3d.select(extend=False, location=coord)
    e = next((e for e in bm.edges if e.select), None)
    sel.restore(context)
    return cast(int, e.index) if e else -1

@dataclass(order=True, slots=True)
class LoopSearchNode:
    """A node in the search tree for finding the shortest loop containing a given edge.
    
    'length' could be any value to be optimized, but in the current code is the total number of 
    edges in the loop."""
    length: float
    end_vertex: int  # comparing this will produce deterministic results
    loops: list[PureEdgeLoop] = field(compare=False)

MAX_EDGE_LOOPS = 10

def get_edge_loops(bm: BMesh, edge: BMEdge) -> list[frozenset[int]]:
    """Return information on edge loops which include the given BMEdge. 
    
    It includes the 'pure edge loop' containing the edge and, if the loop is not already closed, some of the 
    shortest closed loops which can be formed using it and other pure edge loops."""

    pure_loop = pure_edge_loop(bm, edge)
    all_loops = [pure_loop.edge_set]
    if pure_loop.is_closed:
        return all_loops

    visited_verts = set()
    stop_set = {pure_loop.vertices[0]}
    # Priority queue for best-first search (BFS) Prioritize by the total length of loop sequence (fewer edges is better)
    queue = [LoopSearchNode(len(pure_loop.edges), pure_loop.vertices[-1], [pure_loop])]
    shortest_match = len(bm.edges) + 1  # No match is longer than this
    while queue:
        candidate = heappop(queue)
        # We may want multiple algorithms: shortest only vs. all (within limits)
        if len(all_loops) > MAX_EDGE_LOOPS: 
            break
        if candidate.end_vertex == pure_loop.vertices[0]:  # Closed loop
            shortest_match = candidate.length
            all_loops.append(frozenset(edge for l in candidate.loops for edge in l.edge_set))
            continue
        # There's still more to find -- carry on.
        if candidate.end_vertex in visited_verts:
            continue
        visited_verts.add(candidate.end_vertex)
        v = bm.verts[candidate.end_vertex]
        for loop_edge in v.link_edges:
            if any(loop_edge.index in loop.edge_set for loop in candidate.loops):
                # Mostly this catches immediate backtracking, but it also handles
                # obscure edge cases involving non-manifold geometry.
                continue
            # The stop set lets us handle return to a start vertex that's in the middle
            # of a loop. This is a case that only occurs for non-manifold geometry, but the
            # resulting behavior feels inuitively correct.
            next_loop = find_loop(loop_edge, v, stop_set)
            new_sequence = candidate.loops + [next_loop]
            total_edges = sum(len(loop.edges) for loop in new_sequence)
            heappush(queue, LoopSearchNode(total_edges, next_loop.vertices[-1], new_sequence))
    return all_loops

# Package-level variables for tracking state across operator invocations. This is necessary because
# the operator should be able to cycle through multiple loops, but the user might also change target
# edges or the selection mode between invocations.
current_mesh = None
current_loop: Optional[frozenset[int]] = None
old_selection: Optional[SavedSelectionState] = None

@BlenderOperator("mesh.edgy_select_loop", OPTIONS_REDO, "Select Loop",
                 "Select edge-loops, with further clicks cycling through closed loops")
class EdgySelectLoop(Operator):
    extend: BoolProperty(name="Extend/Toggle Selection", default=False)  # type: ignore
    mode: EnumProperty(name="Mode", items=make_enum(SMART="Smart", DEFAULT="Blender default"),
                       default="SMART")  # type: ignore
    mouse_x: int
    mouse_y: int

    def invoke(self, context: Context, event: Event):
        self.mouse_x, self.mouse_y = event.mouse_x, event.mouse_y
        return self.execute(context)

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        if self.mode == "DEFAULT" or context.tool_settings.mesh_select_mode[2]:
            context.window.cursor_warp(self.mouse_x, self.mouse_y)
            return bpy.ops.mesh.loop_select('INVOKE_DEFAULT', toggle=self.extend)

        bm = bmesh.from_edit_mesh(cast(Mesh, context.object.data))
        edge = edge_under_mouse(context, self.mouse_x, self.mouse_y)
        if edge == -1:
            self.report({"WARNING"}, "No edge selected under mouse")
            return {"CANCELLED"}
        loops = get_edge_loops(bm, bm.edges[edge])
        global current_loop, old_selection, current_mesh
        try:
            is_cache_obsolete = current_mesh != context.object.data or (
                current_loop and not all(bm.edges[e].select for e in current_loop))
        except IndexError:
            is_cache_obsolete = True
        if is_cache_obsolete:
            current_loop = None
            old_selection = None
            current_mesh = context.object.data

        if current_loop is None or current_loop not in loops:
            next_loop = loops[0]
            if not self.extend:
                old_selection = None
            elif all(bm.edges[e].select for e in loops[0]):
                # special case if we try to extend a selection that is a loop but not
                # the current loop
                for edge in loops[0]:
                    bm.edges[edge].select_set(False)
                old_selection = SavedSelectionState.from_context(context)
                for edge in loops[0]:
                    bm.edges[edge].select_set(True)
                next_loop = frozenset()
            else:
                old_selection = SavedSelectionState.from_context(context)
        else:
            if self.extend:
                loops.append(frozenset())
            else:
                old_selection = None
            next_loop = loops[(loops.index(current_loop) + 1) % len(loops)]
        current_loop = next_loop
        if old_selection:
            old_selection.restore(context)
        else:
            bpy.ops.mesh.select_all(action='DESELECT')
        for edge in next_loop:
            bm.edges[edge].select = True
        bm.select_flush_mode()
        return {"FINISHED"}
