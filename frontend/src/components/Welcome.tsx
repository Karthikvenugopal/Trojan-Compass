import { Compass, Sparkles } from 'lucide-react';

const starters = [
  "I'm not sure where to start.",
  'I have an interest to explore.',
  'I know what I want to do.',
];

interface WelcomeProps {
  onStarter: (text: string) => void;
  disabled: boolean;
}

export function Welcome({ onStarter, disabled }: WelcomeProps) {
  return (
    <section className="welcome" aria-labelledby="welcome-heading">
      <div className="welcome-icon"><Compass size={24} aria-hidden="true" /></div>
      <span className="eyebrow"><Sparkles size={13} aria-hidden="true" /> Your next step starts here</span>
      <h2 id="welcome-heading">Find your direction at USC.</h2>
      <p>Explore a new interest or turn a clear goal into useful USC courses and events.</p>
      <div className="starter-list" aria-label="Conversation starters">
        {starters.map((starter) => <button key={starter} type="button" disabled={disabled} onClick={() => onStarter(starter)}>{starter}</button>)}
      </div>
    </section>
  );
}
