export interface DocumentItem {
  id: string;
  title: string;
  pageCount: number;
  createdAt: string;
  updatedAt: string;
  status: 'draft' | 'completed' | 'processing';
  isFavorite: boolean;
  previewText?: string;
  rawText?: string;
}
