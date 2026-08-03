export interface DocumentItem {
  id: string;
  title: string;
  pageCount: number;
  createdAt: string;
  updatedAt: string;
  revision: number;
  status: 'draft' | 'processing' | 'review' | 'ready' | 'failed';
  latestJobId?: string;
  previewUrl?: string;
  previewText?: string;
}
