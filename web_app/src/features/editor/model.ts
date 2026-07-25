export type LineBlockStatus = 'unverified' | 'verified' | 'edited';

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface LineBlock {
  id: string;
  lineNumber: number;
  rawText: string;
  editedText: string;
  confidence: number;
  status: LineBlockStatus;
  box?: BoundingBox;
}

export interface EditorHistoryState {
  past: LineBlock[][];
  present: LineBlock[];
  future: LineBlock[][];
}

export function calculateTextStats(blocks: LineBlock[]): { words: number; characters: number } {
  const fullText = blocks.map((b) => b.editedText).join(' ');
  const trimmed = fullText.trim();
  const words = trimmed ? trimmed.split(/\s+/).length : 0;
  const characters = fullText.length;
  return { words, characters };
}

export function initialHistory(initialBlocks: LineBlock[]): EditorHistoryState {
  return {
    past: [],
    present: initialBlocks,
    future: [],
  };
}
