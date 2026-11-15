import { useMemo, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import type { GraphEdge, GraphNode, GraphNodeKind, PathwayGraph } from '../types';

const COLUMNS: { title: string; kinds: GraphNodeKind[] }[] = [
  { title: 'Your interest', kinds: ['interest'] },
  { title: 'Skills', kinds: ['skill'] },
  { title: 'Courses', kinds: ['course'] },
  { title: 'People & events', kinds: ['professor', 'event'] },
];
const KIND_LABEL: Record<GraphNodeKind, string> = {
  interest: 'Interest', skill: 'Skill', course: 'Course', professor: 'Professor', event: 'Event',
};
const WIDTH = 1060;
const NODE_W = 226;
const NODE_H = 56;
const GAP = 14;
const TOP = 44;
const COLUMN_X = [14, 286, 558, 820];

interface Placed { node: GraphNode; x: number; y: number; column: number }

function layout(graph: PathwayGraph) {
  const columns = COLUMNS.map(column => graph.nodes.filter(node => column.kinds.includes(node.kind)));
  // Prerequisites sit just above the course they unlock.
  const courses = columns[2];
  const order = new Map(courses.map((node, index) => [node.id, index * 2]));
  for (const edge of graph.edges) {
    if (order.has(edge.source) && order.has(edge.target) && edge.label.startsWith('prerequisite')) {
      order.set(edge.source, (order.get(edge.target) ?? 0) - 1);
    }
  }
  columns[2] = [...courses].sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0));
  const tallest = Math.max(1, ...columns.map(column => column.length));
  const height = TOP + tallest * (NODE_H + GAP) + 8;
  const placed = new Map<string, Placed>();
  columns.forEach((nodes, column) => {
    const offset = TOP + ((tallest - nodes.length) * (NODE_H + GAP)) / 2;
    nodes.forEach((node, row) => placed.set(node.id, { node, column, x: COLUMN_X[column], y: offset + row * (NODE_H + GAP) }));
  });
  return { placed, height };
}

/** Two lines of plain SVG text (no foreignObject, so it renders the same everywhere). */
function wrap(label: string, width = 33): string[] {
  const lines: string[] = [];
  let current = '';
  for (const word of label.split(' ')) {
    if ((current + ' ' + word).trim().length <= width) { current = (current + ' ' + word).trim(); continue; }
    if (current) lines.push(current);
    current = word;
  }
  if (current) lines.push(current);
  if (lines.length <= 2) return lines;
  const second = lines[1].length > width - 1 ? lines[1].slice(0, width - 1) : lines[1];
  return [lines[0], second + '…'];
}

