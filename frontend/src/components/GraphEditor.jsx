import React, { useCallback, useMemo, useRef } from "react";
import {
  ReactFlow, Background, Controls, Handle, Position,
  applyNodeChanges, applyEdgeChanges, addEdge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useApp } from "../App.jsx";

function AgentNode({ data, selected }) {
  return (
    <div className={"rf-node-agent" + (selected ? " selected" : "")}>
      <Handle type="target" position={Position.Left} />
      <div>
        {data.label}
        <span className="sub">{data.model || ""}</span>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
function StartNode() {
  return (
    <div className="rf-node-terminal start">
      START
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
function EndNode() {
  return (
    <div className="rf-node-terminal">
      <Handle type="target" position={Position.Left} />
      END
    </div>
  );
}
const nodeTypes = { agent: AgentNode, start: StartNode, end: EndNode };

/* graph def {nodes:[{id,agent}], edges:[{source,target}], positions:{id:{x,y}}}
   <-> React Flow state, agents = team agent list for labels/adding. */
export default function GraphEditor({ agents, graph, onChange }) {
  const { theme } = useApp();
  const counter = useRef(0);
  const agentByName = useMemo(
    () => Object.fromEntries((agents || []).map((a) => [a.name, a])), [agents]);

  const rfNodes = useMemo(() => {
    const pos = graph.positions || {};
    const defs = graph.nodes || [];
    const auto = (i, n) => ({ x: 200 + (i % 3) * 230, y: 60 + Math.floor(i / 3) * 110 });
    return [
      { id: "start", type: "start", position: pos.start || { x: 10, y: 150 },
        data: {}, deletable: false },
      ...defs.map((n, i) => ({
        id: n.id, type: "agent",
        position: pos[n.id] || auto(i, defs.length),
        data: { label: n.agent, model: agentByName[n.agent]?.model },
      })),
      { id: "end", type: "end", position: pos.end || { x: 760, y: 150 },
        data: {}, deletable: false },
    ];
  }, [graph, agentByName]);

  const rfEdges = useMemo(() => (graph.edges || []).map((e, i) => ({
    id: `e${i}-${e.source}-${e.target}`, source: e.source, target: e.target,
    animated: true, style: { strokeWidth: 1.8 },
  })), [graph]);

  const commit = useCallback((nodes, edges) => {
    const positions = {};
    for (const n of nodes) positions[n.id] = { x: Math.round(n.position.x), y: Math.round(n.position.y) };
    onChange({
      nodes: nodes.filter((n) => n.type === "agent")
        .map((n) => ({ id: n.id, agent: n.data.label })),
      edges: edges.map((e) => ({ source: e.source, target: e.target })),
      positions,
    });
  }, [onChange]);

  const onNodesChange = useCallback((changes) => {
    commit(applyNodeChanges(changes, rfNodes), rfEdges);
  }, [rfNodes, rfEdges, commit]);

  const onEdgesChange = useCallback((changes) => {
    commit(rfNodes, applyEdgeChanges(changes, rfEdges));
  }, [rfNodes, rfEdges, commit]);

  const onConnect = useCallback((conn) => {
    if (conn.source === conn.target) return;
    commit(rfNodes, addEdge({ ...conn, animated: true }, rfEdges));
  }, [rfNodes, rfEdges, commit]);

  const addNode = (agentName) => {
    counter.current += 1;
    let id = `n${Date.now() % 100000}_${counter.current}`;
    const nodes = [...rfNodes];
    nodes.splice(nodes.length - 1, 0, {
      id, type: "agent",
      position: { x: 220 + (rfNodes.length - 2) * 40, y: 40 + (rfNodes.length - 2) * 50 },
      data: { label: agentName, model: agentByName[agentName]?.model },
    });
    commit(nodes, rfEdges);
  };

  return (
    <div>
      <div className="graph-toolbar">
        <select id="add-agent-node" defaultValue="">
          <option value="" disabled>Add a node for agent…</option>
          {(agents || []).filter((a) => a.name).map((a) => (
            <option key={a.name} value={a.name}>{a.name}</option>
          ))}
        </select>
        <button type="button" className="btn sm" onClick={() => {
          const sel = document.getElementById("add-agent-node");
          if (sel.value) { addNode(sel.value); sel.value = ""; }
        }}>＋ Add node</button>
        <span className="graph-hint">
          Drag from a node's right handle to another node's left handle to connect ·
          select an edge/node and press Delete to remove
        </span>
      </div>
      <div className="graph-wrap">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
          colorMode={theme || "light"}
          proOptions={{ hideAttribution: true }}
          deleteKeyCode={["Delete", "Backspace"]}
        >
          <Background gap={18} size={1.2} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div className="graph-hint">
        Branches that fan out from the same node run in parallel (when the parallel
        toggle is on); a node with several incoming edges waits for all of them.
      </div>
    </div>
  );
}
