import { create } from 'zustand';
import { persist } from 'zustand/middleware';

type Theme = 'light' | 'dark' | 'system';
type Language = 'en' | 'ru';

export type DocumentStatus = 'draft' | 'processing' | 'ready' | 'error';

export interface Document {
  id: string;
  name: string;
  status: DocumentStatus;
  updatedAt: string;
  pageCount: number;
  thumbnail?: string;
  step: 'prepare' | 'regions' | 'processing' | 'result';
}

export interface Preferences {
  dateFormat: string;
  reducedMotion: boolean;
  autoPrepare: boolean;
  qualityWarnings: boolean;
  reviewLines: boolean;
  openResult: boolean;
  lowQualityBehavior: 'stop' | 'continue';
  defaultExportFormat: 'txt' | 'docx' | 'pdf' | 'searchable_pdf';
  notifyCompleted: boolean;
  notifyFailed: boolean;
  notifyBackgroundOnly: boolean;
}

interface AppState {
  theme: Theme;
  language: Language;
  user: { id: string; email: string; name: string, verified: boolean, createdAt: string } | null;
  documents: Document[];
  preferences: Preferences;
  setTheme: (theme: Theme) => void;
  setLanguage: (lang: Language) => void;
  setUser: (user: any) => void;
  logout: () => void;
  addDocument: (doc: Document) => void;
  updateDocument: (id: string, data: Partial<Document>) => void;
  deleteDocument: (id: string) => void;
  updatePreferences: (prefs: Partial<Preferences>) => void;
}

const defaultPreferences: Preferences = {
  dateFormat: 'DD.MM.YYYY',
  reducedMotion: false,
  autoPrepare: true,
  qualityWarnings: true,
  reviewLines: true,
  openResult: true,
  lowQualityBehavior: 'stop',
  defaultExportFormat: 'txt',
  notifyCompleted: true,
  notifyFailed: true,
  notifyBackgroundOnly: true,
};

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      theme: 'light',
      language: 'ru',
      user: null,
      preferences: defaultPreferences,
      documents: [
        {
          id: '1',
          name: 'Manuscript_page_01.jpg',
          status: 'ready',
          updatedAt: new Date().toISOString(),
          pageCount: 1,
          step: 'result'
        },
        {
          id: '2',
          name: 'Historical_doc_scan.png',
          status: 'draft',
          updatedAt: new Date(Date.now() - 86400000).toISOString(),
          pageCount: 1,
          step: 'prepare'
        }
      ],
      setTheme: (theme) => set({ theme }),
      setLanguage: (language) => set({ language }),
      setUser: (user) => set({ user }),
      logout: () => set({ user: null }),
      addDocument: (doc) => set((state) => ({ documents: [doc, ...state.documents] })),
      updateDocument: (id, data) => set((state) => ({
        documents: state.documents.map(d => d.id === id ? { ...d, ...data } : d)
      })),
      deleteDocument: (id) => set((state) => ({
        documents: state.documents.filter(d => d.id !== id)
      })),
      updatePreferences: (prefs) => set((state) => ({
        preferences: { ...state.preferences, ...prefs }
      })),
    }),
    {
      name: 'htr-studio-storage',
    }
  )
);
