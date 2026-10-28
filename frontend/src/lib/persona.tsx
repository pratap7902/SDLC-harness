// "Viewing as": which human the UI acts as. In AUTH_MODE=header the service trusts the
// X-Actor header, so this choice is who every request (and every answer, ruling, approval)
// is recorded as. The choice survives reloads (localStorage), falling back to the first DRI.

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { Person } from '../api';
import { setActor, useJson } from './api';

const KEY = 'srs.viewing_as';

function saved(): string {
  try {
    return localStorage.getItem(KEY) || '';
  } catch {
    return '';
  }
}

interface PersonaState {
  persona: string;
  setPersona: (p: string) => void;
  people: Person[];
  peopleError: string;
}

const PersonaContext = createContext<PersonaState | null>(null);

export function PersonaProvider({ children }: { children: React.ReactNode }) {
  const [persona, setPersonaState] = useState(() => {
    const p = saved();
    setActor(p);
    return p;
  });
  const people = useJson<Person[]>('/api/people');
  const list = useMemo(() => (people.kind === 'ready' ? people.data : []), [people]);

  const setPersona = useCallback((p: string) => {
    setActor(p);
    setPersonaState(p);
    try {
      localStorage.setItem(KEY, p);
    } catch {
      /* private window: the choice lasts this tab */
    }
  }, []);

  // Nobody picked yet (or the saved person is gone after a re-seed): whoever has the most
  // waiting on them, else the first DRI.
  useEffect(() => {
    if (people.kind !== 'ready' || !list.length) return;
    if (persona && list.some((p) => p.person === persona)) return;
    const busiest = [...list].sort((a, b) => b.inbox - a.inbox)[0];
    const dri = list.find((p) => p.roles.some((r) => r.role === 'dri'));
    setPersona((busiest && busiest.inbox ? busiest : dri || list[0]).person);
  }, [people.kind, list, persona, setPersona]);

  const value = useMemo(
    () => ({ persona, setPersona, people: list, peopleError: people.kind === 'error' ? people.message : '' }),
    [persona, setPersona, list, people],
  );
  return <PersonaContext.Provider value={value}>{children}</PersonaContext.Provider>;
}

export function usePersona(): PersonaState {
  const v = useContext(PersonaContext);
  if (!v) throw new Error('usePersona outside PersonaProvider');
  return v;
}
