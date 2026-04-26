"use client";

import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  type Edge,
  type Node,
} from "reactflow";
import { nodeTypes } from "./node-card";

const baseNodes: Node[] = [
  { id: "patient",        type: "agent", position: { x: 400, y: 10  }, data: { role: "patient",  title: "Patient" } },
  { id: "swarm-intake",   type: "agent", position: { x: 400, y: 110 }, data: { role: "intake",   title: "swarm-intake",   subtitle: "Triage & routing" } },
  { id: "swarm-profiler", type: "agent", position: { x: 100, y: 240 }, data: { role: "profiler", title: "swarm-profiler", subtitle: "Patient profile" } },
  { id: "swarm-finder",   type: "agent", position: { x: 400, y: 240 }, data: { role: "finder",   title: "swarm-finder",   subtitle: "Clinic discovery" } },
  { id: "swarm-matcher",  type: "agent", position: { x: 700, y: 240 }, data: { role: "matcher",  title: "swarm-matcher",  subtitle: "Rank candidates" } },
  { id: "swarm-caller",   type: "agent", position: { x: 400, y: 380 }, data: { role: "caller",   title: "swarm-caller",   subtitle: "Voice booking" } },
  { id: "clinic",         type: "agent", position: { x: 400, y: 510 }, data: { role: "clinic",   title: "Clinic" } },
];

interface GraphCanvasProps {
  edges: Edge[];
  candidateNodes: Node[];
}

export function GraphCanvas({ edges, candidateNodes }: GraphCanvasProps) {
  const nodes = useMemo(() => [...baseNodes, ...candidateNodes], [candidateNodes]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      proOptions={{ hideAttribution: true }}
      style={{ backgroundColor: "#F5F7FA" }}
    >
      <Background color="#E5E7EB" gap={28} size={1.5} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export { baseNodes };