function edgePath(from: Placed, to: Placed): string {
  const y1 = from.y + NODE_H / 2;
  const y2 = to.y + NODE_H / 2;
  if (from.column === to.column) {
    const x = from.x;
    const bend = 26 + Math.min(40, Math.abs(y2 - y1) / 6);
    return `M ${x} ${y1} C ${x - bend} ${y1}, ${x - bend} ${y2}, ${x} ${y2}`;
  }
  const x1 = from.x + NODE_W;
  const x2 = to.x;
  const mid = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`;
}

/** Everything upstream and downstream of a node: the whole path through it. */
function pathThrough(id: string, edges: GraphEdge[]): Set<string> {
  const seen = new Set([id]);
  for (const [from, to] of [['source', 'target'], ['target', 'source']] as const) {
    const queue = [id];
    while (queue.length) {
      const current = queue.pop() as string;
      for (const edge of edges) {
        if (edge[from] === current && !seen.has(edge[to])) { seen.add(edge[to]); queue.push(edge[to]); }
      }
    }
  }
  return seen;
}

export function GraphView({ graph }: { graph: PathwayGraph }) {
  const { placed, height } = useMemo(() => layout(graph), [graph]);
  const [active, setActive] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const focusId = active ?? selected;
  const lit = useMemo(() => (focusId ? pathThrough(focusId, graph.edges) : null), [focusId, graph.edges]);
  const chosen = selected ? placed.get(selected)?.node ?? null : null;
  const links = chosen ? graph.edges.filter(edge => edge.source === chosen.id || edge.target === chosen.id) : [];
  const label = (id: string) => placed.get(id)?.node.label ?? id;

  return (
    <div className="graph-view">
      <svg viewBox={`0 0 ${WIDTH} ${height}`} role="group" aria-label="Knowledge graph of your path. Select a node for details.">
        {COLUMNS.map((column, index) => (
          <text key={column.title} className="graph-column-title" x={COLUMN_X[index] + NODE_W / 2} y={22} textAnchor="middle">{column.title}</text>
        ))}
        <g>
          {graph.edges.map(edge => {
            const from = placed.get(edge.source);
            const to = placed.get(edge.target);
            if (!from || !to) return null;
            const on = lit ? lit.has(edge.source) && lit.has(edge.target) : false;
            return (
              <path key={`${edge.source}>${edge.target}`} d={edgePath(from, to)}
                className={`graph-edge kind-${from.node.kind}${edge.inferred ? ' inferred' : ''}${on ? ' on' : lit ? ' off' : ''}`} />
            );
          })}
        </g>
        {[...placed.values()].map(({ node, x, y }) => {
          const dim = lit ? !lit.has(node.id) : false;
          return (
            <g key={node.id} transform={`translate(${x} ${y})`} tabIndex={0} role="button"
              aria-label={`${KIND_LABEL[node.kind]}: ${node.label}`} aria-pressed={selected === node.id}
              className={`graph-node kind-${node.kind} state-${node.state ?? 'none'}${dim ? ' dim' : ''}${selected === node.id ? ' selected' : ''}`}
              onMouseEnter={() => setActive(node.id)} onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(node.id)} onBlur={() => setActive(null)}
              onClick={() => setSelected(selected === node.id ? null : node.id)}
              onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelected(selected === node.id ? null : node.id); } }}>
              <rect width={NODE_W} height={NODE_H} rx={11} />
              <text className="graph-node-kind" x={11} y={17}>{node.state === 'prerequisite' ? 'Prerequisite' : node.state === 'known' ? 'You know this' : KIND_LABEL[node.kind]}</text>
              {wrap(node.label).map((line, index) => <text key={index} className="graph-node-label" x={11} y={33 + index * 14}>{line}</text>)}
            </g>
          );
        })}
      </svg>
      <p className="graph-legend"><span className="legend-line" /> stated in an official source <span className="legend-line inferred" /> inferred link · hover or select a node to trace its path</p>
      {chosen && (
        <div className="graph-detail" role="status">
          <b>{KIND_LABEL[chosen.kind]}: {chosen.label}</b>
          {chosen.detail && <p>{chosen.detail}</p>}
          <ul>{links.map(edge => (
            <li key={`${edge.source}>${edge.target}`}>{label(edge.source)} <i>{edge.label}</i> {label(edge.target)}{edge.inferred ? ' (inferred)' : ''}</li>
          ))}</ul>
          {chosen.url && <a href={chosen.url} target="_blank" rel="noopener noreferrer">Open source <ExternalLink size={12} aria-hidden="true" /></a>}
        </div>
      )}
    </div>
  );
}

/** The same graph as nested headings and lists, for screen readers and small screens. */
export function GraphList({ graph }: { graph: PathwayGraph }) {
  const byId = new Map(graph.nodes.map(node => [node.id, node]));
  const sections: { title: string; kinds: GraphNodeKind[] }[] = [
    { title: 'Skills', kinds: ['skill'] },
    { title: 'Courses', kinds: ['course'] },
    { title: 'People', kinds: ['professor'] },
    { title: 'Events', kinds: ['event'] },
  ];
  return (
    <div className="graph-list">
      {sections.map(section => {
        const nodes = graph.nodes.filter(node => section.kinds.includes(node.kind));
        if (!nodes.length) return null;
        return (
          <section key={section.title} aria-label={section.title}>
            <h4>{section.title}</h4>
            <ul>
              {nodes.map(node => {
                const related = graph.edges.filter(edge => edge.source === node.id || edge.target === node.id);
                return (
                  <li key={node.id}>
                    <b>{node.url ? <a href={node.url} target="_blank" rel="noopener noreferrer">{node.label}</a> : node.label}</b>
                    {node.state === 'prerequisite' && <span className="list-tag">prerequisite</span>}
                    {node.state === 'known' && <span className="list-tag">you know this</span>}
                    {node.detail && <p>{node.detail}</p>}
                    <p className="list-links">{related.map(edge => edge.source === node.id
                      ? `${edge.label} ${byId.get(edge.target)?.label ?? ''}`
                      : `${byId.get(edge.source)?.label ?? ''} ${edge.label} this`).join(' · ')}</p>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
