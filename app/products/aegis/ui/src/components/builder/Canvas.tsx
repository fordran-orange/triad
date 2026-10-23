import {
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import { canConnect, inputPorts, looseBlocks, outputPorts, type Block, type BlockSettings, type SideGraph } from '../../builder/graph';
import { NODE_TYPES, type BlockNode } from './Blocks';
import { DRAG_TYPE, newBlock, type PaletteItem } from './Palette';

const FIXED = new Set(['entry', 'exit', 'price']);

function nextWireId(graph: SideGraph): string {
  const used = graph.wires.map((w) => Number(w.id.replace(/^w/, ''))).filter(Number.isFinite);
  return `w${1 + Math.max(0, ...used)}`;
}

function toNodes(graph: SideGraph, readOnly: boolean, onSettings: (id: string, patch: BlockSettings) => void, current: BlockNode[]): BlockNode[] {
  const loose = looseBlocks(graph);
  const before = new Map(current.map((n) => [n.id, n]));
  return graph.blocks.map((block) => ({
    // React Flow keeps a node's measured size on the node; a redraw must carry it, or the node
    // stays hidden and its wires are never drawn.
    ...(before.get(block.id)?.measured ? { measured: before.get(block.id)!.measured } : {}),
    id: block.id,
    type: block.type,
    position: { x: block.x, y: block.y },
    selected: !!before.get(block.id)?.selected,
    deletable: !readOnly && !FIXED.has(block.id),
    data: {
      block,
      inputs: inputPorts(block, graph),
      outputs: outputPorts(block),
      wired: graph.wires.filter((w) => w.to === block.id).map((w) => w.toPort),
      loose: loose.has(block.id),
      readOnly,
      onSettings,
    },
  }));
}

function toEdges(graph: SideGraph, selected: Set<string>): Edge[] {
  return graph.wires.map((w) => ({ id: w.id, source: w.from, sourceHandle: w.fromPort, target: w.to, targetHandle: w.toPort, selected: selected.has(w.id), deletable: true }));
}

/** The side's graph on a React Flow canvas (spec §4.6). Every change goes to `onChange` as a new
 * graph; `positionsOnly` marks a move, which changes no rule. A refused wire goes to `onRefused`. */
export function Canvas({
  graph,
  readOnly,
  onChange,
  onRefused,
}: {
  graph: SideGraph;
  readOnly: boolean;
  onChange: (graph: SideGraph, positionsOnly?: boolean) => void;
  onRefused: (reason: string) => void;
}) {
  const flow = useReactFlow();
  // Blocks call the latest graph's settings change through a stable function, so a redraw is
  // needed only when the graph itself changes.
  const latest = useRef({ graph, onChange });
  latest.current = { graph, onChange };
  const onSettings = useCallback((id: string, patch: BlockSettings) => {
    const { graph: now, onChange: change } = latest.current;
    const blocks = now.blocks.map((b): Block => (b.id === id ? { ...b, settings: { ...b.settings, ...patch, badge: undefined } } : b));
    change({ ...now, blocks });
  }, []);
  const [nodes, setNodes] = useState<BlockNode[]>(() => toNodes(graph, readOnly, onSettings, []));
  const [edges, setEdges] = useState<Edge[]>(() => toEdges(graph, new Set()));

  // The graph is the truth: redraw on every change from outside, keeping what is selected.
  useEffect(() => {
    setNodes((current) => toNodes(graph, readOnly, onSettings, current));
    setEdges((current) => toEdges(graph, new Set(current.filter((e) => e.selected).map((e) => e.id))));
  }, [graph, readOnly, onSettings]);

  const removeBlocks = useCallback(
    (ids: string[]) => {
      const gone = new Set(ids.filter((id) => !FIXED.has(id)));
      if (gone.size === 0) return;
      onChange({ blocks: graph.blocks.filter((b) => !gone.has(b.id)), wires: graph.wires.filter((w) => !gone.has(w.from) && !gone.has(w.to)) });
    },
    [graph, onChange],
  );
  const removeWires = useCallback(
    (ids: string[]) => {
      const gone = new Set(ids);
      onChange({ ...graph, wires: graph.wires.filter((w) => !gone.has(w.id)) });
    },
    [graph, onChange],
  );

  const onNodesChange = useCallback((changes: NodeChange<BlockNode>[]) => {
    // Removals arrive through onNodesDelete, which edits the graph; everything else is local.
    setNodes((current) => applyNodeChanges(changes.filter((c) => c.type !== 'remove'), current));
  }, []);
  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setEdges((current) => applyEdgeChanges(changes.filter((c) => c.type !== 'remove'), current));
  }, []);

  const onConnect = useCallback(
    (connection: Connection) => {
      const wire = { from: connection.source, fromPort: connection.sourceHandle ?? '', to: connection.target, toPort: connection.targetHandle ?? '' };
      const reason = canConnect(graph, wire);
      if (reason) onRefused(reason);
      else onChange({ ...graph, wires: [...graph.wires, { id: nextWireId(graph), ...wire }] });
    },
    [graph, onChange, onRefused],
  );

  const onNodeDragStop = useCallback(
    (_event: unknown, _node: BlockNode, moved: BlockNode[]) => {
      const places = new Map(moved.map((n) => [n.id, n.position]));
      const blocks = graph.blocks.map((b) => {
        const place = places.get(b.id);
        return place ? { ...b, x: Math.round(place.x), y: Math.round(place.y) } : b;
      });
      onChange({ ...graph, blocks }, true);
    },
    [graph, onChange],
  );

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      const raw = event.dataTransfer.getData(DRAG_TYPE);
      if (!raw || readOnly) return;
      const item = JSON.parse(raw) as PaletteItem;
      const at = flow.screenToFlowPosition({ x: event.clientX, y: event.clientY });
      onChange({ ...graph, blocks: [...graph.blocks, newBlock(graph, item, at.x, at.y)] });
    },
    [flow, graph, onChange, readOnly],
  );

  const deleteKeys = useMemo(() => (readOnly ? null : ['Delete', 'Backspace']), [readOnly]);

  return (
    <div className="builder-canvas" id="builder-canvas" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeDragStop={onNodeDragStop}
        onNodesDelete={(deleted) => removeBlocks(deleted.map((n) => n.id))}
        onEdgesDelete={(deleted) => removeWires(deleted.map((e) => e.id))}
        onNodeContextMenu={(event, node) => {
          event.preventDefault();
          if (!readOnly) removeBlocks([node.id]);
        }}
        onEdgeContextMenu={(event, edge) => {
          event.preventDefault();
          if (!readOnly) removeWires([edge.id]);
        }}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        deleteKeyCode={deleteKeys}
        colorMode="dark"
        fitView
        minZoom={0.2}
      >
        <Background gap={20} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable />
      </ReactFlow>
    </div>
  );
}
