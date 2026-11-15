import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import type { Pathway } from '../types';
import { PathwayPanel, roadmapMarkdown } from './PathwayPanel';

const pathway: Pathway = {
  graph: {
    nodes: [
      { id: 'interest', kind: 'interest', label: 'Search and RAG', detail: null, url: null, state: null },
      { id: 'skill:ir', kind: 'skill', label: 'Information retrieval', detail: 'Powers RAG.', url: null, state: 'to_learn' },
      { id: 'course:csci572', kind: 'course', label: 'CSCI 572: Information Retrieval', detail: 'Spring 2027.', url: 'https://classes.usc.edu/', state: 'recommended' },
      { id: 'course:csci270', kind: 'course', label: 'CSCI 270: Algorithms', detail: null, url: null, state: 'prerequisite' },
      { id: 'prof:ada', kind: 'professor', label: 'Ada Lovelace', detail: 'Teaches CSCI 572.', url: null, state: 'related' },
    ],
    edges: [
      { source: 'interest', target: 'skill:ir', label: 'needs', inferred: true },
      { source: 'skill:ir', target: 'course:csci572', label: 'taught in', inferred: true },
      { source: 'course:csci270', target: 'course:csci572', label: 'prerequisite for', inferred: false },
      { source: 'course:csci572', target: 'prof:ada', label: 'taught by', inferred: false },
    ],
  },
  roadmap: {
    focus: 'Search and RAG',
    known: ['Python (known)'],
    to_learn: [{ name: 'Information retrieval', why: 'It powers RAG.' }],
    courses: [{ code: 'CSCI 572', title: 'Information Retrieval', term: 'Spring 2027', note: 'Best match', url: 'https://classes.usc.edu/' }],
    people: [{ name: 'Ada Lovelace', role: 'Teaches CSCI 572', research: 'Search', url: null }],
    events: [],
    next_step: { title: 'Start with CSCI 270: Algorithms', detail: 'It is a prerequisite for CSCI 572.', url: null, then: ['Then take CSCI 572.'] },
  },
};

it('shows the graph, an accessible list view and the roadmap with its next step', async () => {
  render(<PathwayPanel pathway={pathway} />);
  expect(screen.getByRole('button', { name: 'Course: CSCI 572: Information Retrieval' })).toBeInTheDocument();
  expect(screen.getByRole('note', { name: 'Your next step' })).toHaveTextContent('Start with CSCI 270: Algorithms');
  expect(screen.getByRole('heading', { name: 'What to learn' })).toBeInTheDocument();

  await userEvent.click(screen.getByRole('button', { name: 'Skill: Information retrieval' }));
  expect(screen.getByRole('status')).toHaveTextContent('Information retrieval taught in CSCI 572: Information Retrieval (inferred)');

  await userEvent.click(screen.getByRole('button', { name: 'List' }));
  expect(screen.getByRole('region', { name: 'Courses' })).toHaveTextContent('prerequisite');
  expect(screen.getByRole('link', { name: 'CSCI 572: Information Retrieval' })).toHaveAttribute('href', 'https://classes.usc.edu/');
});

it('exports the roadmap as markdown with the next step first', () => {
  const markdown = roadmapMarkdown(pathway.roadmap!);
  expect(markdown).toContain('# My USC roadmap: Search and RAG');
  expect(markdown.indexOf('## My next step')).toBeLessThan(markdown.indexOf('## What I know'));
  expect(markdown).toContain('1. **CSCI 572: Information Retrieval** (Spring 2027)');
});
