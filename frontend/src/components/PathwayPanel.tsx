import { useState } from 'react';
import { ArrowRight, Download, List, Map as MapIcon, Printer, Waypoints } from 'lucide-react';
import type { Pathway, Roadmap } from '../types';
import { GraphList, GraphView } from './GraphView';

/** Plain-text roadmap a student can keep; built in the browser, nothing is uploaded. */
export function roadmapMarkdown(roadmap: Roadmap): string {
  const lines = [`# My USC roadmap: ${roadmap.focus}`, '', '_Made with Trojan Compass. Confirm seats, prerequisites and dates on the linked official pages._', ''];
  lines.push('## What I know', ...(roadmap.known.length ? roadmap.known.map(item => `- ${item}`) : ['- Starting fresh']), '');
  lines.push('## What to learn', ...roadmap.to_learn.map(skill => `- **${skill.name}**${skill.why ? `: ${skill.why}` : ''}`), '');
  lines.push('## Courses to explore', ...roadmap.courses.map((course, index) =>
    `${index + 1}. **${course.code}: ${course.title}**${course.term ? ` (${course.term})` : ''}${course.note ? `. ${course.note}` : ''}${course.url ? `. ${course.url}` : ''}`), '');
  if (roadmap.people.length) {
    lines.push('## People and research to explore', ...roadmap.people.map(person =>
      `- **${person.name}**${person.role ? `, ${person.role}` : ''}${person.research ? `. Research: ${person.research}` : ''}${person.url ? `. ${person.url}` : ''}`), '');
  }
  if (roadmap.events.length) {
    lines.push('## Events', ...roadmap.events.map(event => `- ${event.title}${event.when ? ` (${event.when})` : ''}`), '');
  }
  return lines.join('\n');
}

function download(roadmap: Roadmap) {
  const blob = new Blob([roadmapMarkdown(roadmap)], { type: 'text/markdown' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = 'my-usc-roadmap.md';
  link.click();
  URL.revokeObjectURL(link.href);
}

export function PathwayPanel({ pathway }: { pathway: Pathway }) {
  const [view, setView] = useState<'graph' | 'list'>('graph');
  const { graph, roadmap } = pathway;
  return (
    <section className="pathway-panel" aria-label="Your path">
      {graph && (
        <div className="pathway-block">
          <header className="pathway-header">
            <h2><Waypoints size={18} aria-hidden="true" /> How your interest connects at USC</h2>
            <div className="view-toggle" role="group" aria-label="Choose a view">
              <button type="button" aria-pressed={view === 'graph'} onClick={() => setView('graph')}><MapIcon size={14} aria-hidden="true" /> Graph</button>
              <button type="button" aria-pressed={view === 'list'} onClick={() => setView('list')}><List size={14} aria-hidden="true" /> List</button>
            </div>
          </header>
          {view === 'graph' ? <GraphView graph={graph} /> : <GraphList graph={graph} />}
        </div>
      )}
      {roadmap && (
        <div className="pathway-block roadmap" id="roadmap">
          <header className="pathway-header">
            <h2>Your roadmap: {roadmap.focus}</h2>
            <div className="roadmap-actions">
              <button type="button" onClick={() => download(roadmap)}><Download size={14} aria-hidden="true" /> Save roadmap</button>
              <button type="button" onClick={() => window.print()}><Printer size={14} aria-hidden="true" /> Print</button>
            </div>
          </header>
          <div className="roadmap-columns">
            <div className="roadmap-column">
              <h3>What I know</h3>
              <ul>{roadmap.known.length ? roadmap.known.map(item => <li key={item}>{item}</li>) : <li className="muted">Starting fresh. That is fine.</li>}</ul>
            </div>
            <ArrowRight className="roadmap-arrow" size={22} aria-hidden="true" />
            <div className="roadmap-column">
              <h3>What to learn</h3>
              <ul>{roadmap.to_learn.map(skill => <li key={skill.name}><b>{skill.name}</b>{skill.why && <span>{skill.why}</span>}</li>)}</ul>
            </div>
            <ArrowRight className="roadmap-arrow" size={22} aria-hidden="true" />
            <div className="roadmap-column wide">
              <h3>Courses & research to explore</h3>
              <ol>{roadmap.courses.map(course => (
                <li key={course.code}>
                  <b>{course.url ? <a href={course.url} target="_blank" rel="noopener noreferrer">{course.code}</a> : course.code}: {course.title}</b>
                  <span>{[course.term, course.note].filter(Boolean).join(' · ')}</span>
                </li>
              ))}</ol>
              {roadmap.people.length > 0 && (
                <>
                  <h4>People & research</h4>
                  <ul>{roadmap.people.map(person => (
                    <li key={person.name}>
                      <b>{person.url ? <a href={person.url} target="_blank" rel="noopener noreferrer">{person.name}</a> : person.name}</b>
                      <span>{[person.role, person.research ? `Research: ${person.research}` : null].filter(Boolean).join(' · ')}</span>
                    </li>
                  ))}</ul>
                </>
              )}
              {roadmap.events.length > 0 && (
                <>
                  <h4>Events</h4>
                  <ul>{roadmap.events.map(event => <li key={event.title}><b>{event.title}</b><span>{event.when}</span></li>)}</ul>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
