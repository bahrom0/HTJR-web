import type { LineBlock } from './model';

export const DRAFTS_STORAGE_KEY = 'htr_editor_drafts';

export const INITIAL_TAJIK_LINES: LineBlock[] = [
  {
    id: 'line-1',
    lineNumber: 1,
    rawText: 'Ба номи Худованди бахшандаи меҳрубон',
    editedText: 'Ба номи Худованди бахшандаи меҳрубон',
    confidence: 0.98,
    status: 'verified',
    box: { x: 5, y: 8, width: 90, height: 12 },
  },
  {
    id: 'line-2',
    lineNumber: 2,
    rawText: 'Саҳифаи 1 аз рукописи 1928 соли',
    editedText: 'Саҳифаи 1 аз рукописи 1928 соли',
    confidence: 0.92,
    status: 'unverified',
    box: { x: 5, y: 24, width: 90, height: 12 },
  },
  {
    id: 'line-3',
    lineNumber: 3,
    rawText: 'Дастхати таърихии адабиёти классикии тоҷик',
    editedText: 'Дастхати таърихии адабиёти классикии тоҷик',
    confidence: 0.89,
    status: 'unverified',
    box: { x: 5, y: 40, width: 90, height: 12 },
  },
  {
    id: 'line-4',
    lineNumber: 4,
    rawText: 'Транскрипсия ва тасҳеҳи матни дастии қадим',
    editedText: 'Транскрипсия ва тасҳеҳи матни дастии қадим',
    confidence: 0.95,
    status: 'verified',
    box: { x: 5, y: 56, width: 90, height: 12 },
  },
  {
    id: 'line-5',
    lineNumber: 5,
    rawText: 'Омӯзиш ва баррасии осори ниёгон дар озмоишгоҳ',
    editedText: 'Омӯзиш ва баррасии осори ниёгон дар озмоишгоҳ',
    confidence: 0.84,
    status: 'unverified',
    box: { x: 5, y: 72, width: 90, height: 12 },
  },
];

export function loadEditorState(docOrJobId?: string): LineBlock[] {
  try {
    const storageKey = docOrJobId ? `${DRAFTS_STORAGE_KEY}_${docOrJobId}` : DRAFTS_STORAGE_KEY;
    const raw = localStorage.getItem(storageKey);
    if (!raw) {
      const defaultRaw = localStorage.getItem(DRAFTS_STORAGE_KEY);
      if (defaultRaw) {
        return JSON.parse(defaultRaw);
      }
      return INITIAL_TAJIK_LINES;
    }
    return JSON.parse(raw);
  } catch (err) {
    console.error('Failed to load editor state from localStorage:', err);
    return INITIAL_TAJIK_LINES;
  }
}

export function saveEditorState(blocks: LineBlock[], docOrJobId?: string): boolean {
  try {
    const json = JSON.stringify(blocks);
    localStorage.setItem(DRAFTS_STORAGE_KEY, json);
    if (docOrJobId) {
      localStorage.setItem(`${DRAFTS_STORAGE_KEY}_${docOrJobId}`, json);
    }
    return true;
  } catch (err) {
    console.error('Failed to save editor state to localStorage:', err);
    return false;
  }
}
