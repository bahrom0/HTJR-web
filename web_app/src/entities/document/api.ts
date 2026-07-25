import { DocumentItem } from './model';

const STORAGE_KEY = 'htr_documents';

const MOCK_DOCUMENTS: DocumentItem[] = [
  {
    id: 'doc-1',
    title: 'Рукопись Рудаки - Страница 1',
    pageCount: 3,
    createdAt: '2026-07-20T10:00:00.000Z',
    updatedAt: '2026-07-24T15:30:00.000Z',
    status: 'completed',
    isFavorite: true,
    previewText: 'Ай дареғо ки он чунон чашмон, Безиё гаштаанду торикон...',
    rawText: 'Ай дареғо ки он чунон чашмон\nБезиё гаштаанду торикон\nЗ-он ки зулфи чу мушк будаш сиёҳ\nГашт чун ширу шуд бидуни гуноҳ',
  },
  {
    id: 'doc-2',
    title: 'Архивный документ 1928 г.',
    pageCount: 1,
    createdAt: '2026-07-22T11:15:00.000Z',
    updatedAt: '2026-07-22T11:20:00.000Z',
    status: 'draft',
    isFavorite: false,
    previewText: 'Протокол заседания комиссии по ликвидации неграмотности...',
    rawText: 'Протокол заседания комиссии по ликвидации неграмотности в Душанбе.\nДата: 14 мая 1928 года.\nПрисутствовали: член президиума...',
  },
  {
    id: 'doc-3',
    title: 'Поэма Саъди "Гулистон"',
    pageCount: 12,
    createdAt: '2026-07-23T09:00:00.000Z',
    updatedAt: '2026-07-25T08:00:00.000Z',
    status: 'processing',
    isFavorite: false,
    previewText: 'Минат худоро азза ва ҷалл ки тоъаташ муҷиби қурбат аст...',
    rawText: 'Минат худоро азза ва ҷалл ки тоъаташ муҷиби қурбат аст ва ба шукр андараш мазиди неъмат...',
  },
];

export function getDocuments(): DocumentItem[] {
  if (typeof window === 'undefined' || !window.localStorage) {
    return MOCK_DOCUMENTS;
  }
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(MOCK_DOCUMENTS));
      return MOCK_DOCUMENTS;
    }
    const parsed = JSON.parse(stored);
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(MOCK_DOCUMENTS));
    return MOCK_DOCUMENTS;
  } catch (error) {
    console.error('Failed to read documents from localStorage:', error);
    return MOCK_DOCUMENTS;
  }
}

export function getDocumentById(id: string): DocumentItem | undefined {
  const documents = getDocuments();
  return documents.find((doc) => doc.id === id);
}

export function saveDocuments(documents: DocumentItem[]): void {
  if (typeof window === 'undefined' || !window.localStorage) return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(documents));
  } catch (error) {
    console.error('Failed to save documents to localStorage:', error);
  }
}

export function toggleFavoriteDocument(id: string): DocumentItem[] {
  const documents = getDocuments();
  const updated = documents.map((doc) =>
    doc.id === id
      ? {
          ...doc,
          isFavorite: !doc.isFavorite,
          updatedAt: new Date().toISOString(),
        }
      : doc,
  );
  saveDocuments(updated);
  return updated;
}

export function deleteDocument(id: string): DocumentItem[] {
  const documents = getDocuments();
  const updated = documents.filter((doc) => doc.id !== id);
  saveDocuments(updated);
  return updated;
}

export function searchDocuments(query: string): DocumentItem[] {
  const documents = getDocuments();
  if (!query.trim()) return documents;
  const q = query.toLowerCase().trim();
  return documents.filter(
    (doc) =>
      doc.title.toLowerCase().includes(q) ||
      (doc.previewText && doc.previewText.toLowerCase().includes(q)),
  );
}

export function saveDocument(document: DocumentItem): DocumentItem[] {
  const documents = getDocuments();
  const existingIndex = documents.findIndex((d) => d.id === document.id);
  let updated: DocumentItem[];
  if (existingIndex >= 0) {
    updated = [...documents];
    updated[existingIndex] = document;
  } else {
    updated = [document, ...documents];
  }
  saveDocuments(updated);
  return updated;
}
