# edgy

Edgy is a Blender add-on which adds a small number of operators to make it easy to select the edges and edge loops that you are most likely to want.

By default it provides drop-in replacements that override the default loop selection (i.e. ALT-LEFT and ALT-SHIFT-LEFT) and select more/less (i.e. CTRL-NUMPAD-PLUS and CTRL-NUMPAD-MINUS), but these default bindings can be overridden in preferences. It also provides a "Close Loop" operator which is not bound by default, but is added to the mesh selection menu.

## Operators

### Loop selection
The edgy_select_loop operator functions identically to select_loop when you first click on an edge. However, further clicks will iterate through a selection of possible closed loops and eventually return to the original selection. The algorithm, though imperfect, tries to create "clean loops" that go through as few "poles" as possible. It also (mostly successfully) attempts to deal robustly with mesh boundaries and other non-manifold geometry.

The operator has two REDO options: 
 * **Extend/Toggle Selection**: chooses whether modify the existing selection by removing the "current" loop or extending with a new loop. If false, it only deals with loops that pass through the selected edge. This option is automatically enabled when you use the "ALT-SHIFT-LEFT" keyboard shortcut.
 * **Mode**: Allows you to return to the default behavior of Blender should the standard "Smart" behavior cause problems.

### Growing and shrinking selections
The edgy_resize_selection operator functions almost identically to the standard "Select More" and "Select Less" operators when you are in face mode, or when you do not have closed loops selected. However, when you are in edge- or vertex-selection mode and choose "Automatic", the operator will attempt to expand or contract any closed loops rather than adding face selections. This uses a variety of heuristics to identify loop selections and face-oriented "region" selections, and to choose reasonable defaults when presented open edges or vertices.

You can choose the following "modes" of operation:
* **Automatic**: Tries to be smart about how to grow or shrink the selection based upon your current select-mode. It never completely removes all selections.
* **Boundaries**: Tries to create larger or smaller edge boundary loop(s) regardless of what select mode is active. In the case of trying to shrink a dense "region" selection, this will do nothing.
* **Faces**: This will grow and shrink completely selected faces in a manner very similar to the default blender operators, but it will refuse to clear all selections.
* **Blender default (Faces)**: This exactly duplicates the More/Less operators with "Use Face Steps" unchecked.
* **Blender default (Edges)**: This exactly duplicates the More/Less operators with "Use Face Steps" checked.

Regardless of mode, the operator will always report what it did or why it did not do as requested.

### Closing loops
The edgy_close_loop operator attempts to turn the current (presumably unclosed) edge selection into a closed loop. It uses an algorithm that chooses the shorted path (by number of edges) while preferring those that move in mostly "straight" lines. This typically results in a "clean" loop that matches what you expect.

It is not bound to any keyboard shortcut by default but does appear on the Mesh Select menu.

## License
This addon and all of the code is licensed under CC0 (Public Domain). You may freely use or modify it for any purpose.
The original code was written by GadFlight and can be found at [his GitHub repository](https://github.com/GadFlight).
